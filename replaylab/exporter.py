import json
import re
import shutil
from pathlib import Path

from .models import Workflow
from .store import digest, write_json


def export_skill(task_dir: Path, destination: Path) -> Path:
    workflow = Workflow.model_validate_json((task_dir / "workflow.json").read_text())
    report = json.loads((task_dir / "execution" / "report.json").read_text())
    if report.get("status") != "passed" or report.get("workflow_digest") != digest(workflow):
        raise ValueError("Export requires a passed execution of the current, unchanged workflow")
    if destination.exists():
        raise ValueError("Export destination already exists; choose a new directory")
    if (
        not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", destination.name)
        or len(destination.name) > 64
    ):
        raise ValueError(
            "Skill directory name must be 1–64 lowercase letters/digits with single hyphens"
        )
    destination.mkdir(parents=True)
    write_json(destination / "workflow.json", workflow.model_dump())
    shutil.copy2(task_dir / "execution" / "report.json", destination / "verification.json")
    scripts = destination / "scripts"
    scripts.mkdir()
    (scripts / "run.py").write_text(
        '''"""Run with the installed ReplayLab runtime; pass parameters/confirmation via CLI flags."""
from pathlib import Path
import subprocess
import sys

workflow = Path(__file__).resolve().parents[1] / "workflow.json"
raise SystemExit(subprocess.call(["replaylab", "run-workflow", str(workflow), *sys.argv[1:]]))
''',
        encoding="utf-8",
    )
    (destination / "SKILL.md").write_text(
        f"""---
name: {destination.name}
description: Replay a reviewed browser workflow recovered from a demonstration video using the ReplayLab CLI.
---

# ReplayLab verified workflow

1. Read `workflow.json`, including preconditions, allowed origins, parameters and sensitive steps.
2. Explain the concrete actions to the user and obtain authorization for the task.
3. Install ReplayLab 0.1 and its Playwright browser if absent. The runtime is an external dependency.
4. Run `python scripts/run.py --params-file /path/to/parameters.json` from this skill directory.
   Omit `--params-file` when no parameters are required. Parameter files are JSON string maps.
5. Add `--confirm-sensitive` only when the user explicitly authorizes the sensitive actions.
6. Inspect the report path printed by the CLI. On failure or pause, stop and report the reason.
   Do not silently retry submissions or claim completion from partial success.

`verification.json` records a previous run, not a guarantee of future success.
The runtime opens a fresh isolated browser and does not import user cookies.
""",
        encoding="utf-8",
    )
    return destination
