from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from repo2gpt.service import (
    ALWAYS_INCLUDE_FILENAMES,
    ProcessingOptions,
    TokenEstimator,
    collect_repo_snapshot,
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


def test_collect_repo_snapshot_without_chunking(tmp_path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    (repo_dir / "example.py").write_text("print('hello world')\n", encoding="utf-8")

    snapshot = collect_repo_snapshot(
        str(repo_dir),
        _make_options(),
        token_estimator=TokenEstimator(enabled=False),
    )

    assert len(snapshot.chunks) == 1
    assert "hello world" in snapshot.chunks[0].content
    assert snapshot.chunks[0].token_count == 0
    assert snapshot.chunks[0].file_count == 1


def test_collect_repo_snapshot_with_chunking(tmp_path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    for index in range(3):
        (repo_dir / f"file_{index}.py").write_text(
            "\n".join([f"print('line {index}-{i}')" for i in range(20)]),
            encoding="utf-8",
        )

    estimator = TokenEstimator(enabled=True)
    snapshot = collect_repo_snapshot(
        str(repo_dir),
        _make_options(),
        token_estimator=estimator,
        chunk_token_limit=10,
    )

    assert snapshot.token_estimator is estimator
    assert len(snapshot.chunks) > 1
    assert sum(chunk.file_count for chunk in snapshot.chunks) == 3
    assert any(chunk.token_count > 0 for chunk in snapshot.chunks)
