"""Get the exact commit onto Devin's VM: push a tool-owned ref, or upload a git bundle."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from . import gitops
from .api import DevinClient
from .config import Config

BUNDLE_WARN_BYTES = 200 * 1024 * 1024


@dataclass(frozen=True)
class Delivery:
    mode: str
    repo: str
    commit: str
    ref: str = ""
    bundle_name: str = ""
    bundle_url: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Delivery":
        return cls(**data)

    def describe(self) -> str:
        if self.mode == "push":
            return f"pushed to branch `{self.ref}` of `{self.repo}`"
        return f"git bundle `{self.bundle_name}` attached to this session"

    def checkout_steps(self) -> str:
        name = self.repo.rsplit("/", 1)[-1]
        if self.mode == "push":
            return (
                f"1. Go to the clone of `{self.repo}` (normally `~/repos/{name}`). If it is missing, clone it there.\n"
                f"2. `git fetch origin {self.ref}` then `git checkout --force --detach {self.commit}`.\n"
                f"3. If the commit is not found, run `git fetch origin {self.commit}` once and retry the checkout."
            )
        return (
            f"1. Find `{self.bundle_name}` in `~/.files/` (session attachments land there).\n"
            f"2. If `~/repos/{name}` exists: `cd ~/repos/{name} && git fetch ~/.files/{self.bundle_name} "
            f"HEAD:refs/client-validation-devin/validate && git checkout --force --detach {self.commit}`.\n"
            f"3. Otherwise: `git clone ~/.files/{self.bundle_name} ~/repos/{name} && cd ~/repos/{name} && "
            f"git checkout --detach {self.commit}`."
        )


def scratch_ref(config: Config, branch: str, commit: str) -> str:
    return config.scratch_prefix + (branch or f"detached-{commit[:12]}")


def deliver(
    config: Config,
    client: DevinClient | None,
    *,
    repo: str,
    branch: str,
    commit: str,
    work_dir: Path,
    dry_run: bool,
) -> Delivery:
    if config.delivery_mode == "push":
        ref = scratch_ref(config, branch, commit)
        if not dry_run:
            gitops.push_scratch_ref(config.root, config.remote, ref)
        return Delivery(mode="push", repo=repo, commit=commit, ref=ref)

    bundle_name = f"{gitops.safe_name(repo.rsplit('/', 1)[-1])}-{commit[:12]}.bundle"
    bundle_path = gitops.create_bundle(config.root, work_dir / bundle_name)
    if bundle_path.stat().st_size > BUNDLE_WARN_BYTES:
        print(f"warning: {bundle_name} is {bundle_path.stat().st_size >> 20} MB; push mode is faster for large repos")
    url = ""
    if not dry_run and client is not None:
        url = client.upload_attachment(bundle_path).get("url", "")
    return Delivery(mode="bundle", repo=repo, commit=commit, bundle_name=bundle_name, bundle_url=url)
