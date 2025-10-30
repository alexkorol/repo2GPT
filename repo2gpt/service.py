from __future__ import annotations

import io
import os
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, List, Optional, Sequence, Set, TextIO, Tuple

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

DEFAULT_DIRNAME_DENYLIST: Set[str] = {
    "node_modules",
    "vendor",
    "deps",
    "third_party",
    "__pycache__",
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
)

DEFAULT_MAX_FILE_BYTES = 500_000


def to_posix_path(path: str) -> str:
    return path.replace("\\", "/")


def _normalize_pattern(line: str) -> List[str]:
    line = line.strip()
    if not line or line.startswith("#"):
        return []

    # ``pathlib.PurePosixPath.match`` works with relative paths, so we strip any
    # leading ``/`` to keep root-anchored ignores functional.
    normalized = line.lstrip("/")
    if not normalized:
        return []

    patterns: List[str] = []

    def add(pattern: str) -> None:
        if pattern and pattern not in patterns:
            patterns.append(pattern)

    if normalized.endswith("/"):
        base = normalized.rstrip("/")
        if not base:
            return ["**"]
        add(f"{base}/**")
        add(f"{base}/")
        if not base.startswith("**/"):
            add(f"**/{base}/**")
            add(f"**/{base}/")
        return patterns

    add(normalized)
    if not normalized.startswith("**/"):
        add(f"**/{normalized}")

    return patterns


def expand_patterns(patterns: Iterable[str]) -> List[str]:
    expanded: List[str] = []
    for pattern in patterns:
        expanded.extend(_normalize_pattern(pattern))
    return expanded


DEFAULT_IGNORE_PATTERNS = expand_patterns(DEFAULT_IGNORE_PATTERNS_RAW)


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


@dataclass
class RepoSnapshotChunk:
    index: int
    token_count: int
    file_count: int
    content: str


@dataclass
class RepoSnapshot:
    repo_map_text: str
    chunks: List[RepoSnapshotChunk]
    warnings: List[str] = field(default_factory=list)
    token_estimator: TokenEstimator = field(default_factory=lambda: TokenEstimator(False))


def matches_patterns(path: str, patterns: Iterable[str]) -> bool:
    if not patterns:
        return False
    posix_path = PurePosixPath(path)
    return any(posix_path.match(pattern) for pattern in patterns)


def matches_include(path: str, include_patterns: Iterable[str]) -> bool:
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
    if options.include_patterns and matches_include(posix, options.include_patterns):
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


def _generate_repomap_text(
    local_dir: str,
    options: ProcessingOptions,
    skip_relatives: Set[str],
    warnings: List[str],
) -> str:
    buffer = io.StringIO()
    repo_name = os.path.basename(os.path.abspath(local_dir))
    buffer.write(f"{repo_name}\n")

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
                buffer.write(f"{indent}{os.path.basename(root)}\n")

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

                buffer.write(f"{sub_indent}{file_name}\n")

                if is_code_file(file_name, options):
                    _write_file_structure_summary(
                        os.path.splitext(file_name)[1].lower(),
                        file_path,
                        buffer,
                        sub_indent + " " * 4,
                    )
        except UnicodeEncodeError:
            warnings.append(
                f"Warning: Skipping directory with unsupported characters: {root}"
            )
            continue

    return buffer.getvalue()


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


# Additional analyzers copied from CLI implementation

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


def _write_file_structure_summary(
    file_ext: str,
    file_path: str,
    handle: TextIO,
    indent: str,
) -> None:
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


def write_file_structure_summary(
    file_ext: str,
    file_path: str,
    handle: TextIO,
    indent: str,
) -> None:
    """Public wrapper for file structure summaries."""

    _write_file_structure_summary(file_ext, file_path, handle, indent)


def _generate_consolidated_chunks(
    local_dir: str,
    options: ProcessingOptions,
    skip_relatives: Set[str],
    token_estimator: TokenEstimator,
    chunk_token_limit: Optional[int],
) -> List[RepoSnapshotChunk]:
    chunk_limit = chunk_token_limit if chunk_token_limit and chunk_token_limit > 0 else None

    chunks: List[RepoSnapshotChunk] = []
    chunk_buffer = io.StringIO()
    chunk_tokens = 0
    chunk_file_count = 0

    def finalize_chunk() -> None:
        nonlocal chunk_buffer, chunk_tokens, chunk_file_count
        chunks.append(
            RepoSnapshotChunk(
                index=len(chunks) + 1,
                token_count=chunk_tokens,
                file_count=chunk_file_count,
                content=chunk_buffer.getvalue(),
            )
        )
        chunk_buffer = io.StringIO()
        chunk_tokens = 0
        chunk_file_count = 0

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
            block_tokens = token_estimator.count(file_block)

            if chunk_limit and chunk_tokens > 0 and chunk_tokens + block_tokens > chunk_limit:
                finalize_chunk()

            chunk_buffer.write(file_block)
            chunk_tokens += block_tokens
            chunk_file_count += 1

    if chunk_buffer.tell() or chunk_file_count or not chunks:
        chunks.append(
            RepoSnapshotChunk(
                index=len(chunks) + 1,
                token_count=chunk_tokens,
                file_count=chunk_file_count,
                content=chunk_buffer.getvalue(),
            )
        )

    return chunks


def collect_repo_snapshot(
    local_dir: str,
    options: ProcessingOptions,
    *,
    skip_relatives: Optional[Set[str]] = None,
    token_estimator: Optional[TokenEstimator] = None,
    chunk_token_limit: Optional[int] = None,
    repomap_writer: Optional[Callable[[str], None]] = None,
    chunk_writer: Optional[Callable[[RepoSnapshotChunk], None]] = None,
) -> RepoSnapshot:
    skip = set(skip_relatives or set())
    estimator = token_estimator or TokenEstimator(False)
    warnings: List[str] = []

    repo_map_text = _generate_repomap_text(local_dir, options, skip, warnings)
    if repomap_writer:
        repomap_writer(repo_map_text)

    chunks = _generate_consolidated_chunks(
        local_dir,
        options,
        skip,
        estimator,
        chunk_token_limit,
    )

    if chunk_writer:
        for chunk in chunks:
            chunk_writer(chunk)

    return RepoSnapshot(
        repo_map_text=repo_map_text,
        chunks=chunks,
        warnings=warnings,
        token_estimator=estimator,
    )
