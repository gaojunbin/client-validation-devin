"""`client-validation-devin doctor`: everything a run needs, checked in order, with the fix for each failure."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from . import gitops
from .api import DevinClient
from .config import CONFIG_RELATIVE_PATH, Config, load_config
from .credentials import load_credentials
from .delivery import scratch_ref
from .envcmd import environment_gap, missing_secrets
from .errors import EXIT_BLOCKED, EXIT_OK, DevinApiError, QaError

PROBE_PLATFORM = "client-validation-devin-probe-unknown-platform"


class Checks:
    def __init__(self) -> None:
        self.failed = 0

    def ok(self, label: str, detail: str = "") -> None:
        print(f"ok    {label}{': ' + detail if detail else ''}")

    def warn(self, label: str, detail: str) -> None:
        print(f"warn  {label}: {detail}")

    def fail(self, label: str, detail: str) -> None:
        self.failed += 1
        print(f"FAIL  {label}: {detail}")


def repo_visible(repositories: list[dict[str, Any]], slug: str) -> bool:
    target = slug.lower()
    for item in repositories:
        for value in item.values():
            if isinstance(value, str) and (value.lower() == target or value.lower().rstrip("/").endswith("/" + target)):
                return True
    return False


def probe_platforms(client: DevinClient) -> str:
    """Unknown platform labels are rejected with a 400 that lists the valid ones."""
    body = {"prompt": "client-validation-devin platform probe. Reply ok and stop.",
            "title": "client-validation-devin probe",
            "platform": PROBE_PLATFORM}
    try:
        created = client.create_session(body)
    except DevinApiError as exc:
        if exc.status == 400:
            return exc.detail
        raise
    client.terminate_session(created["session_id"], archive=True)
    return ""


def _git(checks: Checks, cwd: Path) -> Path | None:
    try:
        root = gitops.repo_root(cwd)
    except QaError as exc:
        checks.fail("git repository", str(exc))
        return None
    branch = gitops.current_branch(root) or "(detached HEAD)"
    dirty = " with uncommitted changes" if gitops.is_dirty(root) else ""
    checks.ok("git repository", f"{root} on {branch}{dirty}")
    return root


def _config(checks: Checks, root: Path) -> Config | None:
    try:
        config = load_config(root)
    except QaError as exc:
        checks.fail("config", f"{exc}")
        return None
    checks.ok("config", f"{root / CONFIG_RELATIVE_PATH}: {len(config.platforms)} platform(s), "
                        f"{len(config.scenarios)} scenario(s)")
    if not (root / ".devin" / "blueprint.yaml").is_file():
        checks.warn("blueprint", ".devin/blueprint.yaml missing; sessions will install toolchains at run time (slow)")
    return config


def _delivery(checks: Checks, config: Config) -> str:
    try:
        slug = config.repo or gitops.repo_slug(gitops.remote_url(config.root, config.remote))
    except QaError as exc:
        checks.fail("repository slug", str(exc))
        return ""
    checks.ok("repository slug", slug)
    if config.delivery_mode == "push":
        ref = scratch_ref(config, gitops.current_branch(config.root), gitops.head_sha(config.root))
        ok, output = gitops.push_dry_run(config.root, config.remote, ref)
        if ok:
            checks.ok("push access", f"can push {ref} to {config.remote}")
        else:
            hint = ""
            if gitops.remote_url(config.root, config.remote).startswith("https://"):
                hint = (f" (the remote uses HTTPS without push credentials; if GitHub access on this machine is SSH, "
                        f"run: git remote set-url {config.remote} git@github.com:{slug}.git)")
            checks.fail("push access", f"git push --dry-run failed: {output[-300:]}{hint}")
    return slug


def _api(checks: Checks, config: Config | None, slug: str, probe: bool) -> None:
    try:
        credentials = load_credentials()
    except QaError as exc:
        checks.fail("credentials", str(exc))
        return
    checks.ok("credentials", f"{credentials.masked_key()} from {credentials.source}")
    client = DevinClient(credentials, max_attempts=2)
    try:
        me = client.self_info()
        checks.ok("api", f"principal {me.get('principal_type', '?')}")
        checks.ok("organization", client.org_id)
    except QaError as exc:
        checks.fail("api", str(exc))
        return
    if slug and config and config.delivery_mode == "push":
        try:
            if repo_visible(client.list_repositories(), slug):
                checks.ok("repository access", f"Devin can see {slug}")
            else:
                checks.fail("repository access", f"{slug} is not connected to Devin; connect the Git host in "
                                                 "app.devin.ai > Settings > Integrations and grant this repo")
        except QaError as exc:
            checks.warn("repository access", f"could not list repositories: {exc}")
    if config:
        _org_setup(checks, client, config, slug)
    if probe:
        try:
            detail = probe_platforms(client)
        except QaError as exc:
            checks.warn("platforms", f"probe failed: {exc}")
            return
        checks.ok("platforms", detail or "probe created a session (terminated); labels unknown")
        if config and detail:
            for name, spec in config.platforms.items():
                if spec.vm.lower() not in detail.lower() and spec.vm not in ("linux", "default"):
                    checks.fail(f"platform {name}", f"vm '{spec.vm}' is not offered to this organization "
                                                    "(Windows: ask Cognition for access or use a Windows Outpost)")


def _org_setup(checks: Checks, client: DevinClient, config: Config, slug: str) -> None:
    """What lives in the Devin organization, not the repo: the built environment and the named secrets."""
    gap = environment_gap(client, config.root, slug, require_blueprint=config.delivery_mode == "push") if slug else ""
    if gap:
        checks.warn("environment", gap)
    note = missing_secrets(client, config.devin_secret_names)
    if note:
        checks.warn("secrets", note)


def run_doctor(cwd: Path, probe: bool) -> int:
    checks = Checks()
    if sys.version_info < (3, 11):
        checks.fail("python", f"{sys.version.split()[0]} found; 3.11+ required")
    else:
        checks.ok("python", sys.version.split()[0])
    root = _git(checks, cwd)
    config = _config(checks, root) if root else None
    slug = _delivery(checks, config) if config else ""
    _api(checks, config, slug, probe)
    print("doctor: all checks passed" if not checks.failed else f"doctor: {checks.failed} check(s) failed")
    return EXIT_OK if not checks.failed else EXIT_BLOCKED
