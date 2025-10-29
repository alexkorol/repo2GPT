import argparse
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, List, Optional, Sequence, Set, Tuple

from git import GitCommandError, Repo
from urllib.parse import urlparse

try:
    import pyperclip  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    pyperclip = None

try:
    import tiktoken  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    tiktoken = None

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


@dataclass
class ConsolidatedChunkResult:
    path: str
    token_count: int
    file_count: int


class TokenEstimator:
    """Estimate token counts using ``tiktoken`` when available."""

    def __init__(self, enabled: bool, encoding_name: str = "cl100k_base") -> None:
        self.enabled = enabled
        self._encoding_name = encoding_name
        self._encoder: Optional[Any] = None
        self.uses_tiktoken = False
        self._strategy_description = "disabled"

        if not enabled:
            return

        if tiktoken is not None:
            self._encoder = self._load_encoder(encoding_name)
            if self._encoder is None:
                for candidate in ("gpt-4", "gpt-3.5-turbo"):
                    self._encoder = self._load_encoder(candidate, for_model=True)
                    if self._encoder is not None:
                        self._encoding_name = candidate
                        break

        if self._encoder is not None:
            self.uses_tiktoken = True
            self._strategy_description = f"tiktoken ({self._encoding_name})"
        else:
            self._strategy_description = "approximate (characters / 4)"

    @staticmethod
    def _load_encoder(name: str, for_model: bool = False) -> Optional[Any]:
        if tiktoken is None:
            return None
        try:
            if for_model:
                return tiktoken.encoding_for_model(name)
            return tiktoken.get_encoding(name)
        except Exception:  # pragma: no cover - depends on optional dependency
            return None

    def count(self, text: str) -> int:
        if not self.enabled or not text:
            return 0
        if self._encoder is not None:
            try:
                return len(self._encoder.encode(text))
            except Exception:  # pragma: no cover - defensive fallback
                pass
        # Coarse heuristic: assume ~4 characters per token.
        length = len(text)
        return (length + 3) // 4 if length else 0

    @property
    def description(self) -> str:
        return self._strategy_description


@dataclass
class RepoProcessingResult:
    repomap_path: str
    consolidated_chunks: List[ConsolidatedChunkResult]
    token_estimator: TokenEstimator


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
    token_estimator: Optional[TokenEstimator] = None,
    chunk_token_limit: Optional[int] = None,
) -> List[ConsolidatedChunkResult]:
    """Generate consolidated code output, optionally splitting into token-bounded chunks."""

    estimator = token_estimator or TokenEstimator(False)
    token_limit = chunk_token_limit if chunk_token_limit and chunk_token_limit > 0 else None
    base_path = Path(output_file)
    base_path.parent.mkdir(parents=True, exist_ok=True)

    def resolve_chunk_path(index: int) -> Path:
        if token_limit and index > 1:
            suffix = base_path.suffix
            stem = base_path.stem
            return base_path.with_name(f"{stem}_part{index:02d}{suffix}")
        return base_path

    chunk_results: List[ConsolidatedChunkResult] = []
    chunk_index = 1
    current_path = resolve_chunk_path(chunk_index)
    current_handle: Optional[Any] = None
    chunk_tokens = 0
    chunk_file_count = 0

    def open_chunk(path: Path) -> Any:
        path.parent.mkdir(parents=True, exist_ok=True)
        return path.open("w", encoding="utf-8")

    def finalize_chunk(handle: Optional[Any], path: Path, tokens: int, file_count: int) -> None:
        if handle is not None:
            handle.close()
        chunk_results.append(
            ConsolidatedChunkResult(path=str(path), token_count=tokens, file_count=file_count)
        )

    try:
        current_handle = open_chunk(current_path)

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

                header = f"\n\n---\n{normalized_relative or file_name}\n---\n\n"
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as source:
                        body = source.read()
                except Exception as exc:  # pragma: no cover - logging only
                    body = (
                        f"Could not read the file {normalized_relative or file_name}. The error is as follows:\n{exc}\n"
                    )

                file_block = f"{header}{body}"
                block_tokens = estimator.count(file_block)

                if (
                    token_limit
                    and chunk_tokens > 0
                    and chunk_tokens + block_tokens > token_limit
                ):
                    finalize_chunk(current_handle, current_path, chunk_tokens, chunk_file_count)
                    chunk_index += 1
                    current_path = resolve_chunk_path(chunk_index)
                    current_handle = open_chunk(current_path)
                    chunk_tokens = 0
                    chunk_file_count = 0

                if current_handle is None:
                    current_handle = open_chunk(current_path)

                current_handle.write(file_block)
                chunk_tokens += block_tokens
                chunk_file_count += 1

        finalize_chunk(current_handle, current_path, chunk_tokens, chunk_file_count)
        current_handle = None
    except Exception as exc:  # pragma: no cover - unexpected filesystem errors
        print(f"Error writing to consolidated file: {exc}")
        sys.exit(1)
    finally:
        if current_handle is not None:
            current_handle.close()

    return chunk_results


@dataclass
class FileStructureSummary:
    classes: List[Tuple[str, int]] = field(default_factory=list)
    functions: List[Tuple[str, int]] = field(default_factory=list)
    class_methods: List[Tuple[str, int]] = field(default_factory=list)
    object_declarations: List[Tuple[str, int]] = field(default_factory=list)
    exports: List[Tuple[str, int]] = field(default_factory=list)
    imports: List[Tuple[str, int]] = field(default_factory=list)


Analyzer = Callable[[Sequence[str]], FileStructureSummary]


def analyze_python(lines: Sequence[str]) -> FileStructureSummary:
    summary = FileStructureSummary()
    for index, line in enumerate(lines):
        match = re.search(r"def ([a-zA-Z0-9_]+)\s*\(", line)
        if match:
            summary.functions.append((match.group(1), index + 1))

        match = re.search(r"class ([a-zA-Z0-9_]+)\s*[\(:]", line)
        if match:
            summary.classes.append((match.group(1), index + 1))

    return summary


def analyze_javascript(lines: Sequence[str]) -> FileStructureSummary:
    summary = FileStructureSummary()

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

    class_patterns = [
        r"class\s+([a-zA-Z0-9_$]+)",
        r"const\s+([a-zA-Z0-9_$]+)\s*=\s*class\s*{",
    ]

    for index, line in enumerate(lines):
        for pattern in func_patterns:
            match = re.search(pattern, line)
            if match:
                summary.functions.append((match.group(1), index + 1))

        for pattern in class_patterns:
            match = re.search(pattern, line)
            if match:
                summary.classes.append((match.group(1), index + 1))

        obj_match = re.search(r"const\s+([a-zA-Z0-9_$]+)\s*=\s*{", line)
        if obj_match:
            summary.object_declarations.append((obj_match.group(1), index + 1))

        export_match = re.search(
            r"export\s+(?:const|let|var|function|class|default)?\s*(\{[^}]+\}|[a-zA-Z0-9_$]+)",
            line,
        )
        if export_match:
            summary.exports.append((export_match.group(1), index + 1))

        import_match = re.search(
            r"import\s+(?:{\s*([^}]+)\s*}|([a-zA-Z0-9_$]+))\s+from\s+['\"]([^'\"]+)['\"]",
            line,
        )
        if import_match:
            imported = import_match.group(1) or import_match.group(2)
            source = import_match.group(3)
            summary.imports.append((f"{imported} from {source}", index + 1))

    in_class = False
    current_class: Optional[str] = None
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
            if method_match and current_class:
                method_name = method_match.group(1)
                if method_name not in {"constructor", "if", "for", "while", "switch"}:
                    summary.class_methods.append((f"{current_class}.{method_name}", index + 1))

    return summary


def analyze_go(lines: Sequence[str]) -> FileStructureSummary:
    summary = FileStructureSummary()
    func_pattern = re.compile(r"^\s*func\s+(?:\([^)]+\)\s*)?([A-Za-z0-9_]+)\s*\(")
    type_pattern = re.compile(r"^\s*type\s+([A-Za-z0-9_]+)\s+(?:struct|interface)")

    for index, line in enumerate(lines):
        func_match = func_pattern.search(line)
        if func_match:
            summary.functions.append((func_match.group(1), index + 1))

        type_match = type_pattern.search(line)
        if type_match:
            summary.classes.append((type_match.group(1), index + 1))

    return summary


def analyze_rust(lines: Sequence[str]) -> FileStructureSummary:
    summary = FileStructureSummary()
    fn_pattern = re.compile(r"^\s*(?:pub\s+)?(?:async\s+)?fn\s+([a-zA-Z0-9_]+)")
    struct_pattern = re.compile(r"^\s*(?:pub\s+)?struct\s+([A-Za-z0-9_]+)")
    enum_pattern = re.compile(r"^\s*(?:pub\s+)?enum\s+([A-Za-z0-9_]+)")

    for index, line in enumerate(lines):
        fn_match = fn_pattern.search(line)
        if fn_match:
            summary.functions.append((fn_match.group(1), index + 1))

        struct_match = struct_pattern.search(line)
        if struct_match:
            summary.classes.append((struct_match.group(1), index + 1))

        enum_match = enum_pattern.search(line)
        if enum_match:
            summary.classes.append((enum_match.group(1), index + 1))

    return summary


def analyze_ruby(lines: Sequence[str]) -> FileStructureSummary:
    summary = FileStructureSummary()
    def_pattern = re.compile(r"^\s*def\s+([A-Za-z0-9_?!]+(?:\.[A-Za-z0-9_?!]+)?)")
    class_pattern = re.compile(r"^\s*class\s+([A-Za-z0-9_:]+)")

    for index, line in enumerate(lines):
        def_match = def_pattern.search(line)
        if def_match:
            summary.functions.append((def_match.group(1), index + 1))

        class_match = class_pattern.search(line)
        if class_match:
            summary.classes.append((class_match.group(1), index + 1))

    return summary


def analyze_php(lines: Sequence[str]) -> FileStructureSummary:
    summary = FileStructureSummary()
    func_pattern = re.compile(r"\bfunction\s+&?\s*([A-Za-z0-9_]+)\s*\(", re.IGNORECASE)
    class_pattern = re.compile(r"\b(class|interface|trait)\s+([A-Za-z0-9_]+)", re.IGNORECASE)

    for index, line in enumerate(lines):
        func_match = func_pattern.search(line)
        if func_match:
            summary.functions.append((func_match.group(1), index + 1))

        class_match = class_pattern.search(line)
        if class_match:
            summary.classes.append((class_match.group(2), index + 1))

    return summary


def analyze_generic(lines: Sequence[str]) -> FileStructureSummary:
    summary = FileStructureSummary()
    func_pattern = re.compile(
        r"(?:public|private|protected|static|\s)+[\w\<\>\[\]]+\s+([a-zA-Z0-9_]+)\s*\("
    )
    class_pattern = re.compile(
        r"(?:public|private|protected|static|\s)+class +([a-zA-Z0-9_]+)"
    )

    for index, line in enumerate(lines):
        func_match = func_pattern.search(line)
        if func_match:
            summary.functions.append((func_match.group(1), index + 1))

        class_match = class_pattern.search(line)
        if class_match:
            summary.classes.append((class_match.group(1), index + 1))

    return summary


ANALYZER_DISPATCH: dict[str, Analyzer] = {
    ".py": analyze_python,
    ".js": analyze_javascript,
    ".jsx": analyze_javascript,
    ".ts": analyze_javascript,
    ".tsx": analyze_javascript,
    ".go": analyze_go,
    ".rs": analyze_rust,
    ".rb": analyze_ruby,
    ".php": analyze_php,
}


def write_file_structure_summary(file_ext: str, file_path: str, handle, indent: str) -> None:
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as code_file:
            lines = code_file.read().splitlines()
    except Exception as exc:
        handle.write(f"{indent}Error analyzing file: {exc}\n")
        return

    try:
        analyzer = ANALYZER_DISPATCH.get(file_ext, analyze_generic)
        summary = analyzer(lines)
    except Exception as exc:  # pragma: no cover - regex failures
        handle.write(f"{indent}Error analyzing file: {exc}\n")
        return

    if summary.classes:
        handle.write(f"{indent}Classes:\n")
        for cls, line_no in summary.classes:
            handle.write(f"{indent}    {cls} (Line {line_no})\n")

    if summary.functions:
        handle.write(f"{indent}Functions:\n")
        for func, line_no in summary.functions:
            handle.write(f"{indent}    {func} (Line {line_no})\n")

    if file_ext in {".js", ".jsx", ".ts", ".tsx"}:
        if summary.class_methods:
            handle.write(f"{indent}Class Methods:\n")
            for method, line_no in summary.class_methods:
                handle.write(f"{indent}    {method} (Line {line_no})\n")

        if summary.object_declarations:
            handle.write(f"{indent}Objects:\n")
            for obj, line_no in summary.object_declarations:
                handle.write(f"{indent}    {obj} (Line {line_no})\n")

        if summary.exports:
            handle.write(f"{indent}Exports:\n")
            for export, line_no in summary.exports:
                handle.write(f"{indent}    {export} (Line {line_no})\n")

        if summary.imports:
            handle.write(f"{indent}Imports:\n")
            for imp, line_no in summary.imports:
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


def handle_clipboard(
    copy_option: Optional[str],
    repomap_path: str,
    consolidated_paths: Sequence[str],
) -> None:
    if not copy_option:
        return

    selections: List[Tuple[str, str]] = []

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


def process_repository(local_dir: str, args: argparse.Namespace) -> RepoProcessingResult:
    options = build_processing_options(local_dir, args)

    repomap_path = os.path.abspath(args.repomap)
    consolidated_path = os.path.abspath(args.consolidated)

    skip_relatives = resolve_skip_paths(local_dir, (repomap_path, consolidated_path))

    generate_repomap(local_dir, repomap_path, options, skip_relatives)
    token_estimator = TokenEstimator(
        enabled=bool(args.enable_token_counts or (args.chunk_size and args.chunk_size > 0))
    )
    chunk_limit = args.chunk_size if args.chunk_size and args.chunk_size > 0 else None
    consolidated_chunks = generate_consolidated_file(
        local_dir,
        consolidated_path,
        options,
        skip_relatives,
        token_estimator=token_estimator,
        chunk_token_limit=chunk_limit,
    )

    print(f"Repo map generated: {repomap_path}")
    if len(consolidated_chunks) == 1:
        print(f"Consolidated code file generated: {consolidated_chunks[0].path}")
    else:
        print("Consolidated code chunks generated:")
        for index, chunk in enumerate(consolidated_chunks, start=1):
            token_fragment = (
                f" (~{chunk.token_count} tokens)" if token_estimator.enabled else ""
            )
            print(f"  Part {index:02d}: {chunk.path}{token_fragment}")

    if token_estimator.enabled:
        if not token_estimator.uses_tiktoken:
            print(
                "Token counts are approximate; install 'tiktoken' for tokenizer-accurate measurements."
            )
        total_tokens = sum(chunk.token_count for chunk in consolidated_chunks)
        print("Token statistics:")
        for index, chunk in enumerate(consolidated_chunks, start=1):
            print(
                f"  Chunk {index:02d}: ~{chunk.token_count} tokens across {chunk.file_count} files ({chunk.path})"
            )
        print(f"  Total estimated tokens: ~{total_tokens} ({token_estimator.description}).")
        if chunk_limit:
            print(f"  Token ceiling per chunk: {chunk_limit}")

    return RepoProcessingResult(
        repomap_path=repomap_path,
        consolidated_chunks=consolidated_chunks,
        token_estimator=token_estimator,
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
