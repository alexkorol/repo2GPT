from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from main import (
    ALWAYS_INCLUDE_FILENAMES,
    ProcessingOptions,
    TokenEstimator,
    generate_consolidated_file,
)


def _make_options() -> ProcessingOptions:
    return ProcessingOptions(
        ignore_patterns=[],
        include_patterns=[],
        allowed_extensions={".py"},
        special_filenames=ALWAYS_INCLUDE_FILENAMES,
        max_file_bytes=None,
        allow_non_code=False,
    )


def test_generate_consolidated_file_without_chunking(tmp_path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "example.py").write_text("print('hello world')\n", encoding="utf-8")

    output_path = tmp_path / "consolidated.txt"
    results = generate_consolidated_file(
        str(repo_dir),
        str(output_path),
        _make_options(),
        set(),
        token_estimator=TokenEstimator(enabled=False),
    )

    assert len(results) == 1
    assert Path(results[0].path).exists()
    assert results[0].token_count == 0
    assert results[0].file_count == 1


def test_generate_consolidated_file_with_chunking(tmp_path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    for index in range(3):
        (repo_dir / f"file_{index}.py").write_text(
            "\n".join([f"print('line {index}-{i}')" for i in range(20)]),
            encoding="utf-8",
        )

    output_path = tmp_path / "consolidated.txt"
    estimator = TokenEstimator(enabled=True)
    results = generate_consolidated_file(
        str(repo_dir),
        str(output_path),
        _make_options(),
        set(),
        token_estimator=estimator,
        chunk_token_limit=10,
    )

    assert len(results) > 1
    assert results[0].path == str(output_path)
    assert Path(results[0].path).exists()
    assert Path(results[1].path).name.startswith(f"{output_path.stem}_part")
    assert sum(chunk.file_count for chunk in results) == 3
    assert all(Path(chunk.path).exists() for chunk in results)
