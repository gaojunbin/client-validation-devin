"""Turn a finished round into verdicts, ledger updates and report.json / report.md."""

from __future__ import annotations

from typing import Any

from .api import DevinClient
from .collect import collect_platform
from .config import Config
from .errors import EXIT_BLOCKED, EXIT_FAIL, EXIT_HUMAN, EXIT_OK
from .render import render_markdown
from .state import Ledger, Run, read_json, write_json
from .verdict import PlatformVerdict, exit_code, judge, shared_root_causes, stuck, update_streaks

ISSUE_FIELDS = ("id", "severity", "category", "title", "scenario", "screen", "device")


def _compact(issue: dict[str, Any]) -> dict[str, Any]:
    return {k: issue.get(k, "") for k in ISSUE_FIELDS}


def _with_paths(issue: dict[str, Any], evidence: dict[str, str]) -> dict[str, Any]:
    names = issue.get("evidence") or []
    return {**issue, "evidence_paths": [evidence.get(n, f"(not downloaded) {n}") for n in names]}


def _seen_attachments(ledger: Ledger, name: str, session_id: str) -> set[str]:
    previous = ledger.platform(name)
    return set(previous.get("seen_attachment_ids", [])) if previous.get("session_id") == session_id else set()


def _update_ledger(ledger: Ledger, run: Run, name: str, verdict: PlatformVerdict, report: dict[str, Any] | None,
                   fail_on: frozenset[str], attachment_ids: list[str]) -> list[dict[str, Any]]:
    previous = ledger.platform(name)
    state = run.platforms[name]
    entry = {
        "commit": run.data["commit"],
        "verdict": verdict.verdict,
        "run_id": run.run_id,
        "session_id": state.get("session_id", ""),
        "url": state.get("url", ""),
        "seen_attachment_ids": attachment_ids,
        "open_issues": previous.get("open_issues", []),
        "streaks": previous.get("streaks", []),
    }
    if report is not None and verdict.verdict != "blocked":
        issues = [i for i in report.get("issues", []) if isinstance(i, dict)]
        entry["open_issues"] = [_compact(i) for i in issues]
        entry["streaks"] = update_streaks(previous.get("streaks", []), name, issues)
    ledger.set_platform(name, entry)
    return stuck(entry["streaks"], fail_on)


def green_on(ledger: Ledger, platforms: tuple[str, ...], commit: str) -> bool:
    return all(ledger.platform(p).get("verdict") == "pass" and ledger.platform(p).get("commit") == commit
               for p in platforms)


def _next_step(code: int, config: Config, ledger: Ledger, commit: str, human_reasons: list[str],
               verdicts: dict[str, PlatformVerdict]) -> str:
    if code == EXIT_HUMAN:
        return "STOP and escalate to the human: " + "; ".join(human_reasons)
    if code == EXIT_FAIL:
        failing = "; ".join(f"{name}: {', '.join(v.reasons)}" for name, v in verdicts.items() if v.verdict == "fail")
        return (f"Fix what failed ({failing}). Each issue below carries its location and a suggested fix; fix shared "
                "root causes once. Then commit and run `client-validation-devin run --rerun`.")
    if code == EXIT_BLOCKED:
        return ("Resolve the blocked reasons (environment, blueprint, spec, Devin access or quota) before touching "
                "product code; then run `client-validation-devin run --rerun`.")
    stale = [p for p in config.run.default_platforms
             if not (ledger.platform(p).get("verdict") == "pass" and ledger.platform(p).get("commit") == commit)]
    if stale:
        return f"Run `client-validation-devin run --rerun` for the regression pass on HEAD ({', '.join(stale)})."
    return "All default platforms passed on HEAD. Run `client-validation-devin release` (release gate) or report READY."


def _platform_summary(run: Run, name: str, verdict: PlatformVerdict, collected: dict[str, Any]) -> dict[str, Any]:
    state = run.platforms[name]
    report = collected["report"] or {}
    return {
        "verdict": verdict.verdict,
        "reasons": verdict.reasons,
        "commit": run.data["commit"],
        "run_id": run.run_id,
        "session_url": state.get("url", ""),
        "usage": state.get("acus", 0),
        "summary": report.get("summary", ""),
        "phases": report.get("phases", {}),
        "tests": report.get("tests", {}),
        "gating": [_with_paths(i, collected["evidence"]) for i in verdict.gating],
        "warnings": [_with_paths(i, collected["evidence"]) for i in verdict.warnings],
        "fixed_issue_ids": report.get("fixed_issue_ids", []),
        "spec_feedback": report.get("spec_feedback", []),
        "scenarios": [_with_paths(s, collected["evidence"]) for s in report.get("scenarios", [])
                      if isinstance(s, dict)],
        "not_downloaded": collected["not_downloaded"],
        "missing_evidence": collected["missing_evidence"],
        "errors": collected["errors"],
        "evidence_counts": collected["evidence_counts"],
        "evidence_index": str(run.platform_dir(name) / "evidence.md") if collected["evidence"] else "",
        "folder": str(run.platform_dir(name)),
    }


def root_cause_groups(issues: dict[str, list[dict[str, Any]]]) -> list[list[dict[str, Any]]]:
    return [[{"platform": p, "id": i.get("id"), "title": i.get("title"), "severity": i.get("severity")}
             for p, i in group] for group in shared_root_causes(issues)]


def branch_summary(config: Config, base, head: str) -> dict[str, Any] | None:
    """The latest result of every platform on this branch, merged into one report (runs may have been split)."""
    ledger = Ledger(base)
    platforms: dict[str, Any] = {}
    run_ids: list[str] = []
    origin = {"repo": "", "branch": ""}
    for name, entry in sorted(ledger.data["platforms"].items()):
        data = read_json(base / "runs" / entry.get("run_id", "") / "report.json")
        if not data or name not in data.get("platforms", {}):
            continue
        platforms[name] = {"commit": data["commit"], "run_id": data["run_id"], **data["platforms"][name]}
        run_ids.append(data["run_id"])
        origin = {"repo": data.get("repo", ""), "branch": data.get("branch", "")}
    if not platforms:
        return None
    verdicts = {p: v["verdict"] for p, v in platforms.items()}
    overall = "fail" if "fail" in verdicts.values() else "blocked" if "blocked" in verdicts.values() else "pass"
    stale = [p for p, v in platforms.items() if v["commit"] != head]
    missing = [p for p in config.run.default_platforms if p not in platforms]
    next_step = ("Fix the failing platforms' issues, commit, then run `client-validation-devin run --rerun`."
                 if overall != "pass" else
                 f"Run `client-validation-devin run --rerun` (stale or missing: {', '.join(stale + missing)})."
                 if stale or missing else "All default platforms passed on HEAD: `client-validation-devin release`.")
    return {
        "run_id": "latest per platform: " + ", ".join(dict.fromkeys(run_ids)),
        "round": ledger.data.get("round_counter", 0),
        "product": config.product_name,
        "repo": origin["repo"],
        "branch": origin["branch"],
        "commit": head,
        "exit_code": {"pass": EXIT_OK, "fail": EXIT_FAIL, "blocked": EXIT_BLOCKED}[overall],
        "overall": overall,
        "platforms": platforms,
        "needs_human": [],
        "shared_root_causes": root_cause_groups({p: v["gating"] + v["warnings"] for p, v in platforms.items()}),
        "next": next_step,
    }


def _human_reasons(config: Config, run: Run, ledger: Ledger, stuck_items: list[dict[str, Any]]) -> list[str]:
    reasons = [f"{s['platform']} {s['id'] or s['fingerprint']} '{s['title']}' survived {s['count'] - 1} fix rounds"
               for s in stuck_items]
    if ledger.rounds_since_green >= config.run.max_rounds:
        reasons.append(f"{ledger.rounds_since_green} rounds without a green HEAD "
                       f"(max_rounds={config.run.max_rounds})")
    limited = [n for n, s in run.platforms.items()
               if s["state"] == "infra" and s.get("note", "").startswith("session suspended:")]
    if limited:
        reasons.append(f"Devin usage limits suspended {', '.join(limited)} (wait for quota or add credits)")
    return reasons


def finalize(client: DevinClient, config: Config, run: Run, ledger: Ledger) -> tuple[int, dict[str, Any]]:
    verdicts: dict[str, PlatformVerdict] = {}
    platforms: dict[str, Any] = {}
    stuck_items: list[dict[str, Any]] = []
    for name, state in run.platforms.items():
        seen = _seen_attachments(ledger, name, state.get("session_id", ""))
        collected = collect_platform(client, run.platform_dir(name), state,
                                     download_videos=config.run.download_videos, seen_ids=seen)
        verdict = judge(name, state["state"], state.get("note", ""), collected["report"], config.run.fail_on)
        verdicts[name] = verdict
        stuck_items += [{"platform": name, **s} for s in _update_ledger(
            ledger, run, name, verdict, collected["report"], config.run.fail_on, collected["attachment_ids"])]
        platforms[name] = _platform_summary(run, name, verdict, collected)

    commit = run.data["commit"]
    ledger.rounds_since_green += 1
    if green_on(ledger, config.run.default_platforms, commit):
        ledger.rounds_since_green = 0
        ledger.data["green_commit"] = commit
    human_reasons = _human_reasons(config, run, ledger, stuck_items)
    code = exit_code(verdicts, bool(human_reasons))
    ledger.save()

    summary = {
        "run_id": run.run_id,
        "round": run.data["round"],
        "product": config.product_name,
        "repo": run.data["repo"],
        "branch": run.data["branch"],
        "commit": commit,
        "exit_code": code,
        "overall": {EXIT_OK: "pass", EXIT_FAIL: "fail", EXIT_BLOCKED: "blocked", EXIT_HUMAN: "needs_human"}[code],
        "platforms": platforms,
        "needs_human": human_reasons,
        "shared_root_causes": root_cause_groups({p: v.gating + v.warnings for p, v in verdicts.items()}),
        "next": _next_step(code, config, ledger, commit, human_reasons, verdicts),
    }
    write_json(run.dir / "report.json", summary)
    (run.dir / "report.md").write_text(render_markdown(summary), encoding="utf-8")
    run.data["finalized"] = True
    run.data["exit_code"] = code
    run.save()
    return code, summary
