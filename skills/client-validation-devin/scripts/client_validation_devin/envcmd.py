"""`client-validation-devin env`: push `.devin/blueprint.yaml` to Devin and build the per-platform snapshots."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .api import DevinClient
from .buildlogs import BATCH_WINDOW
from .errors import EXIT_BLOCKED, EXIT_OK, EXIT_RUNNING, ConfigError, InfraError, QaError
from .waiter import log

BLUEPRINT_PATH = Path(".devin") / "blueprint.yaml"
BUILD_DONE = {"succeeded", "success", "partial", "failed", "cancelled"}
BUILD_OK = {"succeeded", "success", "partial"}
Json = dict[str, Any]


def _matching(blueprints: list[dict[str, Any]], slug: str) -> dict[str, Any] | None:
    for item in blueprints:
        name = str(item.get("repo_name") or "")
        if name.lower() == slug.lower() or name.lower().rstrip("/").endswith("/" + slug.lower()):
            return item
    return None


def apply_blueprint(client: DevinClient, root: Path, slug: str, *, switch_from_git: bool) -> str:
    path = root / BLUEPRINT_PATH
    if not path.is_file():
        raise ConfigError(f"{path} not found; create it from a client-validation-devin-setup blueprint template first")
    contents = path.read_text(encoding="utf-8")
    existing = _matching(client.list_blueprints(), slug)
    if existing is None:
        client.create_blueprint(slug, contents)
        print(f"created repository blueprint for {slug} (database mode)")
    else:
        if existing.get("source") == "git" and not switch_from_git:
            raise QaError(f"the blueprint for {slug} is git-backed: merge {BLUEPRINT_PATH} to the default branch "
                          "and run `client-validation-devin env sync`, or pass --switch-from-git to manage it "
                          "from this checkout")
        client.update_blueprint(existing["blueprint_id"], contents)
        print(f"updated repository blueprint {existing['blueprint_id']} for {slug}")
    return trigger(client)


def environment_gap(client: DevinClient, root: Path, slug: str, *, require_blueprint: bool = True) -> str:
    """Why this repository's sessions would start without its environment; '' when it is built (or unknown).

    Without require_blueprint (bundle delivery: Devin may not be able to pull the repository, so it may have no
    blueprint) only an existing blueprint's builds are checked."""
    if not (root / BLUEPRINT_PATH).is_file():
        return ""  # the environment is not managed from this checkout
    try:
        blueprint = _matching(client.list_blueprints(), slug)
        builds = client.list_builds() if blueprint else []
    except InfraError as exc:  # e.g. a key that may not read the environment settings: the validators will tell
        log(f"note: could not check the Devin environment ({exc})")
        return ""
    if blueprint is None and not require_blueprint:
        return ""
    return _build_gap(client.org_id, slug, blueprint, builds)


def missing_secrets(client: DevinClient, names: tuple[str, ...]) -> str:
    """A note naming the declared Devin secrets this organization lacks; '' when all exist or it cannot tell."""
    if not names:
        return ""
    try:
        keys = {str(s.get("key") or "") for s in client.list_secrets()}
    except InfraError as exc:  # listing needs the ManageOrgSecrets permission
        log(f"note: could not list Devin secrets ({exc})")
        return ""
    missing = [n for n in names if n not in keys]
    if not missing:
        return ""
    return (f"Devin organization {client.org_id} has no organization or personal secret {', '.join(missing)} "
            "(named in .devin/qa.toml [secrets]); unless they are repository secrets, validators cannot sign in. "
            "A human adds them at app.devin.ai > Secrets.")


def _created(build: Json) -> int:
    return build.get("created_at") or 0


def batches(builds: list[Json]) -> list[list[Json]]:
    """Builds grouped by trigger, newest first: one trigger creates one build per VM platform, finishing apart."""
    groups: list[list[Json]] = []
    for build in sorted(builds, key=_created, reverse=True):
        if groups and _created(groups[-1][0]) - _created(build) <= BATCH_WINDOW:
            groups[-1].append(build)
        else:
            groups.append([build])
    return groups


def _ready(batch: list[Json]) -> bool:
    statuses = [b.get("status") for b in batch]
    return all(s in BUILD_DONE for s in statuses) and any(s in BUILD_OK for s in statuses)


def _build_gap(org_id: str, slug: str, blueprint: Json | None, builds: list[Json]) -> str:
    if blueprint is None:
        return (f"Devin organization {org_id} has no environment for {slug} (a new account or organization?). "
                "Next: `client-validation-devin env apply --wait`, then start the round again.")
    since = _created(blueprint)
    recent = batches([b for b in builds if _created(b) >= since])
    if any(_ready(batch) for batch in recent):
        return ""
    active = next((b for batch in recent for b in batch if b.get("status") not in BUILD_DONE), None)
    if active:
        return (f"Devin is still building the first environment for {slug}. Next: `client-validation-devin env "
                f"status --build {active.get('build_id')} --wait`, then start the round again.")
    return (f"Devin organization {org_id} has no successful environment build for {slug}. Next: "
            "`client-validation-devin env apply --wait` (fix .devin/blueprint.yaml if it fails), then start the "
            "round again.")


def sync_blueprint(client: DevinClient, slug: str) -> str:
    client.sync_blueprint(slug)
    print(f"synced .devin/blueprint.yaml from the default branch of {slug}")
    return trigger(client)


def trigger(client: DevinClient) -> str:
    build = client.trigger_build()
    build_id = build.get("build_id", "")
    print(f"snapshot build {build_id} {build.get('status', '')}".rstrip())
    return build_id


def _batch_of(client: DevinClient, build_id: str) -> list[Json]:
    """The builds of the trigger that created build_id."""
    for batch in batches(client.list_builds()):
        if any(b.get("build_id") == build_id for b in batch):
            return batch
    return [client.get_build(build_id)]


def _statuses(batch: list[Json], seen: dict[str, str], fallback_id: str) -> list[str]:
    """Each build's status; prints the ones that changed since the last poll."""
    statuses = []
    for build in batch:
        name, status = str(build.get("build_id") or fallback_id), str(build.get("status", ""))
        if seen.get(name) != status:
            print(f"build {name}: {status}")
            seen[name] = status
        statuses.append(status)
    return statuses


def wait_build(client: DevinClient, build_id: str, timeout_seconds: float, poll_seconds: float = 30.0) -> int:
    """Wait for every build of build_id's trigger (one per VM platform); OK only when all of them succeeded."""
    started = time.time()
    seen: dict[str, str] = {}
    while True:
        statuses = _statuses(_batch_of(client, build_id), seen, build_id)
        if all(s in BUILD_DONE for s in statuses):
            if all(s in BUILD_OK for s in statuses):
                return EXIT_OK
            print("A snapshot build failed: read the summary below (or `client-validation-devin env logs`), fix the "
                  "failing repository's .devin/blueprint.yaml, and apply again.")
            return EXIT_BLOCKED
        if time.time() - started >= timeout_seconds:
            print(f"Still building. Next: `client-validation-devin env status --build {build_id} --wait`")
            return EXIT_RUNNING
        time.sleep(poll_seconds)
