"""Run records and the per-branch ledger under /tmp/client-validation-devin (or $CLIENT_VALIDATION_DEVIN_HOME)."""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from .errors import QaError
from .gitops import safe_name

try:
    import fcntl
except ImportError:  # Windows has no flock; rounds on one branch are then expected to finish one at a time
    fcntl = None

TERMINAL_STATES = ("done", "blocked", "infra")


@contextlib.contextmanager
def locked(base: Path) -> Iterator[None]:
    """Serialize ledger read-modify-write between concurrent runs of the same branch."""
    base.mkdir(parents=True, exist_ok=True)
    with open(base / ".lock", "w", encoding="utf-8") as handle:
        if fcntl is not None:
            fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle, fcntl.LOCK_UN)


def home() -> Path:
    """Run state root. Created private (0700): reports, transcripts and screenshots may hold app data."""
    root = Path(os.environ.get("CLIENT_VALIDATION_DEVIN_HOME") or "/tmp/client-validation-devin")
    if not root.exists():
        root.mkdir(mode=0o700, parents=True)
    return root


def branch_dir(repo: str, branch: str) -> Path:
    return home() / safe_name(repo.replace("/", "__")) / safe_name(branch or "detached")


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(tmp, path)


def read_json(path: Path, default: Any = None) -> Any:
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


class Run:
    """One validation round: run.json plus one artifact folder per platform."""

    def __init__(self, base: Path, data: dict[str, Any]):
        self.base = base
        self.data = data

    @property
    def run_id(self) -> str:
        return self.data["run_id"]

    @property
    def dir(self) -> Path:
        return self.base / "runs" / self.run_id

    @property
    def platforms(self) -> dict[str, dict[str, Any]]:
        return self.data["platforms"]

    def platform_dir(self, platform: str) -> Path:
        return self.dir / platform

    def save(self) -> None:
        write_json(self.dir / "run.json", self.data)

    def mark_latest(self) -> None:
        """Only a newly started run becomes `latest`; waiters saving older runs never move the pointer."""
        (self.base / "latest").write_text(self.run_id + "\n", encoding="utf-8")

    def all_terminal(self) -> bool:
        return all(p["state"] in TERMINAL_STATES for p in self.platforms.values())


def load_run(base: Path, run_id: str | None = None) -> Run:
    if not run_id:
        latest = base / "latest"
        if not latest.is_file():
            raise QaError(f"no runs recorded under {base}; start one with `client-validation-devin run`")
        run_id = latest.read_text(encoding="utf-8").strip()
    data = read_json(base / "runs" / run_id / "run.json")
    if data is None:
        raise QaError(f"run {run_id} not found under {base}")
    return Run(base, data)


class Ledger:
    """Cross-round memory for one branch: last verdict per platform and issue streaks."""

    def __init__(self, base: Path):
        self.path = base / "ledger.json"
        self.data: dict[str, Any] = read_json(self.path, {"rounds_since_green": 0, "platforms": {}})

    def save(self) -> None:
        write_json(self.path, self.data)

    def platform(self, name: str) -> dict[str, Any]:
        return self.data["platforms"].get(name, {})

    def set_platform(self, name: str, entry: dict[str, Any]) -> None:
        self.data["platforms"][name] = entry

    @property
    def rounds_since_green(self) -> int:
        return int(self.data.get("rounds_since_green", 0))

    @rounds_since_green.setter
    def rounds_since_green(self, value: int) -> None:
        self.data["rounds_since_green"] = value
