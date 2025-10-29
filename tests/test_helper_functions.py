from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from main import (  # noqa: E402
    ALWAYS_INCLUDE_FILENAMES,
    ProcessingOptions,
    is_binary_file,
    resolve_skip_paths,
    should_include_file,
)


def _make_options(**overrides) -> ProcessingOptions:
    options = ProcessingOptions(
        ignore_patterns=["ignored/**"],
        include_patterns=["docs/**"],
        allowed_extensions={".py", ".txt"},
        special_filenames=ALWAYS_INCLUDE_FILENAMES,
        max_file_bytes=None,
        allow_non_code=False,
    )
    for key, value in overrides.items():
        setattr(options, key, value)
    return options


def test_should_include_respects_ignore_and_extensions():
    options = _make_options()

    assert should_include_file("src/app.py", "app.py", options)
    assert not should_include_file("ignored/app.py", "app.py", options)
    assert should_include_file("docs/readme.md", "readme.md", options)
    assert not should_include_file("notes/data.bin", "data.bin", options)


def test_should_include_allows_non_code_when_requested():
    options = _make_options(allow_non_code=True)

    assert should_include_file("notes/todo.md", "todo.md", options)
    assert not should_include_file("ignored/todo.md", "todo.md", options)


def test_resolve_skip_paths_filters_outside_targets(tmp_path: Path):
    local_dir = tmp_path / "repo"
    local_dir.mkdir()

    inside = local_dir / "repomap.txt"
    inside.write_text("", encoding="utf-8")
    nested = local_dir / "outputs" / "consolidated.txt"
    nested.parent.mkdir()
    nested.write_text("", encoding="utf-8")

    outside = tmp_path / "external.txt"
    outside.write_text("", encoding="utf-8")

    skip = resolve_skip_paths(str(local_dir), [str(inside), str(nested), str(outside)])

    assert skip == {"repomap.txt", "outputs/consolidated.txt"}


def test_is_binary_file_detects_binary_and_missing(tmp_path: Path):
    text_file = tmp_path / "plain.txt"
    text_file.write_text("hello", encoding="utf-8")

    binary_file = tmp_path / "data.bin"
    binary_file.write_bytes(b"\x00\x01\x02")

    missing_file = tmp_path / "missing.bin"

    assert not is_binary_file(str(text_file))
    assert is_binary_file(str(binary_file))
    assert is_binary_file(str(missing_file))

