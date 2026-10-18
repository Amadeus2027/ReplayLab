import json
import webbrowser
from pathlib import Path
from typing import Annotated

import typer

from .compiler import compile_video
from .executor import execute as run
from .executor import read_parameters
from .exporter import export_skill
from .models import Workflow
from .pipeline import analyze as analyze_task
from .store import Store

app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)


@app.command()
def analyze(source: str, start_url: Annotated[str, typer.Option(help="Target website for replay")]):
    """Analyze a local video or a public media URL; all generated steps need review."""
    store = Store()
    task_id, _ = store.create(source)
    typer.echo(f"Task: {task_id}")
    try:
        analyze_task(store, task_id, source, start_url)
    except Exception as exc:
        typer.echo(f"Analysis failed: {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(f"Review: replaylab visualize {task_id}")


@app.command()
def compile(task_id: str, start_url: Annotated[str, typer.Option()]):
    """Compile saved frames without re-downloading or re-extracting the video."""
    store = Store()
    path = store.task(task_id)
    manifest = json.loads((path / "frames.json").read_text())
    store.save(task_id, compile_video(path, manifest, start_url))
    store.status(task_id, status="needs_review", error=None)
    typer.echo(f"Review: replaylab visualize {task_id}")


@app.command()
def import_workflow(path: Path):
    """Import an existing workflow for review; this does not perform video recognition."""
    workflow = Workflow.model_validate_json(path.read_text())
    for step in workflow.steps:
        step.status = "needs_review"
    store = Store()
    task_id, _ = store.create(str(path.resolve()))
    store.save(task_id, workflow)
    store.status(task_id, status="needs_review", evidence_available=False)
    typer.echo(task_id)


@app.command()
def approve(task_id: str, yes: Annotated[bool, typer.Option("--yes", "-y")] = False):
    """Approve the current workflow after reviewing its JSON or workbench evidence."""
    store = Store()
    workflow = store.workflow(task_id)
    if workflow.uncertainties:
        raise typer.BadParameter("Resolve uncertainties in workflow.json before approval")
    if not yes:
        typer.echo(workflow.model_dump_json(indent=2))
        typer.confirm(
            "I reviewed the workflow, preconditions and sensitive actions. Approve?", abort=True
        )
    for step in workflow.steps:
        step.status = "approved"
    store.save(task_id, workflow)
    store.status(task_id, status="approved")
    typer.echo("Approved. Execution is a separate command.")


def print_report(report: dict, output: Path):
    typer.echo(json.dumps(report, ensure_ascii=False, indent=2))
    typer.echo(f"Report: {output / 'report.json'}")
    if report["status"] != "passed":
        raise typer.Exit(2 if report["status"] == "paused" else 1)


@app.command()
def execute(
    task_id: str,
    params_file: Path | None = None,
    confirm_sensitive: bool = False,
    headed: bool = False,
):
    """Run a reviewed workflow in a fresh browser, stopping on the first failure."""
    store = Store()
    output = store.task(task_id) / "execution"
    report = run(
        store.workflow(task_id), output, read_parameters(params_file), confirm_sensitive, headed
    )
    store.status(task_id, status=report["status"])
    print_report(report, output)


@app.command()
def run_workflow(
    path: Path,
    output: Path = Path(".replaylab/run"),
    params_file: Path | None = None,
    confirm_sensitive: bool = False,
    headed: bool = False,
):
    """Run an exported workflow with the installed ReplayLab runtime."""
    workflow = Workflow.model_validate_json(path.read_text())
    print_report(
        run(workflow, output, read_parameters(params_file), confirm_sensitive, headed), output
    )


@app.command("export-skill")
def export(task_id: str, output: Path):
    """Export only a workflow whose current version passed execution."""
    typer.echo(str(export_skill(Store().task(task_id), output)))


@app.command()
def visualize(task_id: str):
    """Open the workbench; start `replaylab serve` separately."""
    Store().task(task_id)
    webbrowser.open(f"http://127.0.0.1:8765/#task={task_id}")


@app.command()
def serve(port: int = 8765):
    """Serve the API and built workbench on loopback only."""
    import uvicorn

    from .api import create_app

    store = Store()
    store.token()
    typer.echo(f"Workbench: http://127.0.0.1:{port}")
    typer.echo(f"Local API token file: {store.root / 'token'}")
    uvicorn.run(create_app(store), host="127.0.0.1", port=port)


if __name__ == "__main__":
    app()
