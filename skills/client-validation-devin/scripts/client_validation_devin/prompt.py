"""Render the validator prompt from the protocol template, platform guide and project spec."""

from __future__ import annotations

import fnmatch
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import Config, Scenario
from .errors import ConfigError

ASSETS = Path(__file__).resolve().parents[2] / "assets"
PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")
SIZE_LABEL = {"ios": "devices", "android": "devices", "web": "viewports"}


@dataclass
class JobContext:
    run_id: str
    round: int
    round_token: str
    platform: str
    vm: str
    repo: str
    commit: str
    delivery_text: str
    checkout_steps: str
    budget_minutes: int
    focus: str = ""
    diff_stat: str = ""
    changed_files: list[str] | None = None
    previous_issues: list[dict[str, Any]] = field(default_factory=list)


def report_schema() -> dict[str, Any]:
    return json.loads((ASSETS / "report.schema.json").read_text(encoding="utf-8"))


def _asset(relative: str) -> str:
    path = ASSETS / relative
    if not path.is_file():
        raise ConfigError(f"missing skill asset {path}; reinstall the client-validation-devin skill")
    return path.read_text(encoding="utf-8").strip()


def select_scenarios(
    config: Config, platform: str, changed: list[str] | None, only: list[str] | None = None
) -> list[Scenario]:
    applicable = [s for s in config.scenarios if s.applies_to(platform)]
    if only:
        known = {s.id for s in config.scenarios}
        unknown = [i for i in only if i not in known]
        if unknown:
            raise ConfigError(f"unknown scenario id(s): {', '.join(unknown)}")
        return [s for s in applicable if s.id in only]

    def relevant(s: Scenario) -> bool:
        if s.priority == "p0" or changed is None or not s.paths:
            return True
        return any(fnmatch.fnmatch(path, pattern) for path in changed for pattern in s.paths)

    return [s for s in applicable if relevant(s)]


def _bullet(label: str, value: str) -> str:
    return f"- {label}: `{value}`" if value else ""


def project_spec(config: Config, platform: str, scenarios: list[Scenario]) -> str:
    spec = config.platforms[platform]
    layout = config.layout
    sizes = spec.devices or spec.window_sizes
    lines = [
        f"**Product:** {config.product_name}: {config.product_summary}",
        "",
        "**Commands** (run from the repository root):",
        *filter(None, [
            _bullet("setup", spec.setup),
            _bullet("build", spec.build),
            _bullet("test", spec.test),
            _bullet("launch", spec.launch),
            _bullet("built artifact", spec.artifact),
            _bullet("app id", spec.app_id),
        ]),
        "",
        "**Layout matrix:**",
        f"- {SIZE_LABEL.get(platform, 'window sizes')}: {', '.join(sizes) if sizes else 'platform default'}",
        f"- themes: {', '.join(spec.themes or layout.themes)}; locales: {', '.join(spec.locales or layout.locales)}; "
        f"text scale: {', '.join(spec.text_scale or layout.text_scale)}",
    ]
    if layout.checks:
        lines.append(f"- checks: {' '.join(layout.checks.split())}")
    if config.devin_secret_names or config.secrets_from_env:
        names = ", ".join((*config.devin_secret_names, *config.secrets_from_env))
        lines += ["", f"**Credentials:** environment variables {names}. Never print their values."]
    if spec.notes:
        lines += ["", f"**Notes:** {spec.notes}"]
    lines += ["", f"**Scenarios** ({len(scenarios)}, run all in order):"]
    for s in scenarios:
        lines += ["", f"#### {s.id}: {s.title} ({s.priority})", "Steps:", s.steps, "Expected:", s.expect]
    if not scenarios:
        lines.append("None defined: run the launch smoke test and explore the main screens.")
    return "\n".join(lines)


def focus_text(job: JobContext) -> str:
    parts = [job.focus if job.focus else
             "No specific change was named for this round: skip the `change` scenario and validate the app as it is."]
    if job.changed_files is None:
        parts.append("Changed files: unknown (no base branch found); cover every scenario.")
    elif job.diff_stat:
        parts += ["Changed files against the default branch:", "```", job.diff_stat, "```"]
    else:
        parts.append("No file changes against the default branch.")
    return "\n".join(parts)


def previous_text(job: JobContext) -> str:
    if not job.previous_issues:
        return "None: this is the first round for this platform."
    lines = [
        "Verify these issues first. Put the ids of fixed ones in `fixed_issue_ids`; report still-present ones "
        "again with the same id and `status_vs_previous: still_present`.",
    ]
    for issue in job.previous_issues:
        where = issue.get("scenario") or issue.get("screen") or ""
        lines.append(f"- {issue.get('id')} [{issue.get('severity')}/{issue.get('category')}] {issue.get('title')}"
                     + (f" ({where})" if where else ""))
    return "\n".join(lines)


def render_prompt(config: Config, job: JobContext, scenarios: list[Scenario]) -> str:
    values = {
        "product_name": config.product_name,
        "platform": job.platform,
        "run_id": job.run_id,
        "round": str(job.round),
        "round_token": job.round_token,
        "repo": job.repo,
        "commit": job.commit,
        "delivery": job.delivery_text,
        "vm": job.vm,
        "budget_minutes": str(job.budget_minutes),
        "checkout_steps": job.checkout_steps,
        "previous_round_instruction": (
            "Start with the issues under 'Previous round' and re-verify each one." if job.previous_issues else ""
        ),
        "video_instruction": (
            "- Record one screen video of the p0 scenario walkthrough and attach it."
            if config.run.record_video else "- Do not record videos."
        ),
        "platform_guide": _asset(f"platforms/{job.platform}.md"),
        "project_spec": project_spec(config, job.platform, scenarios),
        "focus": focus_text(job),
        "previous_issues": previous_text(job),
    }

    def substitute(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            raise ConfigError(f"runner-protocol.md uses unknown placeholder {{{{{key}}}}}")
        return values[key]

    return PLACEHOLDER.sub(substitute, _asset("runner-protocol.md")) + "\n"


def round_message(prompt: str, job: JobContext) -> str:
    return (
        f"NEW ROUND {job.round} (round token `{job.round_token}`). The dispatcher pushed a new commit. "
        "Discard conclusions from earlier rounds except as listed under 'Previous round', redo the whole "
        "procedure below for this commit, and finish with a new final structured output.\n\n" + prompt
    )
