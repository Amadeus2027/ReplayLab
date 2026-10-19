"""Focused regressions for reviewed-version binding and honest origin labels."""

import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

from fastapi.testclient import TestClient
from typer.testing import CliRunner

import replaylab.api as api_module
from replaylab.cli import app
from replaylab.models import Workflow
from replaylab.store import Store, WorkflowConflict, digest, write_json

ROOT = Path(__file__).parents[1]


def task_client(tmp_path):
    store = Store(tmp_path)
    task_id, path = store.create("ordinary.mp4")
    workflow = Workflow.model_validate_json((ROOT / "examples/demo/workflow.json").read_text())
    workflow.title = "Ordinary project workflow"
    store.save(task_id, workflow)
    client = TestClient(api_module.create_app(store))
    client.headers["Authorization"] = f"Bearer {store.token()}"
    return store, task_id, path, workflow, client


def test_stale_save_approve_and_execute_never_run_new_workflow(tmp_path, monkeypatch):
    store, task_id, _, workflow, client = task_client(tmp_path)
    base = f"/api/tasks/{task_id}"
    version = client.get(base).json()["workflow_digest"]
    assert version == digest(workflow)
    assert client.post(base + "/approve").status_code == 422
    approved = client.post(base + "/approve", json={"expected_digest": version}).json()
    newer = store.workflow(task_id)
    newer.steps[0].value = "Changed from CLI"
    store.save(task_id, newer)
    calls = []
    monkeypatch.setattr(api_module, "execute", lambda *args: calls.append(args))
    for method, endpoint, body in [
        ("PUT", "/workflow", {"workflow": workflow.model_dump(), "expected_digest": version}),
        ("POST", "/approve", {"expected_digest": version}),
        ("POST", "/execute", {"expected_digest": approved["workflow_digest"]}),
    ]:
        response = client.request(method, base + endpoint, json=body)
        assert response.status_code == 409
        assert response.json()["code"] == "workflow_conflict"
    assert not calls
    assert store.workflow(task_id).steps[0].value == "Changed from CLI"


def test_execution_uses_checked_snapshot_even_if_disk_changes_later(tmp_path, monkeypatch):
    store, task_id, _, workflow, client = task_client(tmp_path)
    base = f"/api/tasks/{task_id}"
    approved = client.post(base + "/approve", json={"expected_digest": digest(workflow)}).json()
    seen = []

    def fake_execute(snapshot, *_):
        newer = snapshot.model_copy(deep=True)
        newer.steps[0].value = "Concurrent update after execution snapshot"
        store.save(task_id, newer)
        seen.append(digest(snapshot))
        return {"status": "passed"}

    monkeypatch.setattr(api_module, "execute", fake_execute)
    response = client.post(base + "/execute", json={"expected_digest": approved["workflow_digest"]})
    assert response.status_code == 202
    assert seen == [approved["workflow_digest"]]
    assert digest(store.workflow(task_id)) != seen[0]
    assert client.get(base).json()["status"] == "needs_review"


def test_compare_and_swap_allows_only_one_concurrent_writer(tmp_path):
    store, task_id, _, workflow, _ = task_client(tmp_path)
    version = digest(workflow)
    barrier = Barrier(2)

    def save(value):
        candidate = workflow.model_copy(deep=True)
        candidate.steps[0].value = value
        barrier.wait(timeout=5)
        try:
            store.save(task_id, candidate, expected_digest=version)
            return "saved"
        except WorkflowConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(save, ["one", "two"])) == ["conflict", "saved"]


def test_manual_import_and_legacy_titles_cannot_claim_video_origin(tmp_path, monkeypatch):
    monkeypatch.setenv("REPLAYLAB_DATA_DIR", str(tmp_path))
    source = tmp_path / "plain.json"
    workflow = json.loads((ROOT / "examples/demo/workflow.json").read_text())
    workflow["title"] = "No special keywords"
    source.write_text(json.dumps(workflow))
    result = CliRunner().invoke(app, ["import-workflow", str(source)])
    assert result.exit_code == 0, result.output
    store = Store(tmp_path)
    client = TestClient(api_module.create_app(store))
    client.headers["Authorization"] = f"Bearer {store.token()}"
    task_id = result.output.strip()
    assert client.get(f"/api/tasks/{task_id}").json()["workflow_origin"] == "manual"
    store.status(task_id, workflow_origin="unknown")
    assert client.get(f"/api/tasks/{task_id}").json()["workflow_origin"] == "unknown"
    assert client.get("/api/tasks").json()[0]["workflow_origin"] == "unknown"


def test_recorded_generation_edits_and_broken_receipts_are_distinct(tmp_path):
    store, task_id, path, _, client = task_client(tmp_path)
    evidence = ROOT / "docs/validation/v0.1.1/passed"
    for name in ["inference.json", "workflow.generated.json", "frames.json", "model-response.txt"]:
        shutil.copy(evidence / name, path / name)
    generated = Workflow.model_validate_json((path / "workflow.generated.json").read_text())
    for step in generated.steps:
        step.status = "approved"
    store.save(task_id, generated)
    receipt = json.loads((path / "inference.json").read_text())
    store.status(task_id, media_sha256=receipt["source_sha256"])
    url = f"/api/tasks/{task_id}"
    assert client.get(url).json()["workflow_origin"] == "video"
    generated.steps[0].value = "human edit"
    store.save(task_id, generated)
    assert client.get(url).json()["workflow_origin"] == "video_edited"
    receipt["response_sha256"] = "tampered"
    write_json(path / "inference.json", receipt)
    assert client.get(url).json()["workflow_origin"] == "unknown"
