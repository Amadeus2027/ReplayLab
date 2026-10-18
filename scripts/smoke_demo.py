"""One necessary local closure check; no external sites or paid model calls.

Records a real demo browser video, extracts evidence, executes a HAND-AUTHORED
workflow, exports a Skill, and replays that exported workflow. Not a VLM benchmark.
Run: REPLAYLAB_BROWSER_EXECUTABLE=/usr/bin/chromium python scripts/smoke_demo.py
"""

import json
import subprocess
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from playwright.sync_api import sync_playwright

from replaylab.executor import execute
from replaylab.exporter import export_skill
from replaylab.models import Workflow
from replaylab.store import Store, write_json
from replaylab.video import extract_frames

ROOT = Path(__file__).resolve().parents[1]


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_):
        pass


def main():
    import os

    handler = partial(QuietHandler, directory=str(ROOT / "examples/demo"))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}"
    store = Store()
    task_id, path = store.create("local hand-authored integration fixture")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                executable_path=os.environ.get("REPLAYLAB_BROWSER_EXECUTABLE")
            )
            context = browser.new_context(
                record_video_dir=str(path / "recording"), viewport={"width": 1280, "height": 900}
            )
            page = context.new_page()
            page.set_default_timeout(8000)
            page.goto(url)
            page.wait_for_timeout(300)
            page.get_by_label("项目名称", exact=True).fill("ReplayLab")
            page.wait_for_timeout(300)
            page.get_by_label("优先级", exact=True).select_option(label="高")
            page.wait_for_timeout(300)
            page.get_by_label("启用提醒", exact=True).check()
            page.wait_for_timeout(300)
            page.get_by_role("button", name="创建项目", exact=True).click()
            page.wait_for_timeout(300)
            page.get_by_label("搜索项目", exact=True).fill("ReplayLab")
            page.wait_for_timeout(300)
            video = page.video
            context.close()
            video_path = Path(video.path())
            browser.close()
        manifest = extract_frames(video_path, path, max_frames=12)
        frame_ids = [frame["id"] for frame in manifest["frames"]]

        def target(label):
            return {"description": label, "strategy": "label", "value": label}

        def assertion(kind, label, expected=None):
            return {"type": kind, "target": target(label), "expected": expected}

        evidence = {"start_ms": 0, "end_ms": manifest["duration_ms"], "frame_ids": frame_ids}
        actions = [
            ("fill", "项目名称", "ReplayLab", assertion("value", "项目名称", "ReplayLab")),
            ("select", "优先级", "高", assertion("value", "优先级", "高")),
            ("check", "启用提醒", None, assertion("checked", "启用提醒")),
            (
                "click",
                "创建项目",
                None,
                {
                    "type": "text",
                    "target": {
                        "description": "创建状态",
                        "strategy": "role",
                        "role": "status",
                        "value": "",
                    },
                    "expected": "已创建 1 个项目",
                },
            ),
            ("fill", "搜索项目", "ReplayLab", assertion("value", "搜索项目", "ReplayLab")),
        ]
        # The status target has no accessible name: use its exact visible text instead.
        actions[3][3]["target"] = {
            "description": "创建状态",
            "strategy": "text",
            "value": "已创建 1 个项目",
        }
        steps = []
        for i, (action, label, value, check) in enumerate(actions):
            locator = (
                target(label)
                if action != "click"
                else {"description": label, "strategy": "role", "role": "button", "value": label}
            )
            steps.append(
                {
                    "id": f"step_{i + 1:03}",
                    "action": action,
                    "description": f"{action}: {label}",
                    "target": locator,
                    "value": value,
                    "source": evidence,
                    "confidence": 1,
                    "status": "approved",
                    "sensitive": action == "click",
                    "verification": check,
                }
            )
        workflow = Workflow.model_validate(
            {
                "title": "本地项目创建演示（手工流程，非模型恢复）",
                "start_url": url,
                "allowed_origins": [url],
                "steps": steps,
                "postconditions": [
                    {
                        "type": "visible",
                        "target": {
                            "description": "最终项目",
                            "strategy": "text",
                            "value": "ReplayLab · 高优先级 · 提醒已开启",
                        },
                    }
                ],
            }
        )
        store.save(task_id, workflow)
        report = execute(workflow, path / "execution", confirm_sensitive=True)
        assert report["status"] == "passed", report
        exported = export_skill(path, path / "exported-skill")
        runner = subprocess.run(
            [
                sys.executable,
                str(exported / "scripts/run.py"),
                "--confirm-sensitive",
                "--output",
                str(path / "skill-replay"),
            ],
            capture_output=True,
            text=True,
            timeout=60,
            env={
                **os.environ,
                "PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"],
            },
        )
        assert runner.returncode == 0, runner.stdout + runner.stderr
        replay = json.loads((path / "skill-replay/report.json").read_text())
        assert replay["status"] == "passed", replay
        failed_workflow = workflow.model_copy(deep=True)
        failed_workflow.steps[0].verification.expected = "intentionally wrong value"
        stopped = execute(failed_workflow, path / "failure-stop", confirm_sensitive=True)
        assert stopped["status"] == "failed" and len(stopped["steps"]) == 1, stopped
        store.status(task_id, status="passed")
        write_json(
            path / "smoke-summary.json",
            {
                "task_id": task_id,
                "frames": len(frame_ids),
                "execute": report["status"],
                "exported_replay": replay["status"],
                "model_called": False,
            },
        )
        print(
            json.dumps(
                {
                    "task_id": task_id,
                    "artifacts": str(path),
                    "frames": len(frame_ids),
                    "execute": report["status"],
                    "exported_replay": replay["status"],
                    "model_called": False,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        server.shutdown()


if __name__ == "__main__":
    main()
