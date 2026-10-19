import hashlib
import json
import os
import re
import secrets
from pathlib import Path
from uuid import uuid4

from filelock import FileLock

from .models import Workflow


class WorkflowConflict(ValueError):
    pass


def data_root() -> Path:
    return Path(os.environ.get("REPLAYLAB_DATA_DIR", ".replaylab")).resolve()


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def digest(workflow: Workflow) -> str:
    return hashlib.sha256(workflow.model_dump_json().encode()).hexdigest()


class Store:
    def __init__(self, root: Path | None = None):
        self.root = root or data_root()
        self.root.mkdir(parents=True, exist_ok=True)

    def task(self, task_id: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{12}", task_id):
            raise ValueError("Invalid task ID")
        path = self.root / task_id
        if not path.is_dir():
            raise FileNotFoundError(task_id)
        return path

    def create(self, source: str) -> tuple[str, Path]:
        task_id = uuid4().hex[:12]
        path = self.root / task_id
        path.mkdir()
        write_json(path / "task.json", {"id": task_id, "source": source, "status": "created"})
        return task_id, path

    def status(self, task_id: str, **updates):
        task = self.task(task_id)
        with FileLock(task / ".workflow.lock", timeout=5):
            path = task / "task.json"
            metadata = json.loads(path.read_text())
            metadata.update(updates)
            write_json(path, metadata)

    def workflow(self, task_id: str) -> Workflow:
        return Workflow.model_validate_json((self.task(task_id) / "workflow.json").read_text())

    def save(self, task_id: str, workflow: Workflow, expected_digest: str | None = None):
        path = self.task(task_id)
        # CLI and API writers share this lock; compare and replace are one operation.
        with FileLock(path / ".workflow.lock", timeout=5):
            if expected_digest is not None and digest(self.workflow(task_id)) != expected_digest:
                raise WorkflowConflict("流程已在其他位置更新，请加载最新流程后重新核对。")
            write_json(path / "workflow.json", workflow.model_dump())

    def token(self) -> str:
        path = self.root / "token"
        try:
            with open(path, "x", opener=lambda name, flags: os.open(name, flags, 0o600)) as handle:
                handle.write(secrets.token_urlsafe(32))
        except FileExistsError:
            pass
        return path.read_text().strip()
