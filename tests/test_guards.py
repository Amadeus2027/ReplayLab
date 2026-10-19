"""Small regression checks for execution gates and verified export integrity."""

import json

import pytest
from fastapi.testclient import TestClient

from replaylab.api import create_app
from replaylab.executor import NeedsReview, execute, resolve_parameters
from replaylab.exporter import export_skill
from replaylab.models import Workflow
from replaylab.store import Store, digest, write_json


@pytest.fixture
def workflow():
    return Workflow.model_validate(
        {
            "title": "guard fixture",
            "start_url": "https://example.com",
            "allowed_origins": ["https://example.com"],
            "steps": [
                {
                    "id": "step_001",
                    "action": "fill",
                    "description": "Fill a field",
                    "target": {"description": "Name", "strategy": "label", "value": "Name"},
                    "value": "${name}",
                    "confidence": 0.8,
                    "source": {"start_ms": 0, "end_ms": 1000, "frame_ids": ["frame_000"]},
                    "verification": {
                        "type": "visible",
                        "target": {"description": "Name", "strategy": "label", "value": "Name"},
                    },
                }
            ],
            "postconditions": [{"type": "url", "expected": "https://example.com"}],
        }
    )


def test_unapproved_and_sensitive_stop_before_browser(workflow, tmp_path):
    assert execute(workflow, tmp_path)["status"] == "paused"
    workflow.steps[0].status = "approved"
    workflow.steps[0].sensitive = True
    report = execute(workflow, tmp_path)
    assert report["status"] == "paused"
    assert "Sensitive" in report["error"]
    assert not report["steps"]


def test_parameters_are_explicit_and_not_persisted(workflow):
    with pytest.raises(NeedsReview, match="name"):
        resolve_parameters(workflow, {})
    resolved = resolve_parameters(workflow, {"name": "Ada"})
    assert resolved.steps[0].value == "Ada"
    assert workflow.steps[0].value == "${name}"


def test_export_rejects_modified_workflow(workflow, tmp_path):
    task = tmp_path / "task"
    write_json(task / "workflow.json", workflow.model_dump())
    write_json(
        task / "execution/report.json", {"status": "passed", "workflow_digest": digest(workflow)}
    )
    workflow.steps[0].value = "changed"
    write_json(task / "workflow.json", workflow.model_dump())
    with pytest.raises(ValueError, match="unchanged"):
        export_skill(task, tmp_path / "skill")


def test_api_auth_and_edits_invalidate_approval(workflow, tmp_path):
    store = Store(tmp_path)
    task_id, _ = store.create("fixture")
    store.save(task_id, workflow)
    client = TestClient(create_app(store))
    path = f"/api/tasks/{task_id}"
    assert client.get(path).status_code == 401
    headers = {"Authorization": f"Bearer {store.token()}"}
    assert (
        client.post(
            path + "/approve", headers=headers, json={"expected_digest": digest(workflow)}
        ).status_code
        == 200
    )
    approved = store.workflow(task_id)
    assert approved.steps[0].status == "approved"
    assert (
        client.put(
            path + "/workflow",
            headers=headers,
            json={"workflow": approved.model_dump(), "expected_digest": digest(approved)},
        ).status_code
        == 200
    )
    assert store.workflow(task_id).steps[0].status == "needs_review"
    assert (
        client.get(path, headers={**headers, "Origin": "https://untrusted.example"}).status_code
        == 403
    )


def test_workflow_rejects_arbitrary_action_and_path_traversal(workflow, tmp_path):
    data = json.loads(workflow.model_dump_json())
    data["steps"][0]["action"] = "shell"
    with pytest.raises(ValueError):
        Workflow.model_validate(data)
    with pytest.raises(ValueError):
        Store(tmp_path).task("../token")
