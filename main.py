import argparse
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable, List, Optional, Sequence, Set, Tuple

from git import GitCommandError, Repo
from urllib.parse import urlparse

try:
    import pyperclip  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    pyperclip = None

DEFAULT_CODE_EXTENSIONS: Set[str] = {
    ".py",
    ".pyi",
    ".pyw",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".mjs",
    ".cjs",
    ".java",
    ".kt",
    ".kts",
    ".go",
    ".rb",
    ".rs",
    ".c",
    ".h",
    ".cpp",
    ".cc",
    ".cxx",
    ".hpp",
    ".hh",
    ".hxx",
    ".cs",
    ".swift",
    ".m",
    ".mm",
    ".php",
    ".scala",
    ".clj",
    ".cljs",
    ".hs",
    ".lua",
    ".r",
    ".jl",
    ".dart",
    ".sql",
    ".sh",
    ".bash",
    ".zsh",
    ".ps1",
    ".psm1",
    ".psd1",
    ".bat",
    ".cmd",
    ".fs",
    ".fsx",
    ".f90",
    ".f95",
    ".erl",
    ".ex",
    ".exs",
    ".vb",
    ".groovy",
    ".gradle",
    ".cmake",
    ".svelte",
    ".vue",
}

ALWAYS_INCLUDE_FILENAMES: Set[str] = {
    "Dockerfile",
    "Makefile",
    "CMakeLists.txt",
    "BUILD",
    "WORKSPACE",
    "Gemfile",
    "Rakefile",
    "Procfile",
}

DEFAULT_IGNORE_PATTERNS_RAW: Sequence[str] = (
    ".git/",
    ".hg/",
    ".svn/",
    ".idea/",
    ".vscode/",
    ".vs/",
    ".venv/",
    "venv/",
    ".mypy_cache/",
    ".pytest_cache/",
    "__pycache__/",
    "node_modules/",
    "bower_components/",
    "dist/",
    "build/",
    "coverage/",
    "logs/",
    "tmp/",
    "temp/",
    "deps/",
    "vendor/",
    "third_party/",
    ".gradle/",
    ".terraform/",
    ".next/",
    ".nuxt/",
    ".svelte-kit/",
    ".cache/",
    ".parcel-cache/",
    ".ruff_cache/",
    "public/build/",
    "public/dist/",
    "*.log",
    "*.tmp",
    "*.bak",
    "*.lock",
    "*.sqlite",
    "*.db",
    "*.sqlite3",
    "*.min.js",
    "*.min.css",
    "*.map",
    "*.png",
    "*.jpg",
    "*.jpeg",
    "*.gif",
    "*.svg",
    "*.ico",
    "*.bmp",
    "*.mp3",
    "*.mp4",
    "*.mov",
    "*.avi",
    "*.wav",
    "*.flac",
    "*.zip",
    "*.gz",
    "*.bz2",
    "*.xz",
    "*.7z",
    "*.tar",
    "*.tgz",
    "*.rar",
    "*.pdf",
    "*.doc",
    "*.docx",
    "*.ppt",
    "*.pptx",
    "*.xls",
    "*.xlsx",
    "*.exe",
    "*.dll",
    "*.so",
    "*.bin",
    "*.dylib",
    "*.class",
    "*.jar",
    "*.war",
    "*.ear",
    "*.apk",
    "*.ipa",
    "*.msi",
    "*.obj",
    "*.o",
    "*.a",
    "*.lib",
    "*.pyc",
    "*.pyo",
    "*.whl",
    "*.ttf",
    "*.woff",
    "*.woff2",
    "*.eot",
)

DEFAULT_DIRNAME_DENYLIST: Set[str] = {
    ".git",
    ".hg",
    ".svn",
    ".idea",
    ".vscode",
    ".vs",
    ".venv",
    "venv",
    ".mypy_cache",
    ".pytest_cache",
    "__pycache__",
    "node_modules",
    "bower_components",
    "dist",
    "build",
    "coverage",
    "logs",
    "tmp",
    "temp",
    "deps",
    "vendor",
    "third_party",
    ".gradle",
    ".terraform",
    ".next",
    ".nuxt",
    ".svelte-kit",
    ".cache",
    ".parcel-cache",
    ".ruff_cache",
}

DEFAULT_MAX_FILE_BYTES = 500_000


def _ordered_unique(values: Iterable[str]) -> List[str]:
    seen: Set[str] = set()
    ordered: List[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            ordered.append(value)
    return ordered


def _normalize_pattern(pattern: str) -> List[str]:
    pattern = pattern.strip()
    if not pattern or pattern.startswith("#"):
        return []
    normalized = pattern.replace("\\", "/")
    if normalized.startswith("/"):
        normalized = normalized[1:]
    if normalized.endswith("/"):
        base = normalized.rstrip("/")
        if not base:
            return []
        variants = [base, f"{base}/**", f"**/{base}", f"**/{base}/**"]
        return _ordered_unique(variants)
    return [normalized]


def _expand_patterns(patterns: Iterable[str]) -> List[str]:
    expanded: List[str] = []
    for pattern in patterns:
        expanded.extend(_normalize_pattern(pattern))
    return expanded


def to_posix_path(path: str) -> str:
    return path.replace("\\", "/")


def matches_patterns(path: str, patterns: Iterable[str]) -> bool:
    if not patterns:
        return False
    posix_path = PurePosixPath(path)
    return any(posix_path.match(pattern) for pattern in patterns)


def matches_include(path: str, include_patterns: Iterable[str]) -> bool:
    """Return ``True`` if ``path`` is explicitly requested by include patterns."""

    return matches_patterns(path, include_patterns)


def load_pattern_file(path: Path) -> List[str]:
    patterns: List[str] = []
    if not path.exists():
        return patterns
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                patterns.extend(_normalize_pattern(line))
    except OSError:
        return patterns
    return patterns


DEFAULT_IGNORE_PATTERNS = _expand_patterns(DEFAULT_IGNORE_PATTERNS_RAW)


@dataclass
class ProcessingOptions:
    ignore_patterns: List[str]
    include_patterns: List[str]
    allowed_extensions: Set[str]
    special_filenames: Set[str]
    max_file_bytes: Optional[int]
    allow_non_code: bool


def normalize_relative_path(path: str) -> str:
    if not path or path == ".":
        return ""
    posix = to_posix_path(path)
    if posix.startswith("./"):
        posix = posix[2:]
    return posix


def join_relative_path(base: str, name: str) -> str:
    normalized_base = normalize_relative_path(base)
    name_posix = to_posix_path(name)
    if not normalized_base:
        return name_posix
    return f"{normalized_base}/{name_posix}"


def should_skip_directory(relative_path: str, options: ProcessingOptions) -> bool:
    if not relative_path:
        return False
    posix = normalize_relative_path(relative_path)
    if not posix:
        return False
    parts = posix.split("/")
    if any(part in DEFAULT_DIRNAME_DENYLIST for part in parts):
        return True
    return matches_patterns(posix, options.ignore_patterns)


def is_code_file(file_name: str, options: ProcessingOptions) -> bool:
    ext = os.path.splitext(file_name)[1].lower()
    if ext in options.allowed_extensions:
        return True
    return file_name in options.special_filenames


def is_binary_file(file_path: str) -> bool:
    try:
        with open(file_path, "rb") as handle:
            chunk = handle.read(1024)
    except OSError:
        return True
    return b"\0" in chunk


def should_include_file(relative_path: str, file_name: str, options: ProcessingOptions) -> bool:
    posix = normalize_relative_path(relative_path)
    if matches_patterns(posix, options.ignore_patterns):
        return False
    if matches_include(posix, options.include_patterns):
        return True
    if options.allow_non_code:
        return True
    return is_code_file(file_name, options)


def resolve_skip_paths(local_dir: str, outputs: Sequence[str]) -> Set[str]:
    skip: Set[str] = set()
    local_abs = os.path.abspath(local_dir)
    for output in outputs:
        output_abs = os.path.abspath(output)
        try:
            rel = os.path.relpath(output_abs, local_abs)
        except ValueError:
            continue
        if rel.startswith(".."):
            continue
        normalized = normalize_relative_path(rel)
        if normalized:
            skip.add(normalized)
    return skip


def load_gitignore_patterns(local_dir: str) -> List[str]:
    patterns: List[str] = []
    for candidate in (Path(local_dir) / ".gitignore", Path(local_dir) / ".git" / "info" / "exclude"):
        patterns.extend(load_pattern_file(candidate))
    return patterns


def build_processing_options(local_dir: str, args: argparse.Namespace) -> ProcessingOptions:
    ignore_patterns = list(DEFAULT_IGNORE_PATTERNS)
    ignore_patterns.extend(load_gitignore_patterns(local_dir))

    gptignore_path = Path(args.gptignore) if args.gptignore else Path(local_dir) / ".gptignore"
    ignore_patterns.extend(load_pattern_file(gptignore_path))

    if args.extra_ignore:
        ignore_patterns.extend(_expand_patterns(args.extra_ignore))

    include_patterns: List[str] = []
    gptinclude_path = Path(args.gptinclude) if args.gptinclude else Path(local_dir) / ".gptinclude"
    include_patterns.extend(load_pattern_file(gptinclude_path))

    if args.extra_include:
        include_patterns.extend(_expand_patterns(args.extra_include))

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


def generate_consolidated_file(
    local_dir: str,
    output_file: str,
    options: ProcessingOptions,
    skip_relatives: Set[str],
) -> None:
    """Generates a consolidated text file containing the relevant code files in the repository."""

    Path(output_file).parent.mkdir(parents=True, exist_ok=True)

    try:
        with open(output_file, "w", encoding="utf-8") as handle:
            for root, dirs, files in os.walk(local_dir):
                relative_root = os.path.relpath(root, local_dir)
                if should_skip_directory(relative_root, options):
                    dirs.clear()
                    continue

                dirs[:] = [
                    d
                    for d in dirs
                    if not should_skip_directory(join_relative_path(relative_root, d), options)
                ]

                for file_name in files:
                    relative_file = join_relative_path(relative_root, file_name)
                    normalized_relative = normalize_relative_path(relative_file)

                    if normalized_relative in skip_relatives:
                        continue

                    if not should_include_file(relative_file, file_name, options):
                        continue

                    file_path = os.path.join(root, file_name)

                    try:
                        if options.max_file_bytes and os.path.getsize(file_path) > options.max_file_bytes:
                            continue
                    except OSError:
                        continue

                    if is_binary_file(file_path):
                        continue

                    handle.write(f"\n\n---\n{normalized_relative or file_name}\n---\n\n")
                    try:
                        with open(file_path, "r", encoding="utf-8", errors="ignore") as source:
                            handle.write(source.read())
                    except Exception as exc:  # pragma: no cover - logging only
                        handle.write(
                            f"Could not read the file {normalized_relative or file_name}. The error is as follows:\n{exc}\n"
                        )
    except Exception as exc:  # pragma: no cover - unexpected filesystem errors
        print(f"Error writing to consolidated file: {exc}")
        sys.exit(1)


def write_file_structure_summary(file_ext: str, file_path: str, handle, indent: str) -> None:
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as code_file:
            lines = code_file.read().splitlines()
    except Exception as exc:
        handle.write(f"{indent}Error analyzing file: {exc}\n")
        return

    functions: List[Tuple[str, int]] = []
    classes: List[Tuple[str, int]] = []
    class_methods: List[Tuple[str, int]] = []
    object_declarations: List[Tuple[str, int]] = []
    exports: List[Tuple[str, int]] = []
    imports: List[Tuple[str, int]] = []

    try:
        if file_ext == ".py":
            functions = [
                (match.group(1), index + 1)
                for index, line in enumerate(lines)
                for match in [re.search(r"def ([a-zA-Z0-9_]+)\s*\(", line)]
                if match
            ]
            classes = [
                (match.group(1), index + 1)
                for index, line in enumerate(lines)
                for match in [re.search(r"class ([a-zA-Z0-9_]+)\s*[\(:]", line)]
                if match
            ]
        elif file_ext in {".js", ".jsx", ".ts", ".tsx"}:
            func_patterns = [
                r"function\s+([a-zA-Z0-9_$]+)\s*\(",
                r"const\s+([a-zA-Z0-9_$]+)\s*=\s*function\s*\(",
                r"const\s+([a-zA-Z0-9_$]+)\s*=\s*\([^\)]*\)\s*=>",
                r"let\s+([a-zA-Z0-9_$]+)\s*=\s*function\s*\(",
                r"let\s+([a-zA-Z0-9_$]+)\s*=\s*\([^\)]*\)\s*=>",
                r"var\s+([a-zA-Z0-9_$]+)\s*=\s*function\s*\(",
                r"var\s+([a-zA-Z0-9_$]+)\s*=\s*\([^\)]*\)\s*=>",
                r"([a-zA-Z0-9_$]+):\s*function\s*\(",
                r"([a-zA-Z0-9_$]+)\s*\([^\)]*\)\s*{",
                r"async\s+function\s+([a-zA-Z0-9_$]+)\s*\(",
                r"([a-zA-Z0-9_$]+)\s*=\s*async\s*\([^\)]*\)\s*=>",
            ]
            for index, line in enumerate(lines):
                for pattern in func_patterns:
                    match = re.search(pattern, line)
                    if match:
                        functions.append((match.group(1), index + 1))

            class_patterns = [
                r"class\s+([a-zA-Z0-9_$]+)",
                r"const\s+([a-zA-Z0-9_$]+)\s*=\s*class\s*{",
            ]
            for index, line in enumerate(lines):
                for pattern in class_patterns:
                    match = re.search(pattern, line)
                    if match:
                        classes.append((match.group(1), index + 1))

            in_class = False
            current_class = None
            brace_count = 0
            for index, line in enumerate(lines):
                class_start = re.search(
                    r"class\s+([a-zA-Z0-9_$]+)|const\s+([a-zA-Z0-9_$]+)\s*=\s*class",
                    line,
                )
                if class_start:
                    in_class = True
                    current_class = class_start.group(1) or class_start.group(2)
                    brace_count += line.count("{") - line.count("}")
                elif in_class:
                    brace_count += line.count("{") - line.count("}")
                    if brace_count <= 0:
                        in_class = False
                        current_class = None

                if in_class:
                    method_match = re.search(r"^\s*([a-zA-Z0-9_$]+)\s*\([^\)]*\)\s*{", line)
                    if method_match:
                        method_name = method_match.group(1)
                        if method_name not in {"constructor", "if", "for", "while", "switch"} and current_class:
                            class_methods.append((f"{current_class}.{method_name}", index + 1))

            for index, line in enumerate(lines):
                obj_match = re.search(r"const\s+([a-zA-Z0-9_$]+)\s*=\s*{", line)
                if obj_match:
                    object_declarations.append((obj_match.group(1), index + 1))

                export_match = re.search(
                    r"export\s+(?:const|let|var|function|class|default)?\s*(\{[^}]+\}|[a-zA-Z0-9_$]+)",
                    line,
                )
                if export_match:
                    exports.append((export_match.group(1), index + 1))

                import_match = re.search(
                    r"import\s+(?:{\s*([^}]+)\s*}|([a-zA-Z0-9_$]+))\s+from\s+['\"]([^'\"]+)['\"]",
                    line,
                )
                if import_match:
                    imported = import_match.group(1) or import_match.group(2)
                    source = import_match.group(3)
                    imports.append((f"{imported} from {source}", index + 1))
        else:
            functions = [
                (match.group(1), index + 1)
                for index, line in enumerate(lines)
                for match in [
                    re.search(r"(?:public|private|protected|static|\s)+[\w\<\>\[\]]+\s+([a-zA-Z0-9_]+)\s*\(", line)
                ]
                if match
            ]
            classes = [
                (match.group(1), index + 1)
                for index, line in enumerate(lines)
                for match in [
                    re.search(r"(?:public|private|protected|static|\s)+class +([a-zA-Z0-9_]+)", line)
                ]
                if match
            ]
    except Exception as exc:  # pragma: no cover - regex failures
        handle.write(f"{indent}Error analyzing file: {exc}\n")
        return

    if classes:
        handle.write(f"{indent}Classes:\n")
        for cls, line_no in classes:
            handle.write(f"{indent}    {cls} (Line {line_no})\n")

    if functions:
        handle.write(f"{indent}Functions:\n")
        for func, line_no in functions:
            handle.write(f"{indent}    {func} (Line {line_no})\n")

    if file_ext in {".js", ".jsx", ".ts", ".tsx"}:
        if class_methods:
            handle.write(f"{indent}Class Methods:\n")
            for method, line_no in class_methods:
                handle.write(f"{indent}    {method} (Line {line_no})\n")

        if object_declarations:
            handle.write(f"{indent}Objects:\n")
            for obj, line_no in object_declarations:
                handle.write(f"{indent}    {obj} (Line {line_no})\n")

        if exports:
            handle.write(f"{indent}Exports:\n")
            for export, line_no in exports:
                handle.write(f"{indent}    {export} (Line {line_no})\n")

        if imports:
            handle.write(f"{indent}Imports:\n")
            for imp, line_no in imports:
                handle.write(f"{indent}    {imp} (Line {line_no})\n")


def generate_repomap(
    local_dir: str,
    output_file: str,
    options: ProcessingOptions,
    skip_relatives: Set[str],
) -> None:
    """Generates a repo map of the repository's file structure with details about classes and functions."""

    Path(output_file).parent.mkdir(parents=True, exist_ok=True)

    try:
        with open(output_file, "w", encoding="utf-8") as handle:
            repo_name = os.path.basename(os.path.abspath(local_dir))
            handle.write(f"{repo_name}\n")

            for root, dirs, files in os.walk(local_dir):
                relative_root = os.path.relpath(root, local_dir)
                if should_skip_directory(relative_root, options):
                    dirs.clear()
                    continue

                dirs[:] = [
                    d
                    for d in dirs
                    if not should_skip_directory(join_relative_path(relative_root, d), options)
                ]

                normalized_root = normalize_relative_path(relative_root)
                level = normalized_root.count("/") if normalized_root else 0
                indent = " " * 4 * level

                try:
                    if normalized_root:
                        handle.write(f"{indent}{os.path.basename(root)}\n")

                    sub_indent = " " * 4 * (level + 1)
                    for file_name in files:
                        relative_file = join_relative_path(relative_root, file_name)
                        normalized_relative = normalize_relative_path(relative_file)

                        if normalized_relative in skip_relatives:
                            continue

                        if not should_include_file(relative_file, file_name, options):
                            continue

                        file_path = os.path.join(root, file_name)

                        try:
                            if options.max_file_bytes and os.path.getsize(file_path) > options.max_file_bytes:
                                continue
                        except OSError:
                            continue

                        if is_binary_file(file_path):
                            continue

                        handle.write(f"{sub_indent}{file_name}\n")

                        if is_code_file(file_name, options):
                            write_file_structure_summary(
                                os.path.splitext(file_name)[1].lower(),
                                file_path,
                                handle,
                                sub_indent + " " * 4,
                            )
                except UnicodeEncodeError:
                    print(f"Warning: Skipping directory with unsupported characters: {root}")
                    continue
    except Exception as exc:  # pragma: no cover - unexpected filesystem errors
        print(f"Error writing to repomap file: {exc}")
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


def handle_clipboard(copy_option: Optional[str], repomap_path: str, consolidated_path: str) -> None:
    if not copy_option:
        return

    selections: List[Tuple[str, str]] = []

    if copy_option in {"map", "both"} and os.path.exists(repomap_path):
        selections.append(("repo map", Path(repomap_path).read_text(encoding="utf-8", errors="ignore")))

    if copy_option in {"code", "both"} and os.path.exists(consolidated_path):
        selections.append(
            ("consolidated code", Path(consolidated_path).read_text(encoding="utf-8", errors="ignore"))
        )

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


def process_repository(local_dir: str, args: argparse.Namespace) -> Tuple[str, str]:
    options = build_processing_options(local_dir, args)

    repomap_path = os.path.abspath(args.repomap)
    consolidated_path = os.path.abspath(args.consolidated)

    skip_relatives = resolve_skip_paths(local_dir, (repomap_path, consolidated_path))

    generate_repomap(local_dir, repomap_path, options, skip_relatives)
    generate_consolidated_file(local_dir, consolidated_path, options, skip_relatives)

    print(f"Repo map generated: {repomap_path}")
    print(f"Consolidated code file generated: {consolidated_path}")

    return repomap_path, consolidated_path


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
    return parser.parse_args(argv if argv is not None else sys.argv[1:])


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = parse_arguments(argv)
    input_path = args.input

    if is_valid_url(input_path):
        with tempfile.TemporaryDirectory() as temp_dir:
            local_dir = os.path.join(temp_dir, "repo")
            clone_repository(input_path, local_dir)
            repomap_path, consolidated_path = process_repository(local_dir, args)
    elif os.path.isdir(input_path):
        repomap_path, consolidated_path = process_repository(input_path, args)
    else:
        print("Invalid input. Please provide a valid GitHub repository URL or a local directory path.")
        sys.exit(1)

    handle_clipboard(args.copy, repomap_path, consolidated_path)


if __name__ == "__main__":
    main()
