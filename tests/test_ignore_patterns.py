from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from repo2gpt.service import expand_patterns, matches_patterns  # noqa: E402


def test_root_anchored_directory_patterns_match_repo_root():
    patterns = expand_patterns(["/build/"])

    assert matches_patterns("build", patterns)
    assert matches_patterns("build/output.txt", patterns)


def test_directory_patterns_match_nested_directories():
    patterns = expand_patterns(["build/"])

    assert matches_patterns("frontend/build", patterns)
    assert matches_patterns("frontend/build/output.txt", patterns)
