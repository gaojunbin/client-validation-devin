"""Shared fixtures: import path, a throwaway product repo with a bare remote, and a fake clock."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "skills" / "client-validation-devin" / "scripts"
sys.path.insert(0, str(SCRIPTS))

CONFIG = """
schema = 1
[product]
name = "Acme Notes"
summary = "Note-taking app."
repo = "acme/notes"
[delivery]
mode = "{mode}"
[run]
default_platforms = {platforms}
poll_seconds = 5
timeout_minutes = 20
max_rounds = {max_rounds}
reuse_sessions = true
[platforms.ios]
vm = "macos"
build = "flutter build ios --simulator"
app_id = "com.acme.notes"
devices = ["iPhone 17", "iPhone SE (3rd generation)"]
[platforms.android]
vm = "linux"
build = "flutter build apk --debug"
[platforms.macos]
vm = "macos"
build = "flutter build macos"
window_sizes = ["1280x800"]
[[scenarios]]
id = "create-note"
title = "Create a note"
steps = "1. Tap New note."
expect = "The note appears."
[[scenarios]]
id = "settings"
title = "Settings"
priority = "p1"
paths = ["lib/settings/**"]
steps = "1. Open settings."
expect = "Settings open."
"""


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class ProductRepo:
    """A product repository on branch feature-x with origin pointing at a local bare repo."""

    def __init__(self, mode: str = "push", platforms: str = '["ios", "android", "macos"]', max_rounds: int = 5):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.remote = base / "remote.git"
        self.path = base / "product"
        self.state = base / "state"
        git(base, "init", "--bare", "-b", "main", str(self.remote))
        self.path.mkdir()
        git(self.path, "init", "-b", "main")
        git(self.path, "config", "user.email", "test@example.com")
        git(self.path, "config", "user.name", "Test")
        (self.path / "README.md").write_text("product\n")
        (self.path / ".devin").mkdir()
        (self.path / ".devin" / "qa.toml").write_text(
            CONFIG.format(mode=mode, platforms=platforms, max_rounds=max_rounds))
        git(self.path, "add", ".")
        git(self.path, "commit", "-m", "init")
        git(self.path, "remote", "add", "origin", str(self.remote))
        git(self.path, "push", "-u", "origin", "main")
        git(self.path, "checkout", "-b", "feature-x")
        self.commit_file("lib/editor/editor.dart", "v1")

    def commit_file(self, relative: str, content: str) -> str:
        target = self.path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        git(self.path, "add", ".")
        git(self.path, "commit", "-m", f"change {relative}")
        return git(self.path, "rev-parse", "HEAD")

    def env(self, api_base: str) -> dict[str, str]:
        return {
            "DEVIN_API_KEY": "cog_testkey123456",
            "DEVIN_ORG_ID": "org-test",
            "DEVIN_API_BASE": api_base,
            "CLIENT_VALIDATION_DEVIN_HOME": str(self.state),
            "CLIENT_VALIDATION_DEVIN_ENV_FILE": str(Path(self.tmp.name) / "no-such-env"),
        }

    def cleanup(self) -> None:
        self.tmp.cleanup()


class FakeClock:
    def __init__(self) -> None:
        self.now = 1_900_000_000.0

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def clean_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if not k.startswith("DEVIN")}
