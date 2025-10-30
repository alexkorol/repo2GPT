from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from repo2gpt.service import (
    ALWAYS_INCLUDE_FILENAMES,
    DEFAULT_CODE_EXTENSIONS,
    ProcessingOptions,
    matches_include,
    should_include_file,
)


@pytest.fixture
def base_options():
    return ProcessingOptions(
        ignore_patterns=[],
        include_patterns=["docs/**"],
        allowed_extensions={ext.lower() for ext in DEFAULT_CODE_EXTENSIONS},
        special_filenames=ALWAYS_INCLUDE_FILENAMES,
        max_file_bytes=None,
        allow_non_code=False,
    )


def test_code_files_still_included_with_include_patterns(base_options):
    assert should_include_file("src/app.py", "app.py", base_options)


def test_non_code_files_require_include_match(base_options):
    assert not should_include_file("notes.txt", "notes.txt", base_options)
    assert should_include_file("docs/notes.txt", "notes.txt", base_options)


def test_matches_include_helper_respects_patterns(base_options):
    assert matches_include("docs/diagram.png", base_options.include_patterns)
    assert not matches_include("images/diagram.png", base_options.include_patterns)
