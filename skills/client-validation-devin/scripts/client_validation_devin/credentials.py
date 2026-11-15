"""Devin API credentials: environment first, then a user-level env file. Never the repo."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .errors import ConfigError

DEFAULT_API_BASE = "https://api.devin.ai"
DEFAULT_ENV_FILE = Path.home() / ".config" / "client-validation-devin" / "env"


@dataclass(frozen=True)
class Credentials:
    api_key: str
    org_id: str
    api_base: str
    source: str

    def masked_key(self) -> str:
        return f"{self.api_key[:4]}…{self.api_key[-4:]}" if len(self.api_key) > 10 else "…"


def env_file_path() -> Path:
    override = os.environ.get("CLIENT_VALIDATION_DEVIN_ENV_FILE")
    return Path(override).expanduser() if override else DEFAULT_ENV_FILE


def parse_env_file(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        key, sep, value = line.partition("=")
        if not sep:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def load_credentials() -> Credentials:
    file_values: dict[str, str] = {}
    path = env_file_path()
    if path.is_file():
        file_values = parse_env_file(path.read_text(encoding="utf-8"))

    def pick(name: str) -> tuple[str, str]:
        if os.environ.get(name):
            return os.environ[name].strip(), "environment"
        if file_values.get(name):
            return file_values[name].strip(), str(path)
        return "", ""

    api_key, source = pick("DEVIN_API_KEY")
    if not api_key:
        raise ConfigError(
            "DEVIN_API_KEY is not set. Create a personal access token (cog_...) in "
            f"app.devin.ai > Settings > Devin API, then export it or put it in {path}"
        )
    if not api_key.startswith("cog_"):
        raise ConfigError("DEVIN_API_KEY must be a v3 credential starting with cog_ (legacy apk_ keys do not work)")
    org_id, _ = pick("DEVIN_ORG_ID")
    api_base, _ = pick("DEVIN_API_BASE")
    base = (api_base or DEFAULT_API_BASE).rstrip("/")
    return Credentials(api_key=api_key, org_id=org_id, api_base=base, source=source)
