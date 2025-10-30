import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

from git import GitCommandError, Repo
from urllib.parse import urlparse

try:
    import pyperclip  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    pyperclip = None

from repo2gpt.service import (
    ALWAYS_INCLUDE_FILENAMES,
    DEFAULT_CODE_EXTENSIONS,
    DEFAULT_IGNORE_PATTERNS,
    ConsolidatedChunkResult,
    ProcessingOptions,
    RepoProcessingResult,
    RepoSnapshotChunk,
    TokenEstimator,
    collect_repo_snapshot,
    expand_patterns,
    load_gitignore_patterns,
    load_pattern_file,
    resolve_skip_paths,
)
from repo2gpt.service import DEFAULT_MAX_FILE_BYTES as SERVICE_DEFAULT_MAX_FILE_BYTES

DEFAULT_MAX_FILE_BYTES = SERVICE_DEFAULT_MAX_FILE_BYTES  # re-export for backward compatibility


def _ordered_unique(values: Iterable[str]) -> List[str]:
    seen = set()
    ordered: List[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


def build_processing_options(local_dir: str, args: argparse.Namespace) -> ProcessingOptions:
    ignore_patterns = list(DEFAULT_IGNORE_PATTERNS)
    ignore_patterns.extend(load_gitignore_patterns(local_dir))

    gptignore_path = Path(args.gptignore) if args.gptignore else Path(local_dir) / ".gptignore"
    ignore_patterns.extend(load_pattern_file(gptignore_path))

    if args.extra_ignore:
        ignore_patterns.extend(expand_patterns(args.extra_ignore))

    include_patterns: List[str] = []
    gptinclude_path = Path(args.gptinclude) if args.gptinclude else Path(local_dir) / ".gptinclude"
    include_patterns.extend(load_pattern_file(gptinclude_path))

    if args.extra_include:
        include_patterns.extend(expand_patterns(args.extra_include))

    allowed_extensions = {ext.lower() for ext in DEFAULT_CODE_EXTENSIONS}
    if args.extra_extensions:
        for ext in args.extra_extensions:
            cleaned = ext.lower()
            if not cleaned.startswith("."):
                cleaned = f".{cleaned}"
            allowed_extensions.add(cleaned)

    ignore_patterns = _ordered_unique(ignore_patterns)
    include_patterns = _ordered_unique(include_patterns)

    max_file_bytes = args.max_file_bytes if args.max_file_bytes and args.max_file_bytes > 0 else None

    return ProcessingOptions(
        ignore_patterns=ignore_patterns,
        include_patterns=include_patterns,
        allowed_extensions=allowed_extensions,
        special_filenames=ALWAYS_INCLUDE_FILENAMES,
        max_file_bytes=max_file_bytes,
        allow_non_code=args.include_all,
    )


def is_valid_url(url: str) -> bool:
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc, result.path])
    except ValueError:
        return False


def clone_repository(repo_url: str, local_dir: str) -> None:
    try:
        Repo.clone_from(repo_url, local_dir)
    except GitCommandError as exc:
        print(f"Error cloning repository: {exc}")
        sys.exit(1)


def copy_to_clipboard(text: str) -> bool:
    if not text:
        return False

    if pyperclip is not None:
        try:
            pyperclip.copy(text)
            return True
        except pyperclip.PyperclipException:
            pass

    try:
        if sys.platform.startswith("win"):
            subprocess.run(["clip"], input=text, text=True, check=True)
            return True
        if sys.platform == "darwin":
            subprocess.run(["pbcopy"], input=text, text=True, check=True)
            return True
        subprocess.run(["xclip", "-selection", "clipboard"], input=text, text=True, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def handle_clipboard(
    copy_option: Optional[str],
    repomap_path: str,
    consolidated_paths: Sequence[str],
) -> None:
    if not copy_option:
        return

    selections: List[tuple[str, str]] = []

    if copy_option in {"map", "both"} and os.path.exists(repomap_path):
        selections.append(("repo map", Path(repomap_path).read_text(encoding="utf-8", errors="ignore")))

    if copy_option in {"code", "both"}:
        consolidated_blobs: List[str] = []
        for index, path in enumerate(consolidated_paths, start=1):
            if not os.path.exists(path):
                continue
            content = Path(path).read_text(encoding="utf-8", errors="ignore")
            if len(consolidated_paths) > 1:
                content = f"# Chunk {index:02d} - {Path(path).name}\n\n{content}"
            consolidated_blobs.append(content)

        if consolidated_blobs:
            selections.append(("consolidated code", "\n\n".join(consolidated_blobs)))

    if not selections:
        print("Nothing to copy to the clipboard.")
        return

    if copy_option == "both":
        text_to_copy = "\n\n".join(f"# {label.title()}\n\n{content}" for label, content in selections)
        description = "repo map and consolidated code"
    else:
        description, text_to_copy = selections[0]

    if copy_to_clipboard(text_to_copy):
        print(f"Copied {description} to the clipboard.")
    else:
        print("Unable to copy output to the clipboard automatically.")


def _resolve_chunk_path(base_path: Path, index: int, chunk_limit: Optional[int]) -> Path:
    if chunk_limit and index > 1:
        suffix = base_path.suffix
        stem = base_path.stem
        return base_path.with_name(f"{stem}_part{index:02d}{suffix}")
    return base_path


def process_repository(local_dir: str, args: argparse.Namespace) -> RepoProcessingResult:
    options = build_processing_options(local_dir, args)

    repomap_path = os.path.abspath(args.repomap)
    consolidated_path = os.path.abspath(args.consolidated)

    skip_relatives = resolve_skip_paths(local_dir, (repomap_path, consolidated_path))

    estimator = TokenEstimator(
        enabled=bool(args.enable_token_counts or (args.chunk_size and args.chunk_size > 0))
    )
    chunk_limit = args.chunk_size if args.chunk_size and args.chunk_size > 0 else None

    chunk_results: List[ConsolidatedChunkResult] = []

    def repomap_writer(text: str) -> None:
        path = Path(repomap_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def chunk_writer(chunk: RepoSnapshotChunk) -> None:
        path = _resolve_chunk_path(Path(consolidated_path), chunk.index, chunk_limit)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(chunk.content, encoding="utf-8")
        chunk_results.append(
            ConsolidatedChunkResult(
                path=str(path),
                token_count=chunk.token_count,
                file_count=chunk.file_count,
            )
        )

    snapshot = collect_repo_snapshot(
        local_dir,
        options,
        skip_relatives=skip_relatives,
        token_estimator=estimator,
        chunk_token_limit=chunk_limit,
        repomap_writer=repomap_writer,
        chunk_writer=chunk_writer,
    )

    for warning in snapshot.warnings:
        print(warning)

    print(f"Repo map generated: {repomap_path}")
    if len(chunk_results) == 1:
        print(f"Consolidated code file generated: {chunk_results[0].path}")
    else:
        print("Consolidated code chunks generated:")
        for index, chunk in enumerate(chunk_results, start=1):
            token_fragment = f" (~{chunk.token_count} tokens)" if estimator.enabled else ""
            print(f"  Part {index:02d}: {chunk.path}{token_fragment}")

    if estimator.enabled:
        if not estimator.uses_tiktoken:
            print("Token counts are approximate; install 'tiktoken' for tokenizer-accurate measurements.")
        total_tokens = sum(chunk.token_count for chunk in chunk_results)
        print("Token statistics:")
        for index, chunk in enumerate(chunk_results, start=1):
            print(
                f"  Chunk {index:02d}: ~{chunk.token_count} tokens across {chunk.file_count} files ({chunk.path})"
            )
        print(f"  Total estimated tokens: ~{total_tokens} ({estimator.description}).")
        if chunk_limit:
            print(f"  Token ceiling per chunk: {chunk_limit}")

    return RepoProcessingResult(
        repomap_path=repomap_path,
        consolidated_chunks=chunk_results,
        token_estimator=estimator,
    )


def parse_arguments(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a repo map and consolidated code bundle for LLM workflows."
    )
    parser.add_argument("input", help="GitHub repository URL or local directory path.")
    parser.add_argument(
        "--repomap",
        default="repomap.txt",
        help="Path to write the repo map output (default: %(default)s).",
    )
    parser.add_argument(
        "--consolidated",
        default="consolidated_code.txt",
        help="Path to write the consolidated code output (default: %(default)s).",
    )
    parser.add_argument(
        "--copy",
        choices=("map", "code", "both"),
        help="Copy the repo map, consolidated code, or both to the clipboard after generation.",
    )
    parser.add_argument(
        "--gptignore",
        help="Path to a .gptignore file with additional ignore patterns.",
    )
    parser.add_argument(
        "--gptinclude",
        help="Path to a .gptinclude file with include patterns.",
    )
    parser.add_argument(
        "--extra-ignore",
        nargs="+",
        help="Additional glob patterns to ignore.",
    )
    parser.add_argument(
        "--extra-include",
        nargs="+",
        help="Additional glob patterns to include.",
    )
    parser.add_argument(
        "--extra-extensions",
        nargs="+",
        help="Additional file extensions to treat as code.",
    )
    parser.add_argument(
        "--max-file-bytes",
        type=int,
        default=DEFAULT_MAX_FILE_BYTES,
        help="Skip files larger than this many bytes (default: %(default)s). Use 0 to disable.",
    )
    parser.add_argument(
        "--include-all",
        action="store_true",
        help="Include non-code files by default (combine with include/ignore patterns as needed).",
    )
    parser.add_argument(
        "--enable-token-counts",
        action="store_true",
        help="Estimate token usage for the consolidated output (requires optional 'tiktoken' for best accuracy).",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=0,
        help="Split consolidated output into chunks capped at approximately this many tokens (default: %(default)s, 0 disables).",
    )
    return parser.parse_args(argv if argv is not None else sys.argv[1:])


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = parse_arguments(argv)
    input_path = args.input

    result: RepoProcessingResult
    if is_valid_url(input_path):
        with tempfile.TemporaryDirectory() as temp_dir:
            local_dir = os.path.join(temp_dir, "repo")
            clone_repository(input_path, local_dir)
            result = process_repository(local_dir, args)
    elif os.path.isdir(input_path):
        result = process_repository(input_path, args)
    else:
        print("Invalid input. Please provide a valid GitHub repository URL or a local directory path.")
        sys.exit(1)

    handle_clipboard(
        args.copy,
        result.repomap_path,
        [chunk.path for chunk in result.consolidated_chunks],
    )


if __name__ == "__main__":
    main()
