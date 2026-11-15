"""Markdown rendering of a round summary (report.md). Rendered from report.json, so it can be redone at any time."""

from __future__ import annotations

from typing import Any

SEVERITY_ORDER = ("blocker", "critical", "major", "minor", "cosmetic")
MAX_TEST_FAILURES = 15


def _counts(platform: dict[str, Any]) -> str:
    issues = platform["gating"] + platform["warnings"]
    return "/".join(str(sum(1 for i in issues if i.get("severity") == s)) for s in SEVERITY_ORDER)


def _phases(phases: dict[str, Any]) -> str:
    return " · ".join(f"{name} {(phases.get(name) or {}).get('status', '-')}"
                      for name in ("checkout", "build", "tests", "launch", "scenarios", "layout"))


def _issue(issue: dict[str, Any]) -> list[str]:
    lines = [f"#### {issue.get('id', '?')} [{issue.get('severity')}/{issue.get('category')}] {issue.get('title', '')}"]
    where = ", ".join(filter(None, [issue.get("scenario"), issue.get("screen"), issue.get("device")]))
    if where:
        lines.append(f"- Where: {where}")
    if issue.get("repro_steps"):
        lines.append("- Repro: " + " → ".join(issue["repro_steps"]))
    if issue.get("expected"):
        lines.append(f"- Expected: {issue['expected']}")
    lines.append(f"- Actual: {issue.get('actual', '')}")
    for path in issue.get("evidence_paths", []):
        lines.append(f"- Evidence: {path}")
    if issue.get("suspected_location"):
        lines.append(f"- Suspected location: {issue['suspected_location']}")
    if issue.get("suggested_fix"):
        lines.append(f"- Suggested fix ({issue.get('confidence', 'unrated')} confidence): {issue['suggested_fix']}")
    if issue.get("status_vs_previous"):
        lines.append(f"- Versus previous round: {issue['status_vs_previous']}")
    if issue.get("log_excerpt"):
        lines += ["", "```", issue["log_excerpt"].strip()[:2000], "```"]
    return lines + [""]


def _tests(tests: dict[str, Any]) -> list[str]:
    if not tests:
        return []
    counts = ", ".join(f"{k} {tests[k]}" for k in ("passed", "failed", "skipped") if k in tests)
    lines = [f"Tests: {counts}" if counts else "Tests:"]
    failures = tests.get("failures") or []
    for failure in failures[:MAX_TEST_FAILURES]:
        lines.append(f"- {failure.get('name', '?')}: {failure.get('message', '')}".rstrip(": "))
    if len(failures) > MAX_TEST_FAILURES:
        lines.append(f"- ... {len(failures) - MAX_TEST_FAILURES} more in the platform's report.json")
    return lines


def render_markdown(summary: dict[str, Any]) -> str:
    platforms = summary["platforms"]
    show_usage = any(p.get("usage") for p in platforms.values())
    lines = [
        f"# client-validation-devin report: {summary['product']} @ {summary['commit'][:12]}",
        "",
        f"Run `{summary['run_id']}` · round {summary['round']} · branch `{summary['branch'] or '(detached)'}` · "
        f"overall **{summary['overall'].upper()}** (exit {summary['exit_code']})",
        "",
        f"**Next:** {summary['next']}",
        "",
        "| Platform | Verdict | Issues B/C/M/m/c |" + (" Usage |" if show_usage else "") + " Session |",
        "| - | - | - |" + (" - |" if show_usage else "") + " - |",
    ]
    for name, p in platforms.items():
        usage = f" {p.get('usage')} |" if show_usage else ""
        lines.append(f"| {name} | {p['verdict']} | {_counts(p)} |{usage} {p['session_url']} |")
    if summary["needs_human"]:
        lines += ["", "## Needs a human", *[f"- {r}" for r in summary["needs_human"]]]
    if summary["shared_root_causes"]:
        lines += ["", "## Likely shared root causes (fix once)"]
        for group in summary["shared_root_causes"]:
            lines.append("- " + "; ".join(f"{g['platform']} {g['id']} [{g.get('severity', '?')}] '{g['title']}'"
                                          for g in group))
    for name, p in platforms.items():
        lines += _platform_overview(name, p) + _platform_details(p)
    return "\n".join(lines) + "\n"


def _platform_overview(name: str, p: dict[str, Any]) -> list[str]:
    lines = ["", f"## {name}: {p['verdict'].upper()}", ""]
    if p["summary"]:
        lines += [p["summary"], ""]
    if p.get("commit"):
        lines.append(f"Validated commit {p['commit'][:12]} in run `{p.get('run_id', '?')}`")
    lines.append(f"Phases: {_phases(p['phases'])}")
    lines += [f"- {reason}" for reason in p["reasons"]]
    lines += _tests(p.get("tests") or {})
    failing = [s for s in p["scenarios"] if s.get("status") != "pass"]
    if failing:
        lines.append("Scenarios not passing:")
        for s in failing:
            notes = " ".join((s.get("notes") or "").split())
            lines.append(f"- {s.get('id')} ({s.get('status')}){': ' + notes[:600] if notes else ''}")
            lines += [f"  - Evidence: {path}" for path in (s.get("evidence_paths") or s.get("evidence") or [])[:3]]
    if p["fixed_issue_ids"]:
        lines.append(f"Fixed since the previous round: {', '.join(p['fixed_issue_ids'])}")
    lines.append(f"Artifacts: {p['folder']}")
    counts = p.get("evidence_counts") or {}
    if counts:
        lines.append(f"Evidence ({sum(counts.values())} files, index {p.get('evidence_index')}): "
                     + ", ".join(f"{check} {n}" for check, n in counts.items()))
    return lines


def _platform_details(p: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for title, issues in (("Gating issues", p["gating"]), ("Issues below the gate", p["warnings"])):
        if issues:
            lines += ["", f"### {title}", ""]
            for issue in issues:
                lines += _issue(issue)
    not_downloaded = p.get("not_downloaded", p.get("videos", []))
    sections = (
        ("Spec feedback", p["spec_feedback"]),
        ("Not downloaded (open in a browser signed in to Devin)",
         [f"{v.get('kind', 'video')}: {v['name']}: {v['url']}" for v in not_downloaded]),
    )
    for title, items in sections:
        if items:
            lines += ["", f"### {title}", *[f"- {item}" for item in items]]
    if p["missing_evidence"]:
        lines.append(f"Missing evidence files: {', '.join(p['missing_evidence'])}")
    if p["errors"]:
        lines.append(f"Collection errors: {'; '.join(p['errors'])}")
    return lines
