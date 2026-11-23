"""Create or reuse one Devin session per platform for a round."""

from __future__ import annotations

import os
import time
from typing import Any

from .api import DevinClient
from .config import Config
from .delivery import Delivery
from .errors import ConfigError, DevinApiError
from .prompt import report_schema
from .waiter import usage_limit

LINUX_LABELS = ("linux", "default")
DEAD_STATUSES = ("exit", "error")


def session_secrets(config: Config) -> list[dict[str, Any]]:
    missing = [name for name in config.secrets_from_env if not os.environ.get(name)]
    if missing:
        raise ConfigError(f"[secrets].from_env: environment variable(s) not set: {', '.join(missing)}")
    return [{"key": name, "value": os.environ[name], "sensitive": True} for name in config.secrets_from_env]


def session_body(config: Config, platform: str, vm: str, prompt: str, delivery: Delivery,
                 run_id: str) -> dict[str, Any]:
    body: dict[str, Any] = {
        "prompt": prompt,
        "title": f"client-validation-devin {config.product_name} {platform} {delivery.commit[:7]}",
        "platform": vm,
        "tags": ["client-validation-devin", f"client-validation-devin-{platform}",
                 f"client-validation-devin-run-{run_id}"],
        "structured_output_schema": report_schema(),
        "structured_output_required": True,
        "memory_enabled": False,
    }
    if delivery.mode == "push":
        body["repos"] = [delivery.repo]
    elif delivery.bundle_url:
        body["attachment_urls"] = [delivery.bundle_url]
    if config.run.devin_mode:
        body["devin_mode"] = config.run.devin_mode
    if config.run.max_acu_limit:
        body["max_acu_limit"] = config.run.max_acu_limit
    secrets = session_secrets(config)
    if secrets:
        body["session_secrets"] = secrets
    return body


def create_session(client: DevinClient, body: dict[str, Any]) -> dict[str, Any]:
    try:
        return client.create_session(body)
    except DevinApiError as exc:
        if exc.status != 400 or "platform" not in exc.detail.lower():
            raise
        vm = body.get("platform")
        if vm in LINUX_LABELS:
            alternative = LINUX_LABELS[1 - LINUX_LABELS.index(vm)]
            return client.create_session({**body, "platform": alternative})
        raise DevinApiError(exc.method, exc.path, exc.status, exc.title,
                            f"{exc.detail} (set [platforms.*].vm to one of the labels above; Windows needs "
                            "access from Cognition or a Windows Outpost)") from None


def reusable(client: DevinClient, session_id: str) -> bool:
    if not session_id:
        return False
    try:
        session = client.get_session(session_id)
    except DevinApiError as exc:
        if exc.not_visible:  # deleted, or the key now belongs to another organization: start a new session
            return False
        raise
    return session.get("status") not in DEAD_STATUSES and not session.get("is_archived")


def new_platform_state(vm: str, round_token: str) -> dict[str, Any]:
    return {
        "state": "pending",
        "note": "",
        "vm": vm,
        "session_id": "",
        "url": "",
        "round_token": round_token,
        "reused": False,
        "started_at": 0.0,
        "deadline": 0.0,
        "grace_deadline": 0.0,
        "last_action_at": 0.0,
        "auto_replies": 0,
        "nudged_at": 0.0,
        "last_status": "",
        "last_status_detail": "",
        "acus": 0.0,
        "quota_limited": False,
    }


def start_platform(
    client: DevinClient,
    state: dict[str, Any],
    *,
    body: dict[str, Any],
    round_message: str,
    reuse_session_id: str,
    timeout_minutes: int,
    now: float | None = None,
) -> None:
    """Start (or retry starting) one platform. Leaves the state 'pending' on rate limits."""
    now = time.time() if now is None else now
    try:
        if reuse_session_id and reusable(client, reuse_session_id):
            response = client.send_message(reuse_session_id, round_message)
            state.update(session_id=reuse_session_id, reused=True, url=response.get("url", ""))
        else:
            created = create_session(client, body)
            state.update(session_id=created["session_id"], url=created.get("url", ""), reused=False)
    except DevinApiError as exc:
        if exc.status == 429:
            state.update(state="pending", note="rate limited or at the concurrent-session cap; retrying while waiting")
            return
        limit = usage_limit(f"{exc.title} {exc.detail}") if exc.status in (402, 403) else ""
        if limit:
            state.update(state="infra", note=f"Devin refused to start the session: usage limit ({limit})",
                         quota_limited=True)
            return
        state.update(state="infra", note=str(exc))
        return
    # last_action_at=now: give the session a cooldown before any nudge while it boots or resumes.
    state.update(state="running", note="", started_at=now, last_action_at=now, deadline=now + timeout_minutes * 60)
