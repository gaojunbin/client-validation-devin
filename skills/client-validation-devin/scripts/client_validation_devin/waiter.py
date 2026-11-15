"""Per-platform state machine while a round runs. `decide` is pure; `step` applies its actions."""

from __future__ import annotations

import sys
import time
from typing import Any, Callable

from .api import DevinClient
from .errors import DevinApiError, InfraError

MAX_AUTO_REPLIES = 2
ACTION_COOLDOWN = 180.0
NUDGE_GRACE = 600.0
FINALIZE_GRACE = 600.0
SETTLE_SECONDS = 180.0  # after the final report, let a still-working validator finish attaching evidence
QUOTA_DETAILS = {
    "usage_limit_exceeded", "out_of_credits", "out_of_quota", "no_quota_allocation", "payment_declined",
    "org_usage_limit_exceeded", "user_usage_limit_exceeded", "total_session_limit_exceeded",
    "contract_expired", "error",
}
IDLE_DETAILS = {"inactivity", "user_request", None, ""}

AUTO_REPLY = (
    "No human is available to answer. Decide with the most reasonable assumption and continue. If you truly "
    "cannot proceed, finish now: provide the final structured output with verdict \"blocked\", a blocked_reason, "
    "report_status \"final\" and round_token \"{token}\"."
)
NUDGE = (
    "Your turn ended without the final structured output for round token \"{token}\". Attach your evidence and "
    "provide it now with report_status \"final\", covering what you validated so far."
)
FINALIZE = (
    "Time budget exhausted. Stop testing now, attach your evidence, and provide the final structured output for "
    "round token \"{token}\" (report_status \"final\") within 10 minutes."
)


def has_final_report(state: dict[str, Any], session: dict[str, Any]) -> bool:
    report = session.get("structured_output") or {}
    return (
        isinstance(report, dict)
        and report.get("round_token") == state["round_token"]
        and report.get("report_status") == "final"
    )


def decide(state: dict[str, Any], session: dict[str, Any], now: float) -> tuple[str, str]:
    """Return (action, note). Actions: wait, settle, done, auto_reply, nudge, finalize, terminate, blocked, infra."""
    status = session.get("status")
    detail = session.get("status_detail")
    if has_final_report(state, session):
        seen = state.get("final_seen_at") or now
        if status == "running" and detail == "working" and now - seen < SETTLE_SECONDS:
            return "settle", "final report received; waiting for the validator to finish attaching evidence"
        return "done", ""
    if status == "suspended" and detail in QUOTA_DETAILS:
        return "infra", f"session suspended: {detail}"
    if status == "error":
        return "infra", "session errored"
    if status == "exit":
        return "blocked", "session ended without a final report"
    if state["grace_deadline"]:
        if now > state["grace_deadline"]:
            return "terminate", "no report after the time-budget warning"
        return "wait", ""
    if now > state["deadline"]:
        return "finalize", "time budget exceeded"
    if now - state["last_action_at"] < ACTION_COOLDOWN:
        return "wait", ""
    if status == "running" and detail in ("waiting_for_user", "waiting_for_approval"):
        if state["auto_replies"] < MAX_AUTO_REPLIES:
            return "auto_reply", str(detail)
        return "blocked", (f"still {detail} after {MAX_AUTO_REPLIES} automatic replies "
                           "(approval may be required in the Devin UI)")
    if (status == "running" and detail == "finished") or (status == "suspended" and detail in IDLE_DETAILS):
        if not state["nudged_at"]:
            return "nudge", "turn ended without a final report"
        if now - state["nudged_at"] > NUDGE_GRACE:
            return "blocked", "no final report after a reminder"
    return "wait", ""


def step(client: DevinClient, state: dict[str, Any], now: float) -> str:
    """Poll one running platform and apply the decided action. Returns the action taken."""
    try:
        session = client.get_session(state["session_id"])
    except (DevinApiError, InfraError) as exc:
        state["note"] = f"poll failed: {exc}"
        return "wait"
    state.update(
        last_status=session.get("status", ""),
        last_status_detail=session.get("status_detail") or "",
        acus=session.get("acus_consumed", state["acus"]),
        url=session.get("url") or state["url"],
    )
    action, note = decide(state, session, now)
    if action == "settle":
        state["final_seen_at"] = state.get("final_seen_at") or now
        return "wait"
    token = state["round_token"]
    message = {"auto_reply": AUTO_REPLY, "nudge": NUDGE, "finalize": FINALIZE}.get(action)
    if message:
        try:
            client.send_message(state["session_id"], message.format(token=token))
        except (DevinApiError, InfraError) as exc:
            state["note"] = f"could not message the session: {exc}"
            return "wait"
        state["last_action_at"] = now
        if action == "auto_reply":
            state["auto_replies"] += 1
        elif action == "nudge":
            state["nudged_at"] = now
        else:
            state["grace_deadline"] = now + FINALIZE_GRACE
        state["note"] = note
    elif action == "terminate":
        try:
            client.terminate_session(state["session_id"])
        except (DevinApiError, InfraError):
            pass
        state.update(state="blocked", note=note)
    elif action in ("done", "blocked", "infra"):
        state.update(state=action, note=note)
    return action


def log(line: str) -> None:
    print(line, file=sys.stderr, flush=True)


def poll(
    client: DevinClient,
    platforms: dict[str, dict[str, Any]],
    *,
    timeout_seconds: float,
    poll_seconds: float,
    start_pending: Callable[[], None],
    save: Callable[[], None],
    clock: Callable[[], float] | None = None,
    sleep: Callable[[float], None] | None = None,
) -> bool:
    """Poll until every platform is terminal (True) or the timeout passes (False)."""
    clock = clock or time.time
    sleep = sleep or time.sleep
    started = clock()
    seen: dict[str, tuple[str, str, str]] = {}
    while True:
        start_pending()
        now = clock()
        for name, state in platforms.items():
            if state["state"] == "running":
                action = step(client, state, now)
                if action not in ("wait", "done"):
                    log(f"[{name}] {action}: {state['note']}")
            fingerprint = (state["state"], state["last_status"], state["last_status_detail"])
            if seen.get(name) != fingerprint:
                seen[name] = fingerprint
                log(f"[{name}] {state['state']} ({state['last_status'] or '-'}/{state['last_status_detail'] or '-'}) "
                    f"usage={state['acus']} {state['url']}")
        save()
        if all(s["state"] in ("done", "blocked", "infra") for s in platforms.values()):
            return True
        if clock() - started >= timeout_seconds:
            return False
        sleep(poll_seconds)
