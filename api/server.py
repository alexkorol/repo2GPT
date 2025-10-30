"""FastAPI server for repo2GPT snapshot processing."""
from __future__ import annotations

import asyncio
import base64
import binascii
import json
import os
import shutil
import tarfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional, Union
from urllib.parse import urlparse
from urllib.request import urlopen

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, HttpUrl, ValidationError

from git import GitCommandError, Repo

from repo2gpt.service import (
    ALWAYS_INCLUDE_FILENAMES,
    DEFAULT_CODE_EXTENSIONS,
    DEFAULT_IGNORE_PATTERNS,
    ProcessingOptions,
    RepoSnapshot,
    RepoSnapshotChunk,
    TokenEstimator,
    collect_repo_snapshot,
    expand_patterns,
    resolve_skip_paths,
)


class JobStatus(str, Enum):
    """Possible states for a processing job."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class JobEvent:
    """Structured event used for progress streaming."""

    id: int
    timestamp: datetime
    event: str
    message: Optional[str] = None
    data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat(),
            "event": self.event,
            "message": self.message,
            "data": self.data,
        }


@dataclass
class JobRecord:
    """Represents persisted job metadata."""

    id: str
    status: JobStatus
    created_at: datetime
    updated_at: datetime
    request: Dict[str, Any]
    events: List[JobEvent] = field(default_factory=list)
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "request": self.request,
            "events": [event.to_dict() for event in self.events],
            "result": self.result,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "JobRecord":
        def _parse_dt(value: str) -> datetime:
            return datetime.fromisoformat(value)

        events = [
            JobEvent(
                id=event["id"],
                timestamp=_parse_dt(event["timestamp"]),
                event=event["event"],
                message=event.get("message"),
                data=event.get("data", {}),
            )
            for event in data.get("events", [])
        ]
        return cls(
            id=data["id"],
            status=JobStatus(data["status"]),
            created_at=_parse_dt(data["created_at"]),
            updated_at=_parse_dt(data["updated_at"]),
            request=data.get("request", {}),
            events=events,
            result=data.get("result"),
            error=data.get("error"),
        )


class JobStore:
    """In-memory and on-disk persistence for job metadata."""

    def __init__(self, storage_root: Path) -> None:
        self._storage_root = storage_root
        self._storage_root.mkdir(parents=True, exist_ok=True)
        self._jobs: Dict[str, JobRecord] = {}
        self._lock = asyncio.Lock()
        self._load_existing_jobs()

    def _load_existing_jobs(self) -> None:
        for child in self._storage_root.iterdir():
            if not child.is_dir():
                continue
            status_file = child / "status.json"
            if not status_file.exists():
                continue
            try:
                data = json.loads(status_file.read_text(encoding="utf-8"))
                record = JobRecord.from_dict(data)
            except Exception:
                continue
            self._jobs[record.id] = record

    def job_path(self, job_id: str) -> Path:
        return self._storage_root / job_id

    async def create_job(self, request_data: Dict[str, Any]) -> JobRecord:
        async with self._lock:
            job_id = os.urandom(12).hex()
            now = datetime.now(timezone.utc)
            record = JobRecord(
                id=job_id,
                status=JobStatus.PENDING,
                created_at=now,
                updated_at=now,
                request=request_data,
            )
            self._jobs[job_id] = record
            job_dir = self.job_path(job_id)
            job_dir.mkdir(parents=True, exist_ok=True)
            (job_dir / "request.json").write_text(
                json.dumps(request_data, indent=2), encoding="utf-8"
            )
            self._write_status(record)
            return record

    async def get_job(self, job_id: str) -> Optional[JobRecord]:
        async with self._lock:
            return self._jobs.get(job_id)

    async def update_status(
        self,
        job_id: str,
        status: JobStatus,
        *,
        error: Optional[str] = None,
        result: Optional[Dict[str, Any]] = None,
    ) -> JobRecord:
        async with self._lock:
            record = self._require(job_id)
            record.status = status
            record.updated_at = datetime.now(timezone.utc)
            record.error = error
            record.result = result
            self._write_status(record)
            return record

    async def append_event(
        self,
        job_id: str,
        event: str,
        message: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> JobEvent:
        async with self._lock:
            record = self._require(job_id)
            next_id = len(record.events) + 1
            job_event = JobEvent(
                id=next_id,
                timestamp=datetime.now(timezone.utc),
                event=event,
                message=message,
                data=data or {},
            )
            record.events.append(job_event)
            record.updated_at = job_event.timestamp
            self._write_status(record)
            return job_event

    def _write_status(self, record: JobRecord) -> None:
        status_file = self.job_path(record.id) / "status.json"
        status_file.write_text(json.dumps(record.to_dict(), indent=2), encoding="utf-8")

    def _require(self, job_id: str) -> JobRecord:
        if job_id not in self._jobs:
            raise KeyError(job_id)
        return self._jobs[job_id]


class EventBroker:
    """Publisher/subscriber broker used to stream job progress."""

    def __init__(self) -> None:
        self._subscribers: Dict[str, List[asyncio.Queue[Dict[str, Any]]]] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self, job_id: str) -> asyncio.Queue[Dict[str, Any]]:
        queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
        async with self._lock:
            self._subscribers.setdefault(job_id, []).append(queue)
        return queue

    async def unsubscribe(self, job_id: str, queue: asyncio.Queue[Dict[str, Any]]) -> None:
        async with self._lock:
            queues = self._subscribers.get(job_id)
            if not queues:
                return
            if queue in queues:
                queues.remove(queue)
            if not queues:
                self._subscribers.pop(job_id, None)

    async def publish(self, job_id: str, event: Dict[str, Any]) -> None:
        async with self._lock:
            queues = list(self._subscribers.get(job_id, []))
        for queue in queues:
            await queue.put(event)

class GitSource(BaseModel):
    type: str = Field("git", const=True)
    url: HttpUrl
    ref: Optional[str] = None

    class Config:
        extra = "forbid"


class ArchiveUrlSource(BaseModel):
    type: str = Field("archive_url", const=True)
    url: HttpUrl
    filename: Optional[str] = None

    class Config:
        extra = "forbid"


class ArchiveUploadSource(BaseModel):
    type: str = Field("archive_upload", const=True)
    filename: str
    content_base64: str

    class Config:
        extra = "forbid"


JobSource = Union[GitSource, ArchiveUrlSource, ArchiveUploadSource]


class ProcessingOptionsPayload(BaseModel):
    ignore_patterns: Optional[List[str]] = None
    include_patterns: Optional[List[str]] = None
    allowed_extensions: Optional[List[str]] = None
    special_filenames: Optional[List[str]] = None
    max_file_bytes: Optional[int] = Field(default=None, ge=1)
    allow_non_code: Optional[bool] = None

    class Config:
        extra = "forbid"


class JobCreateRequest(BaseModel):
    source: JobSource
    options: Optional[ProcessingOptionsPayload] = None
    chunk_token_limit: Optional[int] = Field(default=None, ge=1)
    enable_token_counts: bool = True

    class Config:
        extra = "forbid"


class JobResponse(BaseModel):
    id: str
    status: JobStatus
    created_at: datetime
    updated_at: datetime


def _get_storage_root() -> Path:
    configured = os.getenv("REPO2GPT_STORAGE_ROOT")
    if configured:
        root = Path(configured)
    else:
        root = Path.home() / ".repo2gpt" / "jobs"
    root.mkdir(parents=True, exist_ok=True)
    return root


job_store = JobStore(_get_storage_root())
event_broker = EventBroker()
app = FastAPI(title="repo2GPT API", version="1.0.0")


def _format_sse(event: Dict[str, Any]) -> str:
    payload = json.dumps(event)
    event_name = event.get("event", "message")
    lines = [f"event: {event_name}", f"data: {payload}"]
    if "id" in event:
        lines.insert(0, f"id: {event['id']}")
    return "\n".join(lines) + "\n\n"


def _verify_api_key(api_key: Optional[str]) -> None:
    expected = os.getenv("REPO2GPT_API_KEY")
    if expected and api_key != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")


async def require_api_key(request: Request) -> None:
    api_key = request.headers.get("X-API-Key")
    _verify_api_key(api_key)


async def emit_event(job_id: str, event: str, message: Optional[str] = None, **data: Any) -> Dict[str, Any]:
    job_event = await job_store.append_event(job_id, event, message=message, data=data)
    payload = job_event.to_dict()
    await event_broker.publish(job_id, payload)
    return payload


def _threadsafe_emitter(loop: asyncio.AbstractEventLoop, job_id: str):
    def emit(event: str, message: Optional[str] = None, **data: Any) -> None:
        asyncio.run_coroutine_threadsafe(
            emit_event(job_id, event, message=message, **data), loop
        )

    return emit


def _schedule_job(job_id: str) -> None:
    asyncio.create_task(_run_job(job_id))


def _clean_workspace(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)


def _safe_extract_tar(tar: tarfile.TarFile, destination: Path) -> None:
    destination = destination.resolve()
    for member in tar.getmembers():
        member_path = (destination / member.name).resolve()
        if not str(member_path).startswith(str(destination)):
            raise ValueError("Archive contains invalid paths")
    tar.extractall(destination)


def _safe_extract_zip(zip_file: zipfile.ZipFile, destination: Path) -> None:
    destination = destination.resolve()
    for info in zip_file.infolist():
        member_path = (destination / info.filename).resolve()
        if not str(member_path).startswith(str(destination)):
            raise ValueError("Archive contains invalid paths")
    zip_file.extractall(destination)


def _extract_archive(archive_path: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    suffixes = archive_path.suffixes
    suffix = "".join(suffixes[-2:]) if len(suffixes) >= 2 else archive_path.suffix
    if archive_path.suffix == ".zip":
        with zipfile.ZipFile(archive_path) as zip_file:
            _safe_extract_zip(zip_file, destination)
        return
    tar_modes = {
        ".tar": "r:",
        ".tar.gz": "r:gz",
        ".tgz": "r:gz",
        ".tar.bz2": "r:bz2",
        ".tbz": "r:bz2",
        ".tbz2": "r:bz2",
        ".tar.xz": "r:xz",
        ".txz": "r:xz",
    }
    mode = tar_modes.get(suffix)
    if mode is None and archive_path.suffix in tar_modes:
        mode = tar_modes[archive_path.suffix]
    if mode is None:
        raise ValueError(f"Unsupported archive format: {archive_path.suffix}")
    with tarfile.open(archive_path, mode) as tar:
        _safe_extract_tar(tar, destination)


def _select_repo_root(extracted: Path) -> Path:
    candidates = [child for child in extracted.iterdir() if child.is_dir()]
    if len(candidates) == 1:
        return candidates[0]
    return extracted


def _download_archive(url: str, target: Path) -> Path:
    parsed = urlparse(url)
    filename = Path(parsed.path).name or "archive"
    target_path = target / filename
    try:
        with urlopen(url) as response, open(target_path, "wb") as sink:
            shutil.copyfileobj(response, sink)
    except Exception as exc:
        raise ValueError(f"Failed to download archive: {exc}") from exc
    return target_path


def _decode_archive(filename: str, content_base64: str, target: Path) -> Path:
    target_path = target / filename
    try:
        data = base64.b64decode(content_base64, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("Invalid base64-encoded archive content") from exc
    target_path.write_bytes(data)
    return target_path


def _build_processing_options(payload: Optional[ProcessingOptionsPayload]) -> ProcessingOptions:
    ignore_patterns = list(DEFAULT_IGNORE_PATTERNS)
    include_patterns: List[str] = []
    allowed_extensions = {ext.lower() for ext in DEFAULT_CODE_EXTENSIONS}
    special_filenames = set(ALWAYS_INCLUDE_FILENAMES)
    max_file_bytes: Optional[int] = None
    allow_non_code = False
    if payload:
        if payload.ignore_patterns:
            ignore_patterns.extend(expand_patterns(payload.ignore_patterns))
        if payload.include_patterns:
            include_patterns.extend(expand_patterns(payload.include_patterns))
        if payload.allowed_extensions:
            for ext in payload.allowed_extensions:
                normalized = ext.lower()
                if not normalized.startswith("."):
                    normalized = f".{normalized}"
                allowed_extensions.add(normalized)
        if payload.special_filenames:
            special_filenames.update(payload.special_filenames)
        if payload.max_file_bytes:
            max_file_bytes = payload.max_file_bytes
        if payload.allow_non_code is not None:
            allow_non_code = payload.allow_non_code
    return ProcessingOptions(
        ignore_patterns=ignore_patterns,
        include_patterns=include_patterns,
        allowed_extensions=allowed_extensions,
        special_filenames=special_filenames,
        max_file_bytes=max_file_bytes,
        allow_non_code=allow_non_code,
    )


def _prepare_repository(source: JobSource, job_dir: Path, emitter) -> Path:
    workspace = job_dir / "workspace"
    _clean_workspace(workspace)
    workspace.mkdir(parents=True, exist_ok=True)
    emitter("progress", message="Preparing workspace")
    repo_path = workspace / "repository"
    if isinstance(source, GitSource):
        emitter("progress", message="Cloning repository", url=str(source.url))
        try:
            repo = Repo.clone_from(str(source.url), str(repo_path))
        except GitCommandError as exc:
            raise ValueError(f"Failed to clone repository: {exc}") from exc
        if source.ref:
            try:
                repo.git.checkout(source.ref)
            except GitCommandError as exc:
                raise ValueError(f"Unable to checkout ref '{source.ref}': {exc}") from exc
        return repo_path
    archive_dir = workspace / "archives"
    archive_dir.mkdir(parents=True, exist_ok=True)
    if isinstance(source, ArchiveUrlSource):
        emitter("progress", message="Downloading archive", url=str(source.url))
        archive_path = _download_archive(str(source.url), archive_dir)
        if source.filename:
            target_path = archive_dir / source.filename
            if target_path.exists():
                target_path.unlink()
            archive_path.rename(target_path)
            archive_path = target_path
    elif isinstance(source, ArchiveUploadSource):
        emitter("progress", message="Decoding uploaded archive", filename=source.filename)
        archive_path = _decode_archive(source.filename, source.content_base64, archive_dir)
    else:
        raise ValueError("Unsupported source type")
    extracted_dir = workspace / "extracted"
    emitter("progress", message="Extracting archive", filename=archive_path.name)
    _extract_archive(archive_path, extracted_dir)
    repo_root = _select_repo_root(extracted_dir)
    return repo_root


def _snapshot_repository(
    local_dir: Path,
    options: ProcessingOptions,
    job_dir: Path,
    chunk_limit: Optional[int],
    enable_tokens: bool,
    emitter,
) -> Dict[str, Any]:
    artifacts_dir = job_dir / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    repomap_path = artifacts_dir / "repomap.txt"
    chunks_dir = artifacts_dir / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)
    chunk_metadata: List[Dict[str, Any]] = []
    estimator = TokenEstimator(enable_tokens)
    skip_relatives = resolve_skip_paths(str(local_dir), [str(repomap_path), str(chunks_dir)])
    emitter("progress", message="Generating repository snapshot")

    def repomap_writer(text: str) -> None:
        repomap_path.write_text(text, encoding="utf-8")
        emitter("repomap", message="Repo map generated", path=str(repomap_path))

    def chunk_writer(chunk: RepoSnapshotChunk) -> None:
        chunk_file = chunks_dir / f"chunk_{chunk.index:04d}.md"
        chunk_file.write_text(chunk.content, encoding="utf-8")
        metadata = {
            "index": chunk.index,
            "token_count": chunk.token_count,
            "file_count": chunk.file_count,
            "path": str(chunk_file.relative_to(job_dir)),
        }
        chunk_metadata.append(metadata)
        emitter(
            "chunk",
            message="Chunk generated",
            chunk_index=chunk.index,
            token_count=chunk.token_count,
            file_count=chunk.file_count,
            path=str(chunk_file),
        )

    snapshot: RepoSnapshot = collect_repo_snapshot(
        str(local_dir),
        options,
        skip_relatives=set(skip_relatives),
        token_estimator=estimator,
        chunk_token_limit=chunk_limit,
        repomap_writer=repomap_writer,
        chunk_writer=chunk_writer,
    )
    total_tokens = sum(metadata["token_count"] for metadata in chunk_metadata)
    repo_map_tokens = snapshot.token_estimator.count(snapshot.repo_map_text)
    emitter(
        "tokens",
        message="Token statistics updated",
        chunk_count=len(chunk_metadata),
        total_tokens=total_tokens,
        repo_map_tokens=repo_map_tokens,
        estimation_strategy=snapshot.token_estimator.description,
    )
    return {
        "repomap_path": str(repomap_path.relative_to(job_dir)),
        "chunks": chunk_metadata,
        "warnings": snapshot.warnings,
        "token_estimator": {
            "enabled": snapshot.token_estimator.enabled,
            "strategy": snapshot.token_estimator.description,
        },
        "token_totals": {
            "chunk_tokens": total_tokens,
            "repo_map_tokens": repo_map_tokens,
            "chunk_count": len(chunk_metadata),
        },
    }


def _process_job_sync(
    job_id: str, request_data: Dict[str, Any], loop: asyncio.AbstractEventLoop
) -> Dict[str, Any]:
    source_data = request_data.get("source")
    if source_data is None:
        raise ValueError("Job request is missing the source definition")
    try:
        source: JobSource = _parse_source(source_data)
    except ValidationError as exc:
        raise ValueError(f"Invalid source configuration: {exc}") from exc
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    options_payload_data = request_data.get("options")
    options_payload: Optional[ProcessingOptionsPayload] = None
    if options_payload_data:
        try:
            options_payload = ProcessingOptionsPayload(**options_payload_data)
        except ValidationError as exc:
            raise ValueError(f"Invalid processing options: {exc}") from exc
    options = _build_processing_options(options_payload)
    chunk_limit = request_data.get("chunk_token_limit")
    enable_tokens = bool(request_data.get("enable_token_counts", True))
    job_dir = job_store.job_path(job_id)
    emitter = _threadsafe_emitter(loop, job_id)
    emitter("progress", message="Starting job")
    workspace = job_dir / "workspace"
    try:
        repo_root = _prepare_repository(source, job_dir, emitter)
        result = _snapshot_repository(
            Path(repo_root), options, job_dir, chunk_limit, enable_tokens, emitter
        )
        emitter("progress", message="Snapshot generation complete")
        return result
    finally:
        _clean_workspace(workspace)


def _parse_source(data: Dict[str, Any]) -> JobSource:
    source_type = data.get("type")
    if source_type == "git":
        return GitSource(**data)
    if source_type == "archive_url":
        return ArchiveUrlSource(**data)
    if source_type == "archive_upload":
        return ArchiveUploadSource(**data)
    raise ValueError(f"Unsupported source type: {source_type}")


async def _run_job(job_id: str) -> None:
    loop = asyncio.get_running_loop()
    record = await job_store.get_job(job_id)
    if record is None:
        return
    await job_store.update_status(job_id, JobStatus.RUNNING)
    await emit_event(job_id, "status", message="Job started", status=JobStatus.RUNNING.value)
    try:
        result = await asyncio.to_thread(_process_job_sync, job_id, record.request, loop)
    except Exception as exc:
        error_text = f"{exc.__class__.__name__}: {exc}"
        await job_store.update_status(job_id, JobStatus.FAILED, error=error_text)
        await emit_event(
            job_id,
            "status",
            message="Job failed",
            status=JobStatus.FAILED.value,
            error=error_text,
        )
        return
    await job_store.update_status(job_id, JobStatus.COMPLETED, result=result)
    await emit_event(
        job_id,
        "status",
        message="Job completed",
        status=JobStatus.COMPLETED.value,
        result_summary=result,
    )


@app.post("/jobs", response_model=JobResponse, status_code=status.HTTP_202_ACCEPTED, dependencies=[Depends(require_api_key)])
async def submit_job(request: JobCreateRequest, background_tasks: BackgroundTasks) -> JobResponse:
    try:
        payload = request.model_dump()  # type: ignore[attr-defined]
    except AttributeError:
        payload = request.dict()
    record = await job_store.create_job(payload)
    await emit_event(record.id, "status", message="Job created", status=record.status.value)
    background_tasks.add_task(_schedule_job, record.id)
    return JobResponse(
        id=record.id,
        status=record.status,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


@app.get("/jobs/{job_id}", dependencies=[Depends(require_api_key)])
async def get_job(job_id: str) -> JSONResponse:
    record = await job_store.get_job(job_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return JSONResponse(record.to_dict())


@app.get("/jobs/{job_id}/artifacts", dependencies=[Depends(require_api_key)])
async def get_job_artifacts(job_id: str) -> JSONResponse:
    record = await job_store.get_job(job_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    if record.status != JobStatus.COMPLETED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Job not completed yet")
    if not record.result:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Job result missing")
    job_dir = job_store.job_path(job_id)
    repomap_path = job_dir / record.result["repomap_path"]
    if not repomap_path.exists():
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Repo map missing")
    chunks_output: List[Dict[str, Any]] = []
    for chunk_meta in record.result.get("chunks", []):
        chunk_path = job_dir / chunk_meta["path"]
        if not chunk_path.exists():
            continue
        chunks_output.append(
            {
                "index": chunk_meta["index"],
                "token_count": chunk_meta["token_count"],
                "file_count": chunk_meta["file_count"],
                "content": chunk_path.read_text(encoding="utf-8"),
            }
        )
    response_payload = {
        "repomap": repomap_path.read_text(encoding="utf-8"),
        "chunks": chunks_output,
        "warnings": record.result.get("warnings", []),
        "token_estimator": record.result.get("token_estimator"),
        "token_totals": record.result.get("token_totals"),
    }
    return JSONResponse(response_payload)


@app.get("/jobs/{job_id}/events", dependencies=[Depends(require_api_key)])
async def stream_job_events(job_id: str, request: Request) -> StreamingResponse:
    record = await job_store.get_job(job_id)
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    async def event_generator() -> AsyncIterator[str]:
        queue = await event_broker.subscribe(job_id)
        last_event_id = 0
        try:
            for event in record.events:
                payload = event.to_dict()
                last_event_id = max(last_event_id, payload.get("id", 0))
                yield _format_sse(payload)
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=5)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                event_id = event.get("id", 0)
                if event_id and event_id <= last_event_id:
                    continue
                last_event_id = max(last_event_id, event_id)
                yield _format_sse(event)
                if event.get("event") == "status":
                    status_value = event.get("data", {}).get("status")
                    if status_value in {JobStatus.COMPLETED.value, JobStatus.FAILED.value}:
                        break
        finally:
            await event_broker.unsubscribe(job_id, queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/healthz")
async def health_check() -> Dict[str, str]:
    return {"status": "ok"}
