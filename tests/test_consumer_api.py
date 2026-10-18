"""Necessary checks for the new consumer entry and portable download."""

import json
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from fastapi.testclient import TestClient

import replaylab.api as api_module
from replaylab.models import Workflow
from replaylab.store import Store, digest, write_json


def test_upload_keeps_video_and_starts_analysis(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        api_module, "analyze", lambda store, task_id, source, url: calls.append((source, url))
    )
    store = Store(tmp_path)
    client = TestClient(api_module.create_app(store))
    headers = {"Authorization": f"Bearer {store.token()}"}
    response = client.post(
        "/api/tasks/upload",
        headers=headers,
        files={"video": ("demo.webm", b"fixture video", "video/webm")},
        data={"start_url": "https://example.com"},
    )
    assert response.status_code == 202
    assert Path(calls[0][0]).read_bytes() == b"fixture video"
    assert calls[0][1] == "https://example.com"
    assert (
        client.post(
            "/api/tasks/upload",
            headers=headers,
            files={"video": ("bad.exe", b"x")},
            data={"start_url": "https://example.com"},
        ).status_code
        == 422
    )


def test_verified_skill_download_is_authenticated_zip(tmp_path):
    store = Store(tmp_path)
    task_id, path = store.create("hand-authored fixture")
    workflow = Workflow.model_validate_json(
        (Path(__file__).parents[1] / "examples/demo/workflow.json").read_text()
    )
    store.save(task_id, workflow)
    write_json(
        path / "execution/report.json", {"status": "passed", "workflow_digest": digest(workflow)}
    )
    client = TestClient(api_module.create_app(store))
    headers = {"Authorization": f"Bearer {store.token()}"}
    response = client.post(f"/api/tasks/{task_id}/export", headers=headers)
    assert response.status_code == 200
    url = response.json()["download_url"]
    assert client.get(url).status_code == 401
    download = client.get(url, headers=headers)
    assert download.status_code == 200
    with ZipFile(BytesIO(download.content)) as archive:
        workflow_file = next(name for name in archive.namelist() if name.endswith("/workflow.json"))
        assert json.loads(archive.read(workflow_file))["title"] == workflow.title
        assert any(name.endswith("/SKILL.md") for name in archive.namelist())
