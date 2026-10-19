"""Summarize one real-video experiment. No inference, approval or execution occurs here."""

import hashlib
import json
from pathlib import Path

from .compiler import validate_draft
from .models import Workflow
from .store import digest, write_json


def read(path: Path):
    return json.loads(path.read_text()) if path.exists() else None


def review_changes(generated: Workflow, current: Workflow) -> dict:
    original = {step.id: step.model_dump(exclude={"status"}) for step in generated.steps}
    reviewed = {step.id: step.model_dump(exclude={"status"}) for step in current.steps}
    return {
        "changed_step_ids": [
            key
            for key in sorted(original.keys() & reviewed.keys())
            if original[key] != reviewed[key]
        ],
        "added_step_ids": sorted(reviewed.keys() - original.keys()),
        "removed_step_ids": sorted(original.keys() - reviewed.keys()),
        "step_order_changed": [s.id for s in generated.steps] != [s.id for s in current.steps],
        "other_fields_changed": [
            key
            for key, value in generated.model_dump(exclude={"steps"}).items()
            if current.model_dump()[key] != value
        ],
    }


def workflow_origin(task_dir: Path, current: Workflow) -> str:
    """Label origin from compiler receipts, never from titles or filenames.

    This describes recorded generation, not successful execution or a signed attestation.
    Full media/frame byte verification remains the explicit validation-report operation.
    """
    metadata = read(task_dir / "task.json") or {}
    inference = read(task_dir / "inference.json") or {}
    try:
        generated = Workflow.model_validate(read(task_dir / "workflow.generated.json"))
        manifest = read(task_dir / "frames.json")
        raw = (task_dir / "model-response.txt").read_text()
        recorded = (
            inference.get("status") == "succeeded"
            and digest(generated) == inference.get("generated_workflow_digest")
            and hashlib.sha256(raw.encode()).hexdigest() == inference.get("response_sha256")
            and hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
            == inference.get("manifest_sha256")
            and bool(inference.get("source_sha256"))
            and inference["source_sha256"] == metadata.get("media_sha256")
            and digest(validate_draft(raw, manifest, generated.start_url)) == digest(generated)
        )
        if recorded:
            return "video_edited" if any(review_changes(generated, current).values()) else "video"
    except (ValueError, OSError, KeyError, TypeError):
        pass
    return "manual" if metadata.get("workflow_origin") == "manual" else "unknown"


def summarize(task_dir: Path) -> dict:
    metadata = read(task_dir / "task.json") or {}
    inference = read(task_dir / "inference.json") or {}
    frames = read(task_dir / "frames.json") or {}
    generated_data = read(task_dir / "workflow.generated.json")
    current_data = read(task_dir / "workflow.json")
    generated = Workflow.model_validate(generated_data) if generated_data else None
    current = Workflow.model_validate(current_data) if current_data else None
    execution = read(task_dir / "execution/report.json")
    replay = read(task_dir / "skill-replay/report.json")
    raw_path = task_dir / "model-response.txt"
    evidence_matches = bool(frames.get("frames"))
    for frame in frames.get("frames", []):
        image = (task_dir / frame["path"]).resolve()
        if not image.is_relative_to(task_dir.resolve()) or not image.is_file():
            evidence_matches = False
            break
        if hashlib.sha256(image.read_bytes()).hexdigest() != inference.get("frame_sha256", {}).get(
            frame["id"]
        ):
            evidence_matches = False
    manifest_matches = bool(frames) and hashlib.sha256(
        json.dumps(frames, sort_keys=True).encode()
    ).hexdigest() == inference.get("manifest_sha256")
    raw_matches = raw_path.exists() and hashlib.sha256(
        raw_path.read_bytes()
    ).hexdigest() == inference.get("response_sha256")
    source = Path(metadata.get("media_path", ""))
    source_matches = False
    if source.is_file():
        with source.open("rb") as handle:
            source_matches = hashlib.file_digest(handle, "sha256").hexdigest() == metadata.get(
                "media_sha256"
            )
    raw_workflow_matches = False
    if generated and raw_matches:
        try:
            raw_workflow_matches = digest(
                validate_draft(raw_path.read_text(), frames, generated.start_url)
            ) == digest(generated)
        except ValueError:
            pass
    provenance_valid = bool(
        generated
        and inference.get("status") == "succeeded"
        and digest(generated) == inference.get("generated_workflow_digest")
        and evidence_matches
        and manifest_matches
        and raw_matches
        and source_matches
        and inference.get("source_sha256") == metadata.get("media_sha256")
        and raw_workflow_matches
    )
    execution_valid = bool(
        current
        and execution
        and execution.get("status") == "passed"
        and execution.get("workflow_digest") == digest(current)
    )
    replay_valid = bool(
        current
        and replay
        and replay.get("status") == "passed"
        and replay.get("workflow_digest") == digest(current)
    )
    # A model call alone or a hand-authored successful workflow never counts as completion.
    independent_execution = bool(
        execution
        and execution.get("independent_checks")
        and all(check["status"] == "passed" for check in execution["independent_checks"])
    )
    independent_replay = bool(
        replay
        and replay.get("independent_checks")
        and all(check["status"] == "passed" for check in replay["independent_checks"])
    )
    complete = (
        provenance_valid
        and execution_valid
        and replay_valid
        and independent_execution
        and independent_replay
    )
    changes = review_changes(generated, current) if generated and current else None
    unmodified = changes is not None and not any(changes.values())
    result = {
        "task_id": metadata.get("id"),
        "status": "passed" if complete else "incomplete",
        "video_duration_ms": frames.get("duration_ms"),
        "source_sha256": metadata.get("media_sha256"),
        "frame_count": len(frames.get("frames", [])),
        "model": {
            "status": inference.get("status", "not_run"),
            "name": inference.get("model"),
            "provider_host": inference.get("provider_host"),
            "seconds": inference.get("seconds"),
            "usage": inference.get("usage"),
        },
        "provenance": {
            "valid": provenance_valid,
            "source_matches": source_matches,
            "frames_match": evidence_matches,
            "manifest_matches": manifest_matches,
            "raw_response_matches": raw_matches,
            "raw_workflow_matches": raw_workflow_matches,
        },
        "generated_step_count": len(generated.steps) if generated else None,
        "review": changes,
        "recovery_mode": "unmodified_model_workflow"
        if unmodified
        else "reviewed_with_changes"
        if changes
        else "not_generated",
        "execution": {
            "status": execution.get("status", "not_run") if execution else "not_run",
            "current_workflow_verified": execution_valid,
            "independent_checks_passed": independent_execution,
        },
        "skill_replay": {
            "status": replay.get("status", "not_run") if replay else "not_run",
            "current_workflow_verified": replay_valid,
            "independent_checks_passed": independent_replay,
        },
        "reference_comparison": read(task_dir / "reference-comparison.json"),
        "timings": read(task_dir / "timings.json"),
    }
    write_json(task_dir / "validation.json", result)
    return result
