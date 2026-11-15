"""`client-validation-devin env`: push `.devin/blueprint.yaml` to Devin and build the per-platform snapshots."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .api import DevinClient
from .errors import EXIT_BLOCKED, EXIT_OK, EXIT_RUNNING, ConfigError, QaError

BLUEPRINT_PATH = Path(".devin") / "blueprint.yaml"
BUILD_DONE = {"succeeded", "success", "partial", "failed", "cancelled"}
BUILD_OK = {"succeeded", "success", "partial"}


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


def sync_blueprint(client: DevinClient, slug: str) -> str:
    client.sync_blueprint(slug)
    print(f"synced .devin/blueprint.yaml from the default branch of {slug}")
    return trigger(client)


def trigger(client: DevinClient) -> str:
    build = client.trigger_build()
    build_id = build.get("build_id", "")
    print(f"snapshot build {build_id} {build.get('status', '')}".rstrip())
    return build_id


def wait_build(client: DevinClient, build_id: str, timeout_seconds: float, poll_seconds: float = 30.0) -> int:
    started = time.time()
    last = ""
    while True:
        build = client.get_build(build_id)
        status = str(build.get("status", ""))
        if status != last:
            print(f"build {build_id}: {status}")
            last = status
        if status in BUILD_DONE:
            if status in BUILD_OK:
                return EXIT_OK
            print("Build failed: open app.devin.ai > Settings > Environment > Snapshots for the logs, fix "
                  ".devin/blueprint.yaml, and apply again.")
            return EXIT_BLOCKED
        if time.time() - started >= timeout_seconds:
            print(f"Still building. Next: `client-validation-devin env status --build {build_id} --wait`")
            return EXIT_RUNNING
        time.sleep(poll_seconds)
