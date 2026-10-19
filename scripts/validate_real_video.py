"""One real-video experiment. The model receives images, never the recording actions.

record: make a 40-second browser recording and separate reference assertions.
verify: require a genuinely model-generated, reviewed workflow, replay it and its Skill.
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from contextlib import contextmanager
from difflib import SequenceMatcher
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from uuid import uuid4

from playwright.sync_api import sync_playwright

from replaylab.executor import execute, read_assertions, read_parameters
from replaylab.exporter import export_skill
from replaylab.store import Store, write_json
from replaylab.validation import summarize
from replaylab.video import command

ROOT = Path(__file__).resolve().parents[1]


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_):
        pass


@contextmanager
def demo_server(port):
    server = ThreadingHTTPServer(
        ("127.0.0.1", port), partial(QuietHandler, directory=str(ROOT / "examples/demo"))
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def record(output: Path, port: int):
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    project_name = f"Replay-{uuid4().hex[:6].upper()}"
    with demo_server(port) as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=os.environ.get("REPLAYLAB_BROWSER_EXECUTABLE")
        )
        context = browser.new_context(
            record_video_dir=str(output / "recording"),
            viewport={"width": 1280, "height": 1200},
            record_video_size={"width": 1280, "height": 1200},
        )
        page = context.new_page()
        page.set_default_timeout(8000)
        try:
            page.goto(url)
            page.wait_for_timeout(4000)
            page.get_by_label("项目名称", exact=True).fill(project_name)
            page.wait_for_timeout(6000)
            page.get_by_label("优先级", exact=True).select_option(label="高")
            page.wait_for_timeout(6000)
            page.get_by_label("启用提醒", exact=True).check()
            page.wait_for_timeout(6000)
            page.get_by_role("button", name="创建项目", exact=True).click()
            page.wait_for_timeout(8000)
            page.get_by_label("搜索项目", exact=True).fill(project_name)
            page.wait_for_timeout(10000)
            video = page.video
            context.close()
            video.save_as(output / "source.webm")
        finally:
            browser.close()
    shutil.rmtree(output / "recording")
    duration_ms = round(
        float(
            command(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "default=nw=1:nk=1",
                    str(output / "source.webm"),
                ]
            )
        )
        * 1000
    )
    with (output / "source.webm").open("rb") as handle:
        source_hash = hashlib.file_digest(handle, "sha256").hexdigest()
    # Reference is an evaluation artifact, not a Workflow and never compiler input.
    actions = [
        {"action": "fill", "target": "项目名称", "value": project_name},
        {"action": "select", "target": "优先级", "value": "高"},
        {"action": "check", "target": "启用提醒", "value": None},
        {"action": "click", "target": "创建项目", "value": None},
        {"action": "fill", "target": "搜索项目", "value": project_name},
    ]
    assertions = [
        {
            "type": "text",
            "target": {
                "description": "只创建一个项目",
                "strategy": "text",
                "value": "已创建 1 个项目",
            },
            "expected": "已创建 1 个项目",
        },
        {
            "type": "visible",
            "target": {
                "description": "创建的项目及其设置",
                "strategy": "text",
                "value": f"{project_name} · 高优先级 · 提醒已开启",
            },
        },
        {
            "type": "value",
            "target": {"description": "搜索内容", "strategy": "label", "value": "搜索项目"},
            "expected": project_name,
        },
    ]
    write_json(output / "reference.json", {"actions": actions, "not_model_input": True})
    write_json(output / "expected.json", assertions)
    write_json(
        output / "sample.json",
        {
            "kind": "controlled_browser_recording",
            "duration_ms": duration_ms,
            "source_sha256": source_hash,
            "start_url": url,
            "port": port,
            "model_called": False,
        },
    )
    print(
        json.dumps(
            {
                "sample": str(output),
                "duration_ms": duration_ms,
                "start_url": url,
                "model_called": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f'Next: replaylab analyze "{output / "source.webm"}" --start-url {url}')


def signature(action, target, value):
    return (
        action,
        target.strip(),
        value if action in {"fill", "select", "press", "navigate"} else None,
    )


def verify(task_id: str, sample: Path, confirm_sensitive: bool, params_file: Path | None):
    sample = sample.resolve()
    metadata = json.loads((sample / "sample.json").read_text())
    store = Store()
    task_dir = store.task(task_id)
    summary = summarize(task_dir)
    if not summary["provenance"]["valid"] or summary["source_sha256"] != metadata["source_sha256"]:
        raise ValueError("This task is not a verified model compilation of this exact video")
    workflow = store.workflow(task_id)
    if workflow.start_url != metadata["start_url"] or workflow.allowed_origins != [
        metadata["start_url"]
    ]:
        raise ValueError("The reviewed workflow must target this sample's local demo origin")
    if any(step.status != "approved" for step in workflow.steps) or workflow.uncertainties:
        raise ValueError(
            "Review the actual generated workflow, resolve uncertainties, then run replaylab approve"
        )
    reference = json.loads((sample / "reference.json").read_text())["actions"]
    generated = json.loads((task_dir / "workflow.generated.json").read_text())["steps"]
    expected_signatures = [
        signature(step["action"], step["target"], step["value"]) for step in reference
    ]
    recovered = [
        signature(step["action"], (step.get("target") or {}).get("value", ""), step.get("value"))
        for step in generated
    ]
    matches = sum(
        block.size
        for block in SequenceMatcher(
            a=expected_signatures, b=recovered, autojunk=False
        ).get_matching_blocks()
    )
    write_json(
        task_dir / "reference-comparison.json",
        {
            "method": "exact action + visible target text + value, in sequence; not a semantic accuracy benchmark",
            "expected_steps": len(reference),
            "generated_steps": len(generated),
            "exact_matches": matches,
        },
    )
    checks = read_assertions(sample / "expected.json")
    try:
        with demo_server(metadata["port"]):
            report = execute(
                workflow,
                task_dir / "execution",
                read_parameters(params_file),
                confirm_sensitive=confirm_sensitive,
                expected_checks=checks,
            )
            store.status(task_id, status=report["status"])
            if report["status"] != "passed":
                raise ValueError(
                    f"Execution {report['status']}; inspect {task_dir / 'execution/report.json'}"
                )
            destination = export_skill(task_dir, task_dir / f"real-video-skill-{uuid4().hex[:6]}")
            args = [
                sys.executable,
                str(destination / "scripts/run.py"),
                "--output",
                str(task_dir / "skill-replay"),
                "--expect-file",
                str(sample / "expected.json"),
            ]
            if confirm_sensitive:
                args.append("--confirm-sensitive")
            if params_file:
                args.extend(["--params-file", str(params_file.resolve())])
            result = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=180,
                env={
                    **os.environ,
                    "PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"],
                },
            )
            if result.returncode:
                raise ValueError(
                    f"Skill replay failed; inspect {task_dir / 'skill-replay/report.json'}"
                )
    finally:
        summary = summarize(task_dir)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if summary["status"] != "passed":
        raise ValueError("Real-video validation is incomplete; inspect validation.json")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    recorder = commands.add_parser("record")
    recorder.add_argument("--output", type=Path, required=True)
    recorder.add_argument("--port", type=int, default=8891)
    verifier = commands.add_parser("verify")
    verifier.add_argument("task_id")
    verifier.add_argument("--sample", type=Path, required=True)
    verifier.add_argument("--confirm-sensitive", action="store_true")
    verifier.add_argument("--params-file", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "record":
            record(args.output, args.port)
        else:
            verify(args.task_id, args.sample, args.confirm_sensitive, args.params_file)
    except Exception as exc:
        parser.exit(1, f"{type(exc).__name__}: {exc}\n")


if __name__ == "__main__":
    main()
