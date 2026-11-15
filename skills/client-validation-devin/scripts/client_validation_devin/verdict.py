"""The CLI's own verdict: Devin's verdict is advisory, this policy is authoritative."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

from .errors import EXIT_BLOCKED, EXIT_FAIL, EXIT_HUMAN, EXIT_OK

STUCK_APPEARANCES = 3  # seen in the round that found it plus two fix rounds


@dataclass
class PlatformVerdict:
    platform: str
    verdict: str
    reasons: list[str] = field(default_factory=list)
    gating: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def fingerprint(platform: str, issue: dict[str, Any]) -> str:
    key = "|".join([platform, issue.get("category", ""), " ".join(_words(issue.get("title", ""))),
                    " ".join(_words(issue.get("screen", "") or issue.get("scenario", "")))])
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


def _phase_status(report: dict[str, Any]) -> dict[str, str]:
    phases = report.get("phases") or {}
    return {name: (phases.get(name) or {}).get("status", "") for name in
            ("checkout", "build", "tests", "launch", "scenarios", "layout")}


def _blocked(report: dict[str, Any], status: dict[str, str]) -> bool:
    return (report.get("verdict") == "blocked" or status["checkout"] in ("fail", "blocked")
            or status["build"] == "blocked")


def _explained(scenario: dict[str, Any], issues: list[dict[str, Any]]) -> bool:
    """A failed scenario is explained when an issue names it or its notes cite an issue id."""
    notes = scenario.get("notes") or ""
    return any(i.get("scenario") == scenario.get("id") or (i.get("id") and i["id"] in notes) for i in issues)


def _fail_reasons(report: dict[str, Any], status: dict[str, str], issues: list[dict[str, Any]],
                  gating: list[dict[str, Any]], fail_on: frozenset[str]) -> list[str]:
    reasons = []
    if status["build"] == "fail":
        reasons.append("build failed")
    if status["tests"] == "fail" or (report.get("tests") or {}).get("failed"):
        reasons.append("automated tests failed")
    if gating:
        reasons.append(f"{len(gating)} issue(s) at gating severity ({', '.join(sorted(fail_on))})")
    reasons += [f"scenario {s.get('id')} failed and no issue explains it (read its notes)"
                for s in report.get("scenarios", []) if s.get("status") == "fail" and not _explained(s, issues)]
    if report.get("verdict") == "fail" and not issues and not reasons:
        reasons.append("validator reported fail but listed no issues; read its transcript")
    return reasons


def judge(platform: str, state: str, note: str, report: dict[str, Any] | None,
          fail_on: frozenset[str]) -> PlatformVerdict:
    if state == "infra":
        return PlatformVerdict(platform, "blocked", [f"infrastructure: {note}"])
    if report is None:
        return PlatformVerdict(platform, "blocked", [note or "no final report for this round"])
    issues = [i for i in report.get("issues", []) if isinstance(i, dict)]
    gating = [i for i in issues if i.get("severity") in fail_on]
    warnings = [i for i in issues if i.get("severity") not in fail_on]
    status = _phase_status(report)
    if _blocked(report, status):
        reason = report.get("blocked_reason") or "validator could not complete checkout or the build environment"
        return PlatformVerdict(platform, "blocked", [reason], gating, warnings)
    reasons = _fail_reasons(report, status, issues, gating, fail_on)
    if reasons:
        return PlatformVerdict(platform, "fail", reasons, gating, warnings)
    notes = ["validator said fail; only issues below the gate were reported"] if report.get("verdict") == "fail" else []
    return PlatformVerdict(platform, "pass", notes, gating, warnings)


def update_streaks(previous: list[dict[str, Any]], platform: str, issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Count consecutive rounds each issue appeared in, matching by id or fingerprint."""
    streaks = []
    for issue in issues:
        fp = fingerprint(platform, issue)
        match = next((p for p in previous if p["id"] == issue.get("id") or p["fingerprint"] == fp), None)
        streaks.append({
            "id": issue.get("id", ""),
            "fingerprint": fp,
            "title": issue.get("title", ""),
            "severity": issue.get("severity", ""),
            "count": (match["count"] + 1) if match else 1,
        })
    return streaks


def stuck(streaks: list[dict[str, Any]], fail_on: frozenset[str]) -> list[dict[str, Any]]:
    return [s for s in streaks if s["count"] >= STUCK_APPEARANCES and s["severity"] in fail_on]


PATH_TOKEN = re.compile(r"[\w.-]+(?:/[\w.-]+)+\.\w{1,6}")


def _files(issue: dict[str, Any]) -> set[str]:
    return set(PATH_TOKEN.findall(issue.get("suspected_location") or ""))


def same_root(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Same category plus one strong signal: same scenario/screen, a shared source file, or similar titles."""
    if a.get("category") != b.get("category"):
        return False
    place = a.get("scenario") or a.get("screen")
    if place and place == (b.get("scenario") or b.get("screen")):
        return True
    if _files(a) & _files(b):
        return True
    words, other = set(_words(a.get("title", ""))), set(_words(b.get("title", "")))
    return bool(words and other) and len(words & other) / len(words | other) >= 0.5


def shared_root_causes(issues: dict[str, list[dict[str, Any]]]) -> list[list[tuple[str, dict[str, Any]]]]:
    """Group issues (any severity) from different platforms that look like the same defect."""
    groups: list[list[tuple[str, dict[str, Any]]]] = []
    for platform, items in issues.items():
        for issue in items:
            for group in groups:
                if platform not in {p for p, _ in group} and same_root(issue, group[0][1]):
                    group.append((platform, issue))
                    break
            else:
                groups.append([(platform, issue)])
    return [g for g in groups if len(g) > 1]


def exit_code(verdicts: dict[str, PlatformVerdict], needs_human: bool) -> int:
    if needs_human:
        return EXIT_HUMAN
    values = {v.verdict for v in verdicts.values()}
    if "fail" in values:
        return EXIT_FAIL
    if "blocked" in values:
        return EXIT_BLOCKED
    return EXIT_OK
