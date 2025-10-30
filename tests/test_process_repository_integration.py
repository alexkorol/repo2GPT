import argparse
from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from main import (  # noqa: E402
    DEFAULT_MAX_FILE_BYTES,
    build_processing_options,
    process_repository,
)
from repo2gpt.service import (  # noqa: E402
    collect_repo_snapshot,
    resolve_skip_paths,
    TokenEstimator,
)


def _build_args(repomap_path: Path, consolidated_path: Path) -> argparse.Namespace:
    return argparse.Namespace(
        repomap=str(repomap_path),
        consolidated=str(consolidated_path),
        gptignore=None,
        gptinclude=None,
        extra_ignore=None,
        extra_include=None,
        extra_extensions=None,
        max_file_bytes=DEFAULT_MAX_FILE_BYTES,
        include_all=False,
        enable_token_counts=False,
        chunk_size=0,
        copy=None,
    )


def test_process_repository_generates_expected_outputs(tmp_path: Path):
    repo_dir = tmp_path / "sample_repo"
    src_dir = repo_dir / "src"
    src_dir.mkdir(parents=True)

    (src_dir / "module.py").write_text(
        "def greet():\n    return 'hi'\n",
        encoding="utf-8",
    )
    (repo_dir / "README.md").write_text("# Sample Repo\n", encoding="utf-8")
    (repo_dir / "binary.dat").write_bytes(b"\x00\x01\x02")

    repomap_path = repo_dir / "repomap.txt"
    consolidated_path = repo_dir / "consolidated_code.txt"

    args = _build_args(repomap_path, consolidated_path)
    result = process_repository(str(repo_dir), args)

    repomap_content = Path(result.repomap_path).read_text(encoding="utf-8")
    consolidated_content = Path(result.consolidated_chunks[0].path).read_text(
        encoding="utf-8"
    )

    assert repomap_content.splitlines()[0] == repo_dir.name
    assert "module.py" in repomap_content
    assert "README.md" not in repomap_content
    assert "binary.dat" not in repomap_content
    assert Path(result.repomap_path).parent == repo_dir

    assert "def greet" in consolidated_content
    assert "Sample Repo" not in consolidated_content
    assert len(result.consolidated_chunks) == 1
    assert Path(result.consolidated_chunks[0].path) == consolidated_path
    assert result.consolidated_chunks[0].file_count == 1
    assert not result.token_estimator.enabled

    options = build_processing_options(str(repo_dir), args)
    skip_relatives = resolve_skip_paths(
        str(repo_dir), (str(repomap_path), str(consolidated_path))
    )
    snapshot = collect_repo_snapshot(
        str(repo_dir),
        options,
        skip_relatives=skip_relatives,
        token_estimator=TokenEstimator(enabled=False),
    )

    assert snapshot.repo_map_text.splitlines()[0] == repo_dir.name
    assert snapshot.repo_map_text == repomap_content
    assert snapshot.chunks[0].content == consolidated_content
    assert snapshot.chunks[0].file_count == 1
