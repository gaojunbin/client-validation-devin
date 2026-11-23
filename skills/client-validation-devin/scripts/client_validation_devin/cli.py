"""Command-line entry point. Exit codes: 0 pass, 1 fail, 2 blocked, 3 running, 4 usage, 5 needs a human."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

from . import __version__, buildlogs, gitops
from .account import available, login
from .api import DevinClient
from .archives import unpack
from .collect import evidence_index
from .config import CONFIG_RELATIVE_PATH, Config, load_config
from .credentials import load_credentials
from .delivery import scratch_ref
from .doctor import run_doctor
from .envcmd import apply_blueprint, sync_blueprint, wait_build
from .errors import EXIT_BLOCKED, EXIT_OK, EXIT_RUNNING, EXIT_USAGE, DevinApiError, NeedsHumanError, QaError
from .prompt import ASSETS
from .render import render_markdown
from .report import branch_summary, green_on
from .runner import resolve_repo, start_round, wait_run
from .state import Ledger, branch_dir, load_run, read_json

DEFAULT_WAIT = 540


def _config(args: argparse.Namespace) -> Config:
    root = gitops.repo_root(Path(args.cwd).resolve())
    return load_config(root, Path(args.config).resolve() if args.config else None)


def _client() -> DevinClient:
    return DevinClient(load_credentials())


def _base(config: Config) -> Path:
    return branch_dir(resolve_repo(config), gitops.current_branch(config.root))


def cmd_init(args: argparse.Namespace) -> int:
    root = gitops.repo_root(Path(args.cwd).resolve())
    target = root / CONFIG_RELATIVE_PATH
    if target.is_symlink():
        raise QaError(f"{target} is a symlink; edit it in place instead of re-initialising")
    if target.exists() and not args.force:
        raise QaError(f"{target} already exists (use --force to overwrite)")
    text = (ASSETS / "qa.example.toml").read_text(encoding="utf-8")
    text = text.replace('name = "Acme Notes"', f'name = "{root.name}"', 1)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    print(f"wrote {target}; replace the example product, commands, devices and scenarios with this project's")
    return EXIT_OK


def cmd_doctor(args: argparse.Namespace) -> int:
    return run_doctor(Path(args.cwd).resolve(), args.probe_platforms)


def cmd_login(args: argparse.Namespace) -> int:
    return login(key_from_stdin=args.key_stdin, org_id=args.org or "", verify=not args.no_verify)


def cmd_available(args: argparse.Namespace) -> int:
    return available(Path(args.cwd).resolve(), online=args.online)


def cmd_run(args: argparse.Namespace) -> int:
    config = _config(args)
    client = None if args.dry_run else _client()
    run = start_round(
        config, client,
        requested=_split(args.platforms), rerun=args.rerun, focus=args.focus or "",
        only_scenarios=_split(args.scenarios) or None, allow_dirty=args.allow_dirty,
        force_round=args.force_round, fresh=args.fresh, dry_run=args.dry_run,
    )
    if run is None:
        return EXIT_OK
    print(f"Run {run.run_id} (round {run.data['round']}) on {run.data['commit'][:12]}")
    for name, state in run.platforms.items():
        print(f"  {name}: {state['state']} {state['session_id']} {state['url']} {state['note']}".rstrip())
    if args.wait or run.all_terminal():  # nothing started (e.g. every create failed): finalize now
        return wait_run(config, client, run, args.timeout if args.wait else 0)
    print(f"Next: `client-validation-devin wait --timeout {DEFAULT_WAIT}` (repeat while it exits 3)")
    return 3


def cmd_wait(args: argparse.Namespace) -> int:
    config = _config(args)
    return wait_run(config, _client(), load_run(_base(config), args.run), args.timeout)


def cmd_status(args: argparse.Namespace) -> int:
    config = _config(args)
    run = load_run(_base(config), args.run)
    if args.json:
        print(json.dumps(run.data, indent=2))
        return EXIT_OK
    print(f"Run {run.run_id} round {run.data['round']} commit {run.data['commit'][:12]} "
          f"{'finished' if run.data.get('finalized') else 'in progress'}")
    for name, state in run.platforms.items():
        print(f"  {name:8} {state['state']:8} {state['last_status'] or '-'}/{state['last_status_detail'] or '-'} "
              f"usage={state['acus']} {state['url']} {state['note']}".rstrip())
    return EXIT_OK


def cmd_report(args: argparse.Namespace) -> int:
    config = _config(args)
    base = _base(config)
    if args.branch:
        summary = branch_summary(config, base, gitops.head_sha(config.root))
        if summary is None:
            raise QaError("no finished run on this branch yet")
        target = base / "branch-report.md"
    else:
        run = load_run(base, args.run)
        summary = read_json(run.dir / "report.json")
        if summary is None:
            raise QaError(f"run {run.run_id} has no report yet; run `client-validation-devin wait`")
        target = run.dir / "report.md"
    markdown = render_markdown(summary)  # re-rendered so the file always uses the current layout
    target.write_text(markdown, encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False) if args.json else markdown)
    return int(summary.get("exit_code", EXIT_OK))


def cmd_fetch(args: argparse.Namespace) -> int:
    """Download a file the collector skipped (video, archive); archives are unpacked next to it."""
    config = _config(args)
    run = load_run(_base(config), args.run)
    state = run.platforms.get(args.platform) or {}
    if not state.get("session_id"):
        raise QaError(f"no session for {args.platform} in run {run.run_id}")
    client = _client()
    matches = [a for a in client.list_attachments(state["session_id"]) if a.get("name") == args.name]
    if not matches:
        raise QaError(f"{args.name} is not attached to the {args.platform} session")
    dest = run.platform_dir(args.platform) / "attachments" / gitops.safe_name(args.name)
    client.download_attachment(matches[-1], dest)
    print(dest)
    if zipfile.is_zipfile(dest):
        folder, count = unpack(dest)
        print(f"unpacked {count} file(s) into {folder}")
        platform_dir = run.platform_dir(args.platform)
        files = {p.name: str(p) for p in (platform_dir / "attachments").rglob("*") if p.is_file()}
        evidence_index(platform_dir, files)
        print(f"evidence index updated: {platform_dir / 'evidence.md'}")
    return EXIT_OK


def cmd_message(args: argparse.Namespace) -> int:
    config = _config(args)
    run = load_run(_base(config), args.run)
    state = run.platforms.get(args.platform)
    if not state or not state.get("session_id"):
        raise QaError(f"no session for {args.platform} in run {run.run_id}")
    _client().send_message(state["session_id"], args.text)
    print(f"sent to {args.platform} ({state['session_id']})")
    return EXIT_OK


def _terminate(client: DevinClient, session_id: str, *, archive: bool) -> bool:
    """Terminate a session; False when this key cannot see it (deleted, or started under another organization)."""
    try:
        client.terminate_session(session_id, archive=archive)
    except DevinApiError as exc:
        if not exc.not_visible:
            raise
        print(f"session {session_id} is not visible to the current Devin key (HTTP {exc.status}); skipped")
        return False
    return True


def cmd_stop(args: argparse.Namespace) -> int:
    config = _config(args)
    client = _client()
    run = load_run(_base(config), args.run)
    for name, state in run.platforms.items():
        if state["state"] in ("running", "pending"):
            if state.get("session_id"):
                _terminate(client, state["session_id"], archive=args.archive)
            state.update(state="blocked", note="stopped by client-validation-devin stop")
            print(f"stopped {name}")
    run.save()
    return EXIT_OK


def cmd_release(args: argparse.Namespace) -> int:
    config = _config(args)
    head = gitops.head_sha(config.root)
    if gitops.is_dirty(config.root):
        raise QaError("uncommitted changes: the release gate only covers committed, validated code")
    ledger = Ledger(_base(config))
    if not green_on(ledger, config.run.default_platforms, head):
        missing = [p for p in config.run.default_platforms
                   if not (ledger.platform(p).get("verdict") == "pass" and ledger.platform(p).get("commit") == head)]
        print(f"NOT READY: not green on {head[:12]}: {', '.join(missing)}. "
              "Next: `client-validation-devin run --rerun`.")
        return EXIT_BLOCKED
    if not config.release_command:
        print(f"READY: every default platform passed on {head[:12]}. No [release].command configured.")
        return EXIT_OK
    if not (config.release_auto or args.yes):
        print(f"READY: every default platform passed on {head[:12]}. [release].auto is false: ask the human, "
              "then run `client-validation-devin release --yes`.")
        return EXIT_OK
    print(f"releasing {head[:12]}: {' '.join(config.release_command)}")
    try:
        return subprocess.run(list(config.release_command), cwd=config.root).returncode
    except OSError as exc:
        raise QaError(f"[release].command could not start: {exc}") from None


def cmd_cleanup(args: argparse.Namespace) -> int:
    config = _config(args)
    base = _base(config)
    if args.remote and config.delivery_mode == "push":
        ref = scratch_ref(config, gitops.current_branch(config.root), gitops.head_sha(config.root))
        gitops.delete_remote_ref(config.root, config.remote, ref)
        print(f"deleted {config.remote}/{ref}")
    if args.sessions:
        client = _client()
        for name, entry in Ledger(base).data["platforms"].items():
            if entry.get("session_id") and _terminate(client, entry["session_id"], archive=True):
                print(f"terminated and archived {name} session {entry['session_id']}")
    if args.local and base.is_dir():
        shutil.rmtree(base)
        print(f"removed {base}")
    return EXIT_OK


def cmd_env(args: argparse.Namespace) -> int:
    config = _config(args)
    client = _client()
    slug = resolve_repo(config)
    if args.action == "logs":
        buildlogs.report(client, [args.build] if args.build else buildlogs.batch_build_ids(client))
        return EXIT_OK
    if args.action == "apply":
        build_id = apply_blueprint(client, config.root, slug, switch_from_git=args.switch_from_git)
    elif args.action == "sync":
        build_id = sync_blueprint(client, slug)
    else:
        if not args.build:
            raise QaError("env status needs --build <id>")
        build_id = args.build
    if args.wait and build_id:
        code = wait_build(client, build_id, args.timeout)
        if code != EXIT_RUNNING:  # one trigger builds every platform: summarize the whole batch
            try:
                buildlogs.report(client, buildlogs.batch_build_ids(client))
            except QaError as exc:
                print(f"could not summarize the build logs ({exc}); run `client-validation-devin env logs` later")
        return code
    if build_id:
        status = client.get_build(build_id).get("status", "")
        print(f"build {build_id}: {status}")
    return EXIT_OK


def _split(value: str | None) -> list[str]:
    return [v.strip() for v in (value or "").split(",") if v.strip()]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="client-validation-devin", description=__doc__)
    parser.add_argument("--version", action="version", version=f"client-validation-devin {__version__}")
    parser.add_argument("-C", "--cwd", default=".", help="directory inside the product repository")
    parser.add_argument("--config", help=f"config path (default: <repo>/{CONFIG_RELATIVE_PATH})")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="write .devin/qa.toml from the example")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("login", help="store your Devin API key (asked with hidden input) after checking it")
    p.add_argument("--org", help="organization id; detected from the key when omitted")
    p.add_argument("--key-stdin", action="store_true", help="read the key from standard input (scripts)")
    p.add_argument("--no-verify", action="store_true", help="save without calling the Devin API")
    p.set_defaults(func=cmd_login)

    p = sub.add_parser("available", help="exit 0 if this machine can validate this repository on Devin")
    p.add_argument("--online", action="store_true", help="also check that the API accepts the key")
    p.set_defaults(func=cmd_available)

    p = sub.add_parser("doctor", help="check git, config, credentials, API, repo access and platforms")
    p.add_argument("--probe-platforms", action="store_true", help="ask the API which VM platforms exist")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("run", help="start a validation round (returns immediately unless --wait)")
    p.add_argument("--platforms", help="comma-separated subset, e.g. ios,android")
    p.add_argument("--rerun", action="store_true", help="only platforms not green yet, then a regression pass on HEAD")
    p.add_argument("--focus", help="one or two sentences on what changed and what to look at")
    p.add_argument("--scenarios", help="comma-separated scenario ids to run instead of the automatic selection")
    p.add_argument("--fresh", action="store_true", help="new sessions instead of reusing the previous ones")
    p.add_argument("--allow-dirty", action="store_true", help="validate HEAD even with uncommitted changes")
    p.add_argument("--force-round", action="store_true", help="human override of max_rounds")
    p.add_argument("--dry-run", action="store_true", help="render prompts only; no push, no API calls")
    p.add_argument("--wait", action="store_true", help="block until done (or --timeout)")
    p.add_argument("--timeout", type=int, default=DEFAULT_WAIT)
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("wait", help="poll the latest run; exits 3 while still running")
    p.add_argument("--run")
    p.add_argument("--timeout", type=int, default=DEFAULT_WAIT)
    p.set_defaults(func=cmd_wait)

    p = sub.add_parser("status", help="show the latest run without changing anything")
    p.add_argument("--run")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("report", help="print report.md (or --json) of the latest run")
    p.add_argument("--run")
    p.add_argument("--json", action="store_true")
    p.add_argument("--branch", action="store_true",
                   help="merge the latest result of every platform on this branch into one report")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("fetch", help="download a skipped attachment (video, archive) and unpack archives")
    p.add_argument("platform")
    p.add_argument("name", help="attachment name as listed under 'Not downloaded' in the report")
    p.add_argument("--run")
    p.set_defaults(func=cmd_fetch)

    p = sub.add_parser("message", help="send a message to one platform's session")
    p.add_argument("platform")
    p.add_argument("text")
    p.add_argument("--run")
    p.set_defaults(func=cmd_message)

    p = sub.add_parser("stop", help="terminate the latest run's active sessions")
    p.add_argument("--run")
    p.add_argument("--archive", action="store_true")
    p.set_defaults(func=cmd_stop)

    p = sub.add_parser("release", help="release gate: run [release].command only on a green HEAD")
    p.add_argument("--yes", action="store_true", help="the human approved this release")
    p.set_defaults(func=cmd_release)

    p = sub.add_parser("cleanup", help="remove the scratch ref, sessions and/or local state for this branch")
    p.add_argument("--remote", action="store_true")
    p.add_argument("--sessions", action="store_true")
    p.add_argument("--local", action="store_true")
    p.set_defaults(func=cmd_cleanup)

    p = sub.add_parser("env", help="manage the Devin environment from .devin/blueprint.yaml")
    p.add_argument("action", choices=("apply", "sync", "status", "logs"),
                   help="logs: warnings and build results of the latest builds (or --build)")
    p.add_argument("--build", help="build id for status or logs")
    p.add_argument("--switch-from-git", action="store_true")
    p.add_argument("--wait", action="store_true")
    p.add_argument("--timeout", type=int, default=DEFAULT_WAIT)
    p.set_defaults(func=cmd_env)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except NeedsHumanError as exc:
        print(f"client-validation-devin: needs a human: {exc}", file=sys.stderr)
        return exc.exit_code
    except QaError as exc:
        print(f"client-validation-devin: {exc}", file=sys.stderr)
        return exc.exit_code
    except KeyboardInterrupt:
        return EXIT_USAGE
