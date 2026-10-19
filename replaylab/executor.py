"""Interpret approved actions using Playwright. No eval, shell or generated scripts."""

import json
import re
from pathlib import Path
from time import perf_counter

from playwright.sync_api import expect, sync_playwright
from pydantic import TypeAdapter

from .models import Assertion, Target, Workflow, origin
from .store import digest, write_json


class NeedsReview(Exception):
    pass


def resolve_parameters(workflow: Workflow, values: dict[str, str]) -> Workflow:
    data = workflow.model_dump()

    def replace(value):
        if isinstance(value, str):

            def substitute(match):
                key = match.group(1)
                if key not in values:
                    raise NeedsReview(f"Missing parameter: {key}")
                return values[key]

            return re.sub(r"\$\{([a-zA-Z0-9_]+)\}", substitute, value)
        if isinstance(value, list):
            return [replace(item) for item in value]
        if isinstance(value, dict):
            return {key: replace(item) for key, item in value.items()}
        return value

    for field in ("steps", "postconditions"):
        data[field] = replace(data[field])
    return Workflow.model_validate(data)


def locate(page, target: Target):
    if target.strategy == "role":
        return page.get_by_role(target.role, name=target.value, exact=True)
    if target.strategy == "label":
        return page.get_by_label(target.value, exact=True)
    if target.strategy == "placeholder":
        return page.get_by_placeholder(target.value, exact=True)
    return page.get_by_text(target.value, exact=True)


def verify(page, assertion: Assertion):
    if assertion.type == "url":
        expect(page).to_have_url(assertion.expected)
    elif assertion.type == "visible":
        expect(locate(page, assertion.target)).to_be_visible()
    elif assertion.type == "value":
        expect(locate(page, assertion.target)).to_have_value(assertion.expected)
    elif assertion.type == "checked":
        expect(locate(page, assertion.target)).to_be_checked()
    else:
        expect(locate(page, assertion.target)).to_have_text(assertion.expected)


def execute(
    workflow: Workflow,
    output: Path,
    parameters: dict[str, str] | None = None,
    confirm_sensitive: bool = False,
    headed: bool = False,
    expected_checks: list[Assertion] | None = None,
) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    started = perf_counter()
    report = {
        "status": "paused",
        "workflow_digest": digest(workflow),
        "steps": [],
        "independent_checks": [],
    }
    browser = None
    try:
        if workflow.uncertainties:
            raise NeedsReview("Resolve workflow uncertainties before execution")
        if any(step.status != "approved" for step in workflow.steps):
            raise NeedsReview("Review and approve every step before execution")
        if any(step.sensitive for step in workflow.steps) and not confirm_sensitive:
            raise NeedsReview("Sensitive steps require explicit confirmation for this run")
        resolved = resolve_parameters(workflow, parameters or {})
        allowed = set(resolved.allowed_origins)
        for step in resolved.steps:
            if step.action == "navigate" and origin(step.value) not in allowed:
                raise NeedsReview(f"{step.id}: navigation is outside allowed origins")
        report["status"] = "running"
        write_json(output / "report.json", report)
        with sync_playwright() as playwright:
            import os

            executable = os.environ.get("REPLAYLAB_BROWSER_EXECUTABLE")
            browser = playwright.chromium.launch(headless=not headed, executable_path=executable)
            context = browser.new_context(accept_downloads=False, service_workers="block")
            context.set_default_timeout(8000)
            blocked = []

            def guard(route):
                request = route.request
                if request.is_navigation_request():
                    try:
                        if origin(request.url) not in allowed:
                            blocked.append(request.url)
                            return route.abort()
                    except ValueError:
                        blocked.append(request.url)
                        return route.abort()
                return route.continue_()

            context.route("**/*", guard)
            page = context.new_page()
            # v0.1 handles a single page; no silent popup execution.
            page.on("popup", lambda popup: popup.close())
            page.goto(resolved.start_url, wait_until="domcontentloaded")
            for step in resolved.steps:
                entry = {"id": step.id, "status": "running"}
                report["steps"].append(entry)
                write_json(output / "report.json", report)
                stage = perf_counter()
                try:
                    if step.action == "navigate":
                        page.goto(step.value, wait_until="domcontentloaded")
                    else:
                        target = locate(page, step.target)
                        # Playwright strict locators fail rather than picking an ambiguous match.
                        if step.action == "click":
                            target.click()
                        elif step.action == "fill":
                            target.fill(step.value)
                        elif step.action == "select":
                            target.select_option(label=step.value)
                        elif step.action == "check":
                            target.check()
                        elif step.action == "press":
                            target.press(step.value)
                    if blocked:
                        raise NeedsReview("Blocked navigation outside allowed origins")
                    if origin(page.url) not in allowed:
                        raise NeedsReview("Page left the allowed origins")
                    verify(page, step.verification)
                    entry["status"] = "passed"
                except Exception as exc:
                    entry["status"] = "failed"
                    entry["error"] = str(exc)
                    raise
                finally:
                    entry["seconds"] = round(perf_counter() - stage, 3)
                    screenshot = f"{step.id}.png"
                    try:
                        page.screenshot(path=str(output / screenshot))
                        entry["screenshot"] = screenshot
                    except Exception:
                        pass  # Keep the original execution error if the page has already closed.
                    report["seconds"] = round(perf_counter() - started, 3)
                    write_json(output / "report.json", report)
            for assertion in resolved.postconditions:
                verify(page, assertion)
            for index, assertion in enumerate(expected_checks or []):
                check = {"index": index, "status": "failed"}
                report["independent_checks"].append(check)
                verify(page, assertion)
                check["status"] = "passed"
            report["status"] = "passed"
            report["final_url"] = page.url
            browser.close()
            browser = None
    except NeedsReview as exc:
        report.update(status="paused", error=str(exc))
    except Exception as exc:
        report.update(status="failed", error=str(exc))
    finally:
        # Playwright's context manager closes the driver on all exceptional paths.
        report["seconds"] = round(perf_counter() - started, 3)
        write_json(output / "report.json", report)
    return report


def read_parameters(path: Path | None) -> dict[str, str]:
    if path is None:
        return {}
    values = json.loads(path.read_text())
    if not isinstance(values, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in values.items()
    ):
        raise ValueError("Parameters must be a JSON object with string values")
    return values


def read_assertions(path: Path | None) -> list[Assertion]:
    return TypeAdapter(list[Assertion]).validate_json(path.read_text()) if path else []
