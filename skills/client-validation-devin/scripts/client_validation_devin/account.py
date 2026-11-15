"""`login` stores the Devin API key in the user-level env file; `available` says whether validation can run here."""

from __future__ import annotations

import getpass
import os
import sys
from pathlib import Path

from .api import DevinClient
from .config import load_config
from .credentials import DEFAULT_API_BASE, Credentials, env_file_path, load_credentials
from .errors import EXIT_BLOCKED, EXIT_OK, QaError
from .gitops import repo_root


def save_env_values(path: Path, values: dict[str, str]) -> None:
    """Set KEY=value lines in place: keeps comments, other keys and a symlinked file (it is written through)."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    pending = {k: v for k, v in values.items() if v}
    for index, line in enumerate(lines):
        key = line.strip().removeprefix("export ").split("=", 1)[0].strip()
        if key in pending and "=" in line and not line.lstrip().startswith("#"):
            lines[index] = f"{key}={pending.pop(key)}"
    lines += [f"{k}={v}" for k, v in pending.items()]
    text = "\n".join(lines) + "\n"
    if path.is_symlink():
        path.write_text(text, encoding="utf-8")
        return
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.chmod(path, 0o600)


def _read_key(from_stdin: bool) -> str:
    if from_stdin:
        return sys.stdin.readline().strip()
    print("Create a personal access token at https://app.devin.ai/settings/devin-api (PATs tab).")
    return getpass.getpass("Devin API key (cog_..., input hidden): ").strip()


def login(*, key_from_stdin: bool, org_id: str, verify: bool) -> int:
    key = _read_key(key_from_stdin)
    if not key.startswith("cog_"):
        raise QaError("that is not a Devin v3 key: it must start with cog_ (legacy apk_ keys do not work)")
    if verify:
        client = DevinClient(Credentials(key, org_id, os.environ.get("DEVIN_API_BASE") or DEFAULT_API_BASE,
                                         "login"), max_attempts=2)
        me = client.self_info()
        org_id = org_id or me.get("org_id") or ""
        if not org_id:
            raise QaError("the key works but has no default organization; rerun with --org <org id> "
                          "(shown at the top of Settings > Devin API)")
        print(f"key accepted: {me.get('principal_type', 'principal')}, organization {org_id}")
    path = env_file_path()
    save_env_values(path, {"DEVIN_API_KEY": key, "DEVIN_ORG_ID": org_id})
    print(f"saved to {path} (readable only by you)")
    if os.environ.get("DEVIN_API_KEY") and os.environ["DEVIN_API_KEY"] != key:
        print("note: DEVIN_API_KEY is also set in your environment and takes precedence over the file")
    return EXIT_OK


def available(cwd: Path, *, online: bool) -> int:
    """Exit 0 when this machine can validate this repository on Devin; otherwise print why and exit 2."""
    reasons = []
    try:
        load_config(repo_root(cwd))
    except QaError as exc:
        reasons.append(f"project not onboarded ({exc})")
    try:
        credentials = load_credentials()
    except QaError as exc:
        reasons.append(f"no Devin credentials ({exc})")
    else:
        if online and not reasons:
            try:
                DevinClient(credentials, max_attempts=2).self_info()
            except QaError as exc:
                reasons.append(f"Devin API not reachable with this key ({exc})")
    if reasons:
        print("unavailable: " + "; ".join(reasons))
        return EXIT_BLOCKED
    print("available: client-validation-devin can validate this repository on Devin")
    return EXIT_OK
