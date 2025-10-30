"""Tests for the repo2GPT MCP server."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from integrations.mcp.server import MCPConfig, MCPServer
from repo2gpt import RepoSnapshot, RepoSnapshotChunk, TokenEstimator


def test_initialize_reports_capabilities() -> None:
    server = MCPServer(
        MCPConfig(
            github_pat="token-123",
            gemini_api_key="gem-key",
            gemini_model="models/gemini-test",
        )
    )

    response = asyncio.run(
        server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    )
    assert response["result"]["serverInfo"]["name"] == "repo2gpt-mcp"
    assert response["result"]["configuration"]["githubPATConfigured"] is True
    assert response["result"]["configuration"]["geminiConfigured"] is True
    assert response["result"]["configuration"]["geminiModel"] == "models/gemini-test"


def test_process_repo_workflow(monkeypatch, tmp_path) -> None:
    snapshot = RepoSnapshot(
        repo_map_text="repo-map",
        chunks=[
            RepoSnapshotChunk(index=0, token_count=10, file_count=2, content="chunk-0"),
            RepoSnapshotChunk(index=1, token_count=20, file_count=3, content="chunk-1"),
        ],
        warnings=["watch out"],
        token_estimator=TokenEstimator(False),
    )

    def fake_collect(path, options, chunk_token_limit=None):  # type: ignore[override]
        return snapshot

    monkeypatch.setattr("integrations.mcp.server.collect_repo_snapshot", fake_collect)

    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()

    server = MCPServer(MCPConfig())

    response = asyncio.run(
        server.handle(
            {
                "jsonrpc": "2.0",
                "id": "process-1",
                "method": "callTool",
                "params": {"name": "processRepo", "arguments": {"repository": str(repo_dir)}},
            }
        )
    )
    result = response["result"]["result"]
    assert result["status"] == "completed"
    assert result["warnings"] == ["watch out"]
    assert result["tokenSummary"]["chunkTokens"] == 30
    assert len(result["artifacts"]) == 3  # repo map + two chunks

    artifact_id = next(
        descriptor["artifactId"]
        for descriptor in result["artifacts"]
        if descriptor["name"].startswith("chunk-0000")
    )

    list_jobs = asyncio.run(
        server.handle(
            {
                "jsonrpc": "2.0",
                "id": "jobs-1",
                "method": "callTool",
                "params": {"name": "listRecentJobs", "arguments": {"limit": 5}},
            }
        )
    )
    jobs_payload = list_jobs["result"]["result"]
    assert jobs_payload["jobs"]
    assert result["jobId"] in {job["jobId"] for job in jobs_payload["jobs"]}

    artifact_response = asyncio.run(
        server.handle(
            {
                "jsonrpc": "2.0",
                "id": "artifact-1",
                "method": "callTool",
                "params": {
                    "name": "getArtifact",
                    "arguments": {"artifactId": artifact_id},
                },
            }
        )
    )
    artifact = artifact_response["result"]["result"]["artifact"]
    assert artifact["content"] == "chunk-0"
    assert artifact["metadata"]["tokenCount"] == 10
