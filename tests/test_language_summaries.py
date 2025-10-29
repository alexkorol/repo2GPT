import io
from pathlib import Path

import pytest

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from main import write_file_structure_summary  # noqa: E402


@pytest.mark.parametrize(
    "extension, content, expected_fragments",
    [
        (
            ".go",
            """package main\n\nfunc main() {}\nfunc (s *Server) Start() {}\ntype Server struct {}\n""",
            [
                "Classes:\n    Server (Line 5)",
                "Functions:\n    main (Line 3)",
                "Functions:\n    main (Line 3)\n    Start (Line 4)",
            ],
        ),
        (
            ".rs",
            """pub struct Config {}\nenum Mode { A, B }\n\npub fn compute() {}\nfn helper() {}\n""",
            [
                "Classes:\n    Config (Line 1)",
                "Classes:\n    Config (Line 1)\n    Mode (Line 2)",
                "Functions:\n    compute (Line 4)",
                "    helper (Line 5)",
            ],
        ),
        (
            ".rb",
            """class Greeter\n  def greet\n  end\nend\n\ndef top_level\nend\n""",
            [
                "Classes:\n    Greeter (Line 1)",
                "Functions:\n    greet (Line 2)",
                "    top_level (Line 6)",
            ],
        ),
        (
            ".php",
            """<?php\nclass Sample {\n    public function run() {}\n}\n\nfunction helper() {}\n""",
            [
                "Classes:\n    Sample (Line 2)",
                "Functions:\n    run (Line 3)",
                "    helper (Line 6)",
            ],
        ),
    ],
)
def test_language_specific_summaries(tmp_path, extension, content, expected_fragments):
    file_path = tmp_path / f"sample{extension}"
    file_path.write_text(content)

    buffer = io.StringIO()
    write_file_structure_summary(extension, str(file_path), buffer, "")

    summary = buffer.getvalue()
    for fragment in expected_fragments:
        assert fragment in summary
