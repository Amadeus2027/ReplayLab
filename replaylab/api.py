"""Loopback-only workbench API. Mutations require a per-install bearer token."""

import json
import re
import secrets
import shutil
from contextlib import contextmanager
from pathlib import Path
from threading import Lock
from uuid import uuid4

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import __version__
from .executor import execute
from .exporter import export_skill
from .models import Model, Workflow, origin
from .pipeline import analyze
from .store import Store, WorkflowConflict, digest
from .validation import workflow_origin


class AnalyzeRequest(Model):
    source: str
    start_url: str


class VersionRequest(Model):
    expected_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class SaveRequest(VersionRequest):
    workflow: Workflow


class ExecuteRequest(VersionRequest):
    parameters: dict[str, str] = Field(default_factory=dict)
    confirm_sensitive: bool = False


def create_app(store: Store | None = None) -> FastAPI:
    store = store or Store()
    token = store.token()
    app = FastAPI(title="ReplayLab", docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"]
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["Authorization", "Content-Type"],
    )
    locks: dict[str, Lock] = {}

    @app.exception_handler(WorkflowConflict)
    def workflow_conflict(_request, exc):
        return JSONResponse(
            status_code=409, content={"detail": str(exc), "code": "workflow_conflict"}
        )

    def snapshot(workflow):
        return {"workflow": workflow, "workflow_digest": digest(workflow)}

    def checked_workflow(task_id, expected_digest):
        workflow = store.workflow(task_id)
        if digest(workflow) != expected_digest:
            raise WorkflowConflict("流程已在其他位置更新，请加载最新流程后重新核对。")
        return workflow

    def authorize(request: Request, authorization: str = Header(default="")):
        if not secrets.compare_digest(authorization, f"Bearer {token}"):
            raise HTTPException(401, "Valid local API token required")
        request_origin = request.headers.get("origin")
        own_origin = f"{request.url.scheme}://{request.headers.get('host')}"
        if request_origin and request_origin not in {
            own_origin,
            "http://127.0.0.1:5173",
            "http://localhost:5173",
        }:
            raise HTTPException(403, "Origin is not allowed")

    def task_path(task_id: str) -> Path:
        try:
            return store.task(task_id)
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(404, "Task not found") from exc

    def reserve(task_id: str):
        task_path(task_id)
        lock = locks.setdefault(task_id, Lock())
        if not lock.acquire(blocking=False):
            raise HTTPException(409, "Task is busy")
        return lock

    @contextmanager
    def mutation(task_id: str):
        lock = reserve(task_id)
        try:
            yield
        finally:
            lock.release()

    def background_analysis(task_id, body, lock):
        try:
            analyze(store, task_id, body.source, body.start_url)
        except Exception:
            pass  # Pipeline persists the failure; polling returns it to the workbench.
        finally:
            lock.release()

    def background_execution(task_id, body, workflow, lock):
        try:
            report = execute(
                workflow, store.task(task_id) / "execution", body.parameters, body.confirm_sensitive
            )
            current = store.workflow(task_id)
            status = report["status"] if digest(current) == digest(workflow) else "needs_review"
            store.status(task_id, status=status)
        except Exception as exc:
            store.status(task_id, status="failed", error=str(exc))
        finally:
            lock.release()

    auth = [Depends(authorize)]

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": __version__}

    @app.get("/api/tasks", dependencies=auth)
    def tasks():
        result = []
        for path in sorted(
            store.root.glob("*/task.json"), key=lambda p: p.stat().st_mtime, reverse=True
        ):
            item = json.loads(path.read_text())
            workflow_path = path.parent / "workflow.json"
            if workflow_path.exists():
                workflow = Workflow.model_validate_json(workflow_path.read_text())
                item.update(
                    title=workflow.title,
                    step_count=len(workflow.steps),
                    workflow_origin=workflow_origin(path.parent, workflow),
                )
            result.append(item)
        return result

    @app.post("/api/validate", dependencies=auth)
    def validate_workflow(workflow: Workflow):
        return workflow

    @app.post("/api/tasks", dependencies=auth, status_code=202)
    def create_task(body: AnalyzeRequest, background: BackgroundTasks):
        try:
            origin(body.start_url)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        task_id, _ = store.create(body.source)
        lock = reserve(task_id)
        background.add_task(background_analysis, task_id, body, lock)
        return {"id": task_id}

    @app.post("/api/tasks/upload", dependencies=auth, status_code=202)
    def upload_task(
        background: BackgroundTasks, video: UploadFile = File(), start_url: str = Form()
    ):
        try:
            origin(start_url)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        suffix = Path(video.filename or "video.mp4").suffix.lower()
        if suffix not in {".mp4", ".mov", ".webm", ".mkv", ".avi", ".m4v"}:
            raise HTTPException(422, "请选择 MP4、MOV、WebM、MKV、AVI 或 M4V 视频")
        task_id, path = store.create(video.filename or "上传的视频")
        media = path / f"input{suffix}"
        size = 0
        try:
            with media.open("wb") as handle:
                while chunk := video.file.read(1024 * 1024):
                    size += len(chunk)
                    if size > 200 * 1024 * 1024:
                        raise HTTPException(413, "视频大小不能超过 200 MB")
                    handle.write(chunk)
            if size == 0:
                raise HTTPException(422, "视频文件为空")
        except Exception:
            shutil.rmtree(path)
            raise
        finally:
            video.file.close()
        lock = reserve(task_id)
        background.add_task(
            background_analysis,
            task_id,
            AnalyzeRequest(source=str(media), start_url=start_url),
            lock,
        )
        return {"id": task_id}

    @app.get("/api/tasks/{task_id}", dependencies=auth)
    def detail(task_id: str):
        path = task_path(task_id)
        result = json.loads((path / "task.json").read_text())
        result["has_media"] = bool(
            result.get("media_path") and Path(result["media_path"]).is_file()
        )
        for name, filename in {
            "workflow": "workflow.json",
            "evidence": "frames.json",
            "report": "execution/report.json",
            "timings": "timings.json",
        }.items():
            if (path / filename).exists():
                result[name] = json.loads((path / filename).read_text())
        if "workflow" in result:
            workflow = Workflow.model_validate(result["workflow"])
            result["workflow_digest"] = digest(workflow)
            result["workflow_origin"] = workflow_origin(path, workflow)
        return result

    @app.get("/api/tasks/{task_id}/media", dependencies=auth)
    def media(task_id: str):
        metadata = json.loads((task_path(task_id) / "task.json").read_text())
        path = Path(metadata.get("media_path", ""))
        if not path.is_file():
            raise HTTPException(404, "原视频不可用")
        return FileResponse(path)

    @app.put("/api/tasks/{task_id}/workflow", dependencies=auth)
    def save_workflow(task_id: str, body: SaveRequest):
        with mutation(task_id):
            workflow = body.workflow
            # Any edit invalidates approval. A separate user action approves the new version.
            for step in workflow.steps:
                step.status = "needs_review"
            store.save(task_id, workflow, expected_digest=body.expected_digest)
            store.status(task_id, status="needs_review")
        return snapshot(workflow)

    @app.post("/api/tasks/{task_id}/approve", dependencies=auth)
    def approve(task_id: str, body: VersionRequest):
        with mutation(task_id):
            workflow = checked_workflow(task_id, body.expected_digest)
            if workflow.uncertainties:
                raise HTTPException(409, "Resolve uncertainties before approval")
            for step in workflow.steps:
                step.status = "approved"
            store.save(task_id, workflow, expected_digest=body.expected_digest)
            store.status(task_id, status="approved")
        return snapshot(workflow)

    @app.post("/api/tasks/{task_id}/execute", dependencies=auth, status_code=202)
    def run(task_id: str, body: ExecuteRequest, background: BackgroundTasks):
        lock = reserve(task_id)
        try:
            workflow = checked_workflow(task_id, body.expected_digest)
            if workflow.uncertainties or any(s.status != "approved" for s in workflow.steps):
                raise HTTPException(409, "Review and approve this workflow before execution")
            store.status(task_id, status="executing")
        except Exception:
            lock.release()
            raise
        background.add_task(background_execution, task_id, body, workflow, lock)
        return {"status": "executing"}

    @app.post("/api/tasks/{task_id}/export", dependencies=auth)
    def export(task_id: str):
        with mutation(task_id):
            export_id = uuid4().hex[:6]
            destination = store.root / "exports" / f"skill-{task_id}-{export_id}"
            try:
                export_skill(task_path(task_id), destination)
            except (ValueError, FileNotFoundError) as exc:
                raise HTTPException(409, str(exc)) from exc
            shutil.make_archive(
                str(destination), "zip", root_dir=destination.parent, base_dir=destination.name
            )
        return {
            "path": str(destination),
            "download_url": f"/api/tasks/{task_id}/exports/{export_id}",
        }

    @app.get("/api/tasks/{task_id}/exports/{export_id}", dependencies=auth)
    def download(task_id: str, export_id: str):
        task_path(task_id)
        if not re.fullmatch(r"[a-f0-9]{6}", export_id):
            raise HTTPException(404)
        path = store.root / "exports" / f"skill-{task_id}-{export_id}.zip"
        if not path.is_file():
            raise HTTPException(404)
        return FileResponse(
            path, filename=f"replaylab-skill-{task_id}.zip", media_type="application/zip"
        )

    @app.get("/api/tasks/{task_id}/assets/{kind}/{filename}", dependencies=auth)
    def asset(task_id: str, kind: str, filename: str):
        if kind not in {"frames", "execution"} or Path(filename).name != filename:
            raise HTTPException(404)
        if Path(filename).suffix not in {".jpg", ".png"}:
            raise HTTPException(404)
        path = task_path(task_id) / kind / filename
        if not path.is_file():
            raise HTTPException(404)
        return FileResponse(path)

    dist = Path(__file__).resolve().parents[1] / "apps/web-workbench/dist"
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="workbench")
    else:

        @app.get("/")
        def missing_workbench():
            return {"message": "Build workbench: cd apps/web-workbench && npm ci && npm run build"}

    return app
