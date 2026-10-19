"""Targeted compiler/provenance checks. Mock responses are not real-video acceptance."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import replaylab.compiler as compiler
from replaylab.models import Workflow
from replaylab.store import digest, write_json
from replaylab.validation import review_changes, summarize


@pytest.fixture
def draft():
    workflow = Workflow.model_validate_json(
        (Path(__file__).parents[1] / "examples/demo/workflow.json").read_text()
    )
    data = workflow.model_dump(exclude={"schema_version", "start_url", "allowed_origins"})
    data["steps"] = data["steps"][:1]
    data["steps"][0]["source"] = {"start_ms": 0, "end_ms": 1000, "frame_ids": ["frame_000"]}
    data["steps"][0]["status"] = "approved"
    return data


@pytest.fixture
def manifest():
    return {
        "duration_ms": 1000,
        "frames": [{"id": "frame_000", "timestamp_ms": 0, "path": "frames/frame_000.jpg"}],
    }


def test_output_must_cite_real_evidence_and_stay_unapproved(draft, manifest):
    workflow = compiler.validate_draft(json.dumps(draft), manifest, "https://example.com")
    assert workflow.steps[0].status == "needs_review"
    assert workflow.allowed_origins == ["https://example.com"]
    draft["steps"][0]["source"]["frame_ids"] = ["invented_frame"]
    with pytest.raises(ValueError, match="nonexistent"):
        compiler.validate_draft(json.dumps(draft), manifest, "https://example.com")


def test_inference_receipt_preserves_raw_output_without_reference_leak(
    tmp_path, monkeypatch, draft, manifest
):
    write_json(tmp_path / "reference.json", {"forbidden_model_input": "DO_NOT_SEND_REFERENCE"})
    (tmp_path / "frames").mkdir()
    (tmp_path / "frames/frame_000.jpg").write_bytes(b"mock image; no real API call")
    calls = []
    raw = json.dumps(draft)

    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            id="mock-response",
            model="mock-vision",
            usage=None,
            choices=[SimpleNamespace(message=SimpleNamespace(content=raw), finish_reason="stop")],
        )

    monkeypatch.setenv("REPLAYLAB_API_KEY", "test-only-placeholder")
    monkeypatch.setenv("REPLAYLAB_MODEL", "mock-vision")
    monkeypatch.setattr(
        compiler,
        "OpenAI",
        lambda **kwargs: SimpleNamespace(
            base_url="https://mock.invalid/v1",
            chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
        ),
    )
    workflow = compiler.compile_video(tmp_path, manifest, "https://example.com")
    receipt = json.loads((tmp_path / "inference.json").read_text())
    assert receipt["generated_workflow_digest"] == digest(workflow)
    assert (tmp_path / "model-response.txt").read_text() == raw
    assert "DO_NOT_SEND_REFERENCE" not in json.dumps(calls)
    assert "test-only-placeholder" not in (tmp_path / "inference.json").read_text()
    raw = '{"invalid":true}'
    with pytest.raises(ValueError):
        compiler.compile_video(tmp_path, manifest, "https://example.com")
    assert json.loads((tmp_path / "inference.json").read_text())["status"] == "invalid_output"
    assert len(list((tmp_path / "inference-attempts").glob("*/model-response.txt"))) == 2


def test_manual_workflow_cannot_be_reported_as_video_recovery(tmp_path, draft, manifest):
    workflow = compiler.validate_draft(json.dumps(draft), manifest, "https://example.com")
    write_json(tmp_path / "workflow.json", workflow.model_dump())
    passed = {
        "status": "passed",
        "workflow_digest": digest(workflow),
        "independent_checks": [{"status": "passed"}],
    }
    write_json(tmp_path / "execution/report.json", passed)
    write_json(tmp_path / "skill-replay/report.json", passed)
    summary = summarize(tmp_path)
    assert summary["status"] == "incomplete"
    assert summary["model"]["status"] == "not_run"
    assert not summary["provenance"]["valid"]
    reviewed = workflow.model_copy(deep=True)
    reviewed.steps[0].status = "approved"
    assert not review_changes(workflow, reviewed)["changed_step_ids"]
    reviewed.steps[0].value = "edited"
    assert review_changes(workflow, reviewed)["changed_step_ids"] == [workflow.steps[0].id]
