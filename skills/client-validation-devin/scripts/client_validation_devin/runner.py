"""Start a round (platform selection, delivery, prompts, sessions) and wait for it."""

from __future__ import annotations

import secrets
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from . import gitops
from .api import DevinClient
from .config import Config
from .delivery import Delivery, deliver
from .errors import EXIT_RUNNING, ConfigError, GitError, NeedsHumanError
from .prompt import JobContext, render_prompt, round_message, select_scenarios
from .report import finalize
from .sessions import new_platform_state, session_body, start_platform
from .state import Ledger, Run, branch_dir, locked, read_json
from .waiter import log, poll


def resolve_repo(config: Config) -> str:
    return config.repo or gitops.repo_slug(gitops.remote_url(config.root, config.remote))


def select_platforms(config: Config, ledger: Ledger, head: str, requested: list[str],
                     rerun: bool) -> tuple[list[str], str]:
    if requested:
        unknown = [p for p in requested if p not in config.platforms]
        if unknown:
            raise ConfigError(f"no [platforms.*] table for: {', '.join(unknown)}")
        return requested, "requested on the command line"
    defaults = list(config.run.default_platforms)
    if not rerun:
        return defaults, "default platforms"
    not_green = [p for p in defaults if ledger.platform(p).get("verdict") != "pass"]
    if not_green:
        return not_green, "platforms that are not green yet"
    stale = [p for p in defaults if ledger.platform(p).get("commit") != head]
    if stale:
        return stale, "regression pass: these passed on an older commit"
    return [], "every default platform already passed on HEAD"


def _job(config: Config, run: Run, platform: str, delivery: Delivery, ledger: Ledger, *,
         focus: str, diff_stat: str, changed: list[str] | None) -> JobContext:
    return JobContext(
        run_id=run.run_id,
        round=run.data["round"],
        round_token=run.platforms[platform]["round_token"],
        platform=platform,
        vm=config.platforms[platform].vm,
        repo=delivery.repo,
        commit=delivery.commit,
        delivery_text=delivery.describe(),
        checkout_steps=delivery.checkout_steps(),
        budget_minutes=config.run.timeout_minutes,
        focus=focus,
        diff_stat=diff_stat,
        changed_files=changed,
        previous_issues=ledger.platform(platform).get("open_issues", []),
    )


def _start_args(config: Config, run: Run, platform: str) -> tuple[dict[str, Any], str]:
    folder = run.platform_dir(platform)
    prompt = (folder / "prompt.md").read_text(encoding="utf-8")
    state = run.platforms[platform]
    delivery = Delivery.from_dict(run.data["delivery"])
    body = session_body(config, platform, state["vm"], prompt, delivery, run.run_id)
    header = JobContext(run_id=run.run_id, round=run.data["round"], round_token=state["round_token"], platform=platform,
                        vm=state["vm"], repo=delivery.repo, commit=delivery.commit, delivery_text="",
                        checkout_steps="", budget_minutes=0)
    return body, round_message(prompt, header)


def start_pending(config: Config, client: DevinClient, run: Run) -> None:
    """Start queued platforms while fewer than [run].max_parallel sessions of this run are running."""
    running = sum(1 for s in run.platforms.values() if s["state"] == "running")
    slots = max(0, config.run.max_parallel - running)
    pending = [p for p, s in run.platforms.items() if s["state"] == "pending"][:slots]
    if not pending:
        return

    def start(platform: str) -> None:
        body, message = _start_args(config, run, platform)
        state = run.platforms[platform]
        start_platform(client, state, body=body, round_message=message,
                       reuse_session_id=state.get("reuse_session_id", ""),
                       timeout_minutes=config.run.timeout_minutes)
        if state["state"] != "pending":
            log(f"[{platform}] {'reused' if state['reused'] else 'created'} session {state['session_id'] or '-'} "
                f"{state['note']}".rstrip())

    with ThreadPoolExecutor(max_workers=config.run.max_parallel) as pool:
        list(pool.map(start, pending))
    run.save()


def start_round(
    config: Config,
    client: DevinClient | None,
    *,
    requested: list[str],
    rerun: bool,
    focus: str,
    only_scenarios: list[str] | None,
    allow_dirty: bool,
    force_round: bool,
    fresh: bool,
    dry_run: bool,
) -> Run | None:
    root = config.root
    if gitops.is_dirty(root) and not allow_dirty:
        raise GitError("uncommitted changes: commit them first (validation runs on a commit), or pass --allow-dirty "
                       "to validate HEAD without them")
    branch = gitops.current_branch(root)
    commit = gitops.head_sha(root)
    repo = resolve_repo(config)
    base = branch_dir(repo, branch)
    ledger, platforms, why, round_no = _reserve_round(config, base, commit, requested, rerun, force_round, dry_run)
    if rerun and not focus:  # fix rounds keep verifying the change the first round was about
        focus = ledger.data.get("last_focus", "")
    if not platforms:
        print(f"Nothing to run: {why}. Next: `client-validation-devin release`.")
        return None
    log(f"platforms: {', '.join(platforms)} ({why})")

    # Random suffix: two runs started in the same second on the same commit must not share a folder.
    run_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{commit[:7]}-{secrets.token_hex(2)}"
    run = Run(base / "dry-run" if dry_run else base, {
        "run_id": run_id, "round": round_no, "repo": repo, "branch": branch, "commit": commit,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "config": str(config.path),
        "platforms": {}, "delivery": {}, "finalized": False, "focus": focus,
    })
    mb = gitops.merge_base(root, config.remote)
    changed = gitops.changed_files(root, mb) if mb else None
    diff_stat = gitops.diff_stat(root, mb)
    delivery = deliver(config, client, repo=repo, branch=branch, commit=commit, work_dir=run.dir, dry_run=dry_run)
    run.data["delivery"] = delivery.to_dict()

    for platform in platforms:
        state = new_platform_state(config.platforms[platform].vm, f"r{round_no}-{secrets.token_hex(3)}")
        previous = ledger.platform(platform)
        if config.run.reuse_sessions and not fresh:
            state["reuse_session_id"] = previous.get("session_id", "")
        run.platforms[platform] = state
        job = _job(config, run, platform, delivery, ledger, focus=focus, diff_stat=diff_stat, changed=changed)
        scenarios = select_scenarios(config, platform, changed, only_scenarios)
        folder = run.platform_dir(platform)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "prompt.md").write_text(render_prompt(config, job, scenarios), encoding="utf-8")

    if dry_run:
        for platform in platforms:
            print(f"[dry-run] {platform}: prompt at {run.platform_dir(platform) / 'prompt.md'}")
        return None

    if focus:
        with locked(base):
            fresh_ledger = Ledger(base)
            fresh_ledger.data["last_focus"] = focus
            fresh_ledger.save()
    run.save()
    run.mark_latest()
    for other in unfinished_runs(base, exclude=run.run_id):
        log(f"note: run {other} is still in progress; wait on it with `client-validation-devin wait --run {other}`")
    start_pending(config, client, run)
    return run


def _reserve_round(config: Config, base, commit: str, requested: list[str], rerun: bool, force_round: bool,
                   dry_run: bool) -> tuple[Ledger, list[str], str, int]:
    """Pick platforms and claim a round number under the branch lock (concurrent runs may finalize meanwhile)."""
    with locked(base):
        ledger = Ledger(base)
        if ledger.rounds_since_green >= config.run.max_rounds and not force_round:
            raise NeedsHumanError(f"{ledger.rounds_since_green} rounds without a green HEAD on this branch "
                                  f"(max_rounds={config.run.max_rounds}); escalate to the human")
        platforms, why = select_platforms(config, ledger, commit, requested, rerun)
        round_no = int(ledger.data.get("round_counter", 0)) + 1
        if platforms and not dry_run:
            ledger.data["round_counter"] = round_no
            ledger.save()
    return ledger, platforms, why, round_no


def unfinished_runs(base, exclude: str = "") -> list[str]:
    runs_dir = base / "runs"
    if not runs_dir.is_dir():
        return []
    unfinished = []
    for run_file in sorted(runs_dir.glob("*/run.json")):
        data = read_json(run_file, {})
        if data.get("run_id") and data["run_id"] != exclude and not data.get("finalized"):
            unfinished.append(data["run_id"])
    return unfinished


def wait_run(config: Config, client: DevinClient, run: Run, timeout_seconds: float) -> int:
    if run.data.get("finalized"):
        print(f"Run {run.run_id} already finished: {run.dir / 'report.md'}")
        return int(run.data.get("exit_code", 0))
    finished = poll(
        client,
        run.platforms,
        timeout_seconds=timeout_seconds,
        poll_seconds=config.run.poll_seconds,
        start_pending=lambda: start_pending(config, client, run),
        save=run.save,
    )
    if not finished:
        running = [p for p, s in run.platforms.items() if s["state"] in ("running", "pending")]
        print(f"Still running: {', '.join(running)}. "
              f"Next: `client-validation-devin wait --timeout {int(timeout_seconds)}`")
        return EXIT_RUNNING
    with locked(run.base):  # another run of this branch may be finalizing at the same moment
        code, summary = finalize(client, config, run, Ledger(run.base))
    print(f"Report: {run.dir / 'report.md'}")
    print(f"Overall: {summary['overall']} (exit {code})")
    print(f"Next: {summary['next']}")
    return code
