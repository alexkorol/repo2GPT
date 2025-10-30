"""Model Context Protocol server for repo2GPT tooling."""
from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import quote, urlparse, urlunparse

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from git import GitCommandError, Repo

from repo2gpt import (
    ALWAYS_INCLUDE_FILENAMES,
    DEFAULT_CODE_EXTENSIONS,
    DEFAULT_IGNORE_PATTERNS,
    ProcessingOptions,
    RepoSnapshot,
    TokenEstimator,
    collect_repo_snapshot,
    expand_patterns,
)

JSONRPC_VERSION = "2.0"
SERVER_NAME = "repo2gpt-mcp"
SERVER_VERSION = "0.1.0"


class MCPError(Exception):
    """Exception raised for MCP/JSON-RPC failures."""

    def __init__(self, code: int, message: str, *, data: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data or {}

    def to_json(self, request_id: Any) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "jsonrpc": JSONRPC_VERSION,
            "id": request_id,
            "error": {"code": self.code, "message": self.message},
        }
        if self.data:
            payload["error"]["data"] = self.data
        return payload


@dataclass
class ArtifactRecord:
    """Stored artifact that can be retrieved by MCP clients."""

    id: str
    job_id: str
    name: str
    mime_type: str
    content: str
    description: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_descriptor(self) -> Dict[str, Any]:
        descriptor: Dict[str, Any] = {
            "artifactId": self.id,
            "name": self.name,
            "mimeType": self.mime_type,
        }
        if self.description:
            descriptor["description"] = self.description
        if self.metadata:
            descriptor["metadata"] = self.metadata
        return descriptor

    def to_payload(self) -> Dict[str, Any]:
        payload = self.to_descriptor()
        payload["content"] = self.content
        return payload


@dataclass
class JobRecord:
    """Metadata describing an executed tool call."""

    id: str
    created_at: datetime
    status: str
    request: Dict[str, Any]
    warnings: List[str] = field(default_factory=list)
    artifact_ids: List[str] = field(default_factory=list)
    token_summary: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

    def to_descriptor(self, artifacts: Iterable[ArtifactRecord]) -> Dict[str, Any]:
        artifact_lookup = {artifact.id: artifact for artifact in artifacts}
        return {
            "jobId": self.id,
            "createdAt": self.created_at.isoformat(),
            "status": self.status,
            "warnings": list(self.warnings),
            "error": self.error,
            "tokenSummary": self.token_summary,
            "artifacts": [
                artifact_lookup[artifact_id].to_descriptor()
                for artifact_id in self.artifact_ids
                if artifact_id in artifact_lookup
            ],
        }


class JobStore:
    """In-memory storage for jobs and artifacts."""

    def __init__(self) -> None:
        self._jobs: Dict[str, JobRecord] = {}
        self._artifacts: Dict[str, ArtifactRecord] = {}

    def create_job(self, request: Dict[str, Any]) -> JobRecord:
        job_id = uuid.uuid4().hex
        record = JobRecord(id=job_id, created_at=datetime.now(timezone.utc), status="pending", request=request)
        self._jobs[job_id] = record
        return record

    def update_status(
        self,
        job_id: str,
        status: str,
        *,
        warnings: Optional[List[str]] = None,
        token_summary: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> JobRecord:
        record = self._require_job(job_id)
        record.status = status
        if warnings is not None:
            record.warnings = warnings
        if token_summary is not None:
            record.token_summary = token_summary
        if error is not None:
            record.error = error
        return record

    def register_artifact(
        self,
        job_id: str,
        name: str,
        mime_type: str,
        content: str,
        *,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ArtifactRecord:
        record = self._require_job(job_id)
        artifact_id = uuid.uuid4().hex
        artifact = ArtifactRecord(
            id=artifact_id,
            job_id=record.id,
            name=name,
            mime_type=mime_type,
            content=content,
            description=description,
            metadata=metadata or {},
        )
        self._artifacts[artifact_id] = artifact
        record.artifact_ids.append(artifact_id)
        return artifact

    def describe_job(self, job_id: str) -> Dict[str, Any]:
        record = self._require_job(job_id)
        artifacts = [self._artifacts[artifact_id] for artifact_id in record.artifact_ids if artifact_id in self._artifacts]
        return record.to_descriptor(artifacts)

    def get_artifact(self, artifact_id: str) -> ArtifactRecord:
        try:
            return self._artifacts[artifact_id]
        except KeyError as exc:  # pragma: no cover - defensive
            raise MCPError(-32001, f"Unknown artifact: {artifact_id}") from exc

    def list_jobs(self, limit: int = 10) -> List[Dict[str, Any]]:
        jobs = sorted(self._jobs.values(), key=lambda record: record.created_at, reverse=True)
        limited = jobs[: max(limit, 0)] if limit >= 0 else []
        return [self.describe_job(job.id) for job in limited]

    def _require_job(self, job_id: str) -> JobRecord:
        try:
            return self._jobs[job_id]
        except KeyError as exc:  # pragma: no cover - defensive
            raise MCPError(-32000, f"Unknown job: {job_id}") from exc


@dataclass
class MCPConfig:
    """Configuration resolved from environment variables."""

    github_pat: Optional[str] = None
    gemini_api_key: Optional[str] = None
    gemini_model: Optional[str] = None

    @classmethod
    def from_env(cls) -> "MCPConfig":
        return cls(
            github_pat=os.getenv("REPO2GPT_GITHUB_PAT") or os.getenv("GITHUB_TOKEN") or os.getenv("GITHUB_PAT"),
            gemini_api_key=os.getenv("REPO2GPT_GEMINI_API_KEY")
            or os.getenv("GEMINI_API_KEY")
            or os.getenv("GOOGLE_API_KEY"),
            gemini_model=os.getenv("REPO2GPT_GEMINI_MODEL") or os.getenv("GEMINI_MODEL"),
        )


class MCPServer:
    """Routes JSON-RPC requests for the repo2GPT MCP integration."""

    def __init__(self, config: Optional[MCPConfig] = None) -> None:
        self.config = config or MCPConfig.from_env()
        self.job_store = JobStore()

    async def handle(self, payload: Any) -> Any:
        if isinstance(payload, list):
            return [await self._handle_single(item) for item in payload]
        return await self._handle_single(payload)

    async def _handle_single(self, request: Dict[str, Any]) -> Dict[str, Any]:
        request_id = request.get("id")
        method = request.get("method")
        try:
            if request.get("jsonrpc") != JSONRPC_VERSION:
                raise MCPError(-32600, "Invalid JSON-RPC version", data={"expected": JSONRPC_VERSION})
            if method == "initialize":
                result = self._handle_initialize(request.get("params") or {})
            elif method == "listTools":
                result = self._handle_list_tools()
            elif method == "callTool":
                result = await self._handle_call_tool(request.get("params") or {})
            else:
                raise MCPError(-32601, f"Method not found: {method}")
            return {"jsonrpc": JSONRPC_VERSION, "id": request_id, "result": result}
        except MCPError as exc:
            return exc.to_json(request_id)

    def _handle_initialize(self, params: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "protocolVersion": JSONRPC_VERSION,
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            "capabilities": {
                "tools": {
                    "list": True,
                    "call": True,
                },
                "jobs": {"list": True},
                "artifacts": {"get": True},
            },
            "configuration": {
                "githubPATConfigured": bool(self.config.github_pat),
                "geminiConfigured": bool(self.config.gemini_api_key),
                "geminiModel": self.config.gemini_model,
            },
        }

    def _handle_list_tools(self) -> Dict[str, Any]:
        return {
            "tools": [
                {
                    "name": "processRepo",
                    "description": "Process a repository path or Git URL into repo2GPT artifacts.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "repository": {
                                "type": "string",
                                "description": "Filesystem path or Git URL to process.",
                            },
                            "ref": {
                                "type": ["string", "null"],
                                "description": "Optional Git ref (branch, tag, or commit).",
                            },
                            "chunkTokenLimit": {
                                "type": ["integer", "null"],
                                "description": "Optional maximum tokens per chunk.",
                            },
                            "ignorePatterns": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Additional glob patterns to ignore.",
                            },
                            "includePatterns": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Additional glob patterns to include.",
                            },
                            "allowedExtensions": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Extra file extensions to treat as code.",
                            },
                            "allowNonCode": {
                                "type": "boolean",
                                "description": "Include non-code files in the snapshot.",
                            },
                            "maxFileBytes": {
                                "type": ["integer", "null"],
                                "description": "Skip files larger than this size in bytes.",
                            },
                            "githubPAT": {
                                "type": ["string", "null"],
                                "description": "Personal access token for private GitHub repositories.",
                            },
                        },
                        "required": ["repository"],
                    },
                },
                {
                    "name": "listRecentJobs",
                    "description": "List recently completed MCP jobs and their artifacts.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "limit": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": 50,
                                "default": 10,
                            }
                        },
                    },
                },
                {
                    "name": "getArtifact",
                    "description": "Fetch the contents of a previously generated artifact.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "artifactId": {
                                "type": "string",
                                "description": "Identifier returned by processRepo.",
                            }
                        },
                        "required": ["artifactId"],
                    },
                },
            ]
        }

    async def _handle_call_tool(self, params: Dict[str, Any]) -> Dict[str, Any]:
        name = params.get("name")
        if not name:
            raise MCPError(-32602, "Tool name is required")
        arguments = params.get("arguments") or {}
        if name == "processRepo":
            result = await self._tool_process_repo(arguments)
        elif name == "listRecentJobs":
            result = self._tool_list_recent_jobs(arguments)
        elif name == "getArtifact":
            result = self._tool_get_artifact(arguments)
        else:
            raise MCPError(-32601, f"Unknown tool: {name}")
        return {"tool": name, "result": result}

    async def _tool_process_repo(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        repository = arguments.get("repository")
        if not repository:
            raise MCPError(-32602, "'repository' is required")
        ref = arguments.get("ref")
        chunk_limit_value = arguments.get("chunkTokenLimit")
        try:
            chunk_limit = int(chunk_limit_value) if chunk_limit_value is not None else None
        except (TypeError, ValueError) as exc:
            raise MCPError(-32602, "chunkTokenLimit must be an integer") from exc
        ignore_patterns = self._normalize_patterns(arguments.get("ignorePatterns") or [])
        include_patterns = self._normalize_patterns(arguments.get("includePatterns") or [])
        allowed_extensions = [ext.lower() for ext in arguments.get("allowedExtensions") or []]
        allow_non_code = bool(arguments.get("allowNonCode", False))
        max_file_bytes_value = arguments.get("maxFileBytes")
        try:
            max_file_bytes = (
                int(max_file_bytes_value) if max_file_bytes_value is not None else None
            )
        except (TypeError, ValueError) as exc:
            raise MCPError(-32602, "maxFileBytes must be an integer") from exc
        github_pat = arguments.get("githubPAT") or self.config.github_pat
        options = self._build_processing_options(
            ignore_patterns=ignore_patterns,
            include_patterns=include_patterns,
            allowed_extensions=allowed_extensions,
            allow_non_code=allow_non_code,
            max_file_bytes=max_file_bytes,
        )
        job = self.job_store.create_job({"repository": repository, "ref": ref})
        self.job_store.update_status(job.id, "running")
        cleanup_dir: Optional[str] = None
        local_path: Optional[str] = None
        try:
            local_path, cleanup_dir = self._prepare_repository(repository, ref, github_pat)
            snapshot = collect_repo_snapshot(
                local_path,
                options,
                chunk_token_limit=chunk_limit,
            )
            descriptors = self._store_snapshot_artifacts(job.id, snapshot)
            token_summary = self._build_token_summary(snapshot)
            self.job_store.update_status(
                job.id,
                "completed",
                warnings=snapshot.warnings,
                token_summary=token_summary,
            )
            payload = self.job_store.describe_job(job.id)
            payload["artifacts"] = descriptors
            return payload
        except MCPError as exc:
            self.job_store.update_status(job.id, "failed", error=exc.message)
            raise
        except GitCommandError as exc:
            self.job_store.update_status(job.id, "failed", error=str(exc))
            raise MCPError(-32010, f"Failed to prepare repository: {exc}") from exc
        except Exception as exc:
            self.job_store.update_status(job.id, "failed", error=str(exc))
            raise MCPError(-32603, "Failed to process repository", data={"details": str(exc)}) from exc
        finally:
            if cleanup_dir:
                shutil.rmtree(cleanup_dir, ignore_errors=True)

    def _tool_list_recent_jobs(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        limit_value = arguments.get("limit", 10)
        try:
            limit = int(limit_value)
        except (TypeError, ValueError) as exc:
            raise MCPError(-32602, "limit must be an integer") from exc
        limit = max(1, min(limit, 50))
        jobs = self.job_store.list_jobs(limit=limit)
        return {"jobs": jobs}

    def _tool_get_artifact(self, arguments: Dict[str, Any]) -> Dict[str, Any]:
        artifact_id = arguments.get("artifactId")
        if not artifact_id:
            raise MCPError(-32602, "'artifactId' is required")
        artifact = self.job_store.get_artifact(artifact_id)
        return {"artifact": artifact.to_payload()}

    def _store_snapshot_artifacts(self, job_id: str, snapshot: RepoSnapshot) -> List[Dict[str, Any]]:
        descriptors: List[Dict[str, Any]] = []
        repo_map = self.job_store.register_artifact(
            job_id,
            name="repo-map",
            mime_type="text/markdown",
            content=snapshot.repo_map_text,
            description="Consolidated repository structure",
        )
        descriptors.append(repo_map.to_descriptor())
        for chunk in snapshot.chunks:
            chunk_artifact = self.job_store.register_artifact(
                job_id,
                name=f"chunk-{chunk.index:04d}",
                mime_type="text/markdown",
                content=chunk.content,
                metadata={
                    "tokenCount": chunk.token_count,
                    "fileCount": chunk.file_count,
                },
            )
            descriptors.append(chunk_artifact.to_descriptor())
        return descriptors

    @staticmethod
    def _build_token_summary(snapshot: RepoSnapshot) -> Dict[str, Any]:
        estimator = snapshot.token_estimator or TokenEstimator(False)
        chunk_tokens = sum(chunk.token_count for chunk in snapshot.chunks)
        repo_map_tokens = estimator.count(snapshot.repo_map_text)
        return {
            "chunkTokens": chunk_tokens,
            "chunkCount": len(snapshot.chunks),
            "repoMapTokens": repo_map_tokens,
            "estimationStrategy": estimator.description,
        }

    @staticmethod
    def _normalize_patterns(patterns: Iterable[str]) -> List[str]:
        flattened = [pattern for pattern in patterns if pattern]
        if not flattened:
            return []
        return expand_patterns(flattened)

    def _build_processing_options(
        self,
        *,
        ignore_patterns: List[str],
        include_patterns: List[str],
        allowed_extensions: List[str],
        allow_non_code: bool,
        max_file_bytes: Optional[int],
    ) -> ProcessingOptions:
        ignore = list(DEFAULT_IGNORE_PATTERNS)
        include: List[str] = []
        ignore.extend(ignore_patterns)
        include.extend(include_patterns)
        extensions = {ext.lower() for ext in DEFAULT_CODE_EXTENSIONS}
        for extension in allowed_extensions:
            normalized = extension if extension.startswith(".") else f".{extension}"
            extensions.add(normalized.lower())
        return ProcessingOptions(
            ignore_patterns=ignore,
            include_patterns=include,
            allowed_extensions=extensions,
            special_filenames=set(ALWAYS_INCLUDE_FILENAMES),
            max_file_bytes=max_file_bytes,
            allow_non_code=allow_non_code,
        )

    def _prepare_repository(
        self, repository: str, ref: Optional[str], github_pat: Optional[str]
    ) -> tuple[str, Optional[str]]:
        local_path = Path(repository)
        if local_path.exists():
            return str(local_path.resolve()), None
        temp_dir = tempfile.mkdtemp(prefix="repo2gpt-mcp-")
        target_dir = Path(temp_dir) / "repository"
        git_url = self._apply_github_pat(repository, github_pat)
        repo = Repo.clone_from(git_url, target_dir)
        if ref:
            repo.git.checkout(ref)
        return str(target_dir), temp_dir

    @staticmethod
    def _apply_github_pat(url: str, pat: Optional[str]) -> str:
        if not pat:
            return url
        parsed = urlparse(url)
        if parsed.scheme not in {"https", "http"}:
            return url
        if "github.com" not in parsed.netloc.lower():
            return url
        encoded = quote(pat, safe="")
        netloc = f"{encoded}@{parsed.netloc}"
        return urlunparse((parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))


def create_app(config: Optional[MCPConfig] = None) -> FastAPI:
    server = MCPServer(config=config)
    app = FastAPI(title="repo2GPT MCP Server")

    @app.post("/")
    async def handle(request: Request) -> JSONResponse:  # type: ignore[override]
        payload = await request.json()
        response = await server.handle(payload)
        return JSONResponse(response)

    @app.get("/healthz")
    async def healthcheck() -> Dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
