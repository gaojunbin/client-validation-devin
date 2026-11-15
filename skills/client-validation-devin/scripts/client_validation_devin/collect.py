"""Download a finished platform's report, transcript and evidence into the run folder."""

from __future__ import annotations

import datetime as dt
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from .api import DevinClient
from .errors import DevinApiError, InfraError
from .gitops import safe_name
from .state import write_json
from .waiter import has_final_report

VIDEO_SUFFIXES = {".mp4", ".mov", ".webm", ".mkv", ".avi"}
ARCHIVE_SUFFIXES = {".zip", ".tar", ".gz", ".tgz", ".xz", ".7z", ".rar"}
EVIDENCE_NAME = re.compile(r"^r\d+-[a-z]+__(?P<check>.+?)__(?P<variant>.+?)__\d+\.\w+$")


def referenced_names(report: dict[str, Any]) -> set[str]:
    names = set(report.get("evidence_files") or [])
    for item in (*(report.get("issues") or []), *(report.get("scenarios") or [])):
        if isinstance(item, dict):
            names.update(item.get("evidence") or [])
    return {n for n in names if isinstance(n, str) and n}


def heavy_kind(attachment: dict[str, Any]) -> str:
    """'video' or 'archive' for files listed with their URL instead of downloaded; '' otherwise."""
    content_type = attachment.get("content_type") or ""
    suffix = Path(attachment.get("name", "")).suffix.lower()
    if content_type.startswith("video/") or suffix in VIDEO_SUFFIXES:
        return "video"
    if suffix in ARCHIVE_SUFFIXES:
        return "archive"
    return ""


def _transcript(messages: list[dict[str, Any]]) -> str:
    lines = []
    for m in messages:
        when = dt.datetime.fromtimestamp(m.get("created_at", 0) or 0, dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        lines += [f"### {m.get('source', '?')} · {when}Z", "", m.get("message", ""), ""]
    return "\n".join(lines)


def evidence_index(folder: Path, evidence: dict[str, str]) -> dict[str, int]:
    """Write evidence.md (files grouped by check) and return the per-check counts."""
    groups: dict[str, list[str]] = defaultdict(list)
    for name, path in sorted(evidence.items()):
        match = EVIDENCE_NAME.match(name)
        groups[match.group("check") if match else "other"].append(path)
    lines = ["# Evidence index", "", "Files are named <round>-<platform>__<check>__<variant>__<nn>; variant = "
             "device-or-size_theme_locale_scale.", ""]
    for check in sorted(groups):
        lines += [f"## {check} ({len(groups[check])})", *[f"- {path}" for path in groups[check]], ""]
    (folder / "evidence.md").write_text("\n".join(lines), encoding="utf-8")
    return {check: len(paths) for check, paths in sorted(groups.items())}


def _wanted_attachments(attachments: list[dict[str, Any]], wanted: set[str] | None,
                        seen_ids: set[str]) -> list[dict[str, Any]]:
    """This round's files: those the report names, plus new videos/archives (or every new file without a report)."""
    latest: dict[str, dict[str, Any]] = {}
    for attachment in attachments:  # later entries win when a name repeats across rounds
        if attachment.get("source") != "user" and attachment.get("name"):
            latest[attachment["name"]] = attachment
    chosen = []
    for name, attachment in latest.items():
        referenced = wanted is not None and name in wanted
        new = str(attachment.get("attachment_id")) not in seen_ids
        if referenced or (new and (wanted is None or heavy_kind(attachment))):
            chosen.append(attachment)
    return chosen


def _download(client: DevinClient, folder: Path, attachments: list[dict[str, Any]], result: dict[str, Any],
              download_videos: bool) -> None:
    for attachment in attachments:
        name = attachment["name"]
        kind = heavy_kind(attachment)
        if kind == "archive" or (kind == "video" and not download_videos):
            result["not_downloaded"].append({"name": name, "kind": kind, "url": attachment.get("url", "")})
            continue
        dest = folder / "attachments" / safe_name(name)
        try:
            client.download_attachment(attachment, dest)
            result["evidence"][name] = str(dest)
        except (DevinApiError, InfraError, KeyError) as exc:
            result["errors"].append(f"{name}: {exc}")


def collect_platform(
    client: DevinClient, folder: Path, state: dict[str, Any], *, download_videos: bool, seen_ids: set[str]
) -> dict[str, Any]:
    """seen_ids: attachment ids collected in earlier rounds of the same session; they are skipped."""
    result: dict[str, Any] = {"report": None, "evidence": {}, "not_downloaded": [], "missing_evidence": [],
                              "errors": [], "evidence_counts": {}, "attachment_ids": sorted(seen_ids)}
    if not state.get("session_id"):
        return result
    folder.mkdir(parents=True, exist_ok=True)
    session_id = state["session_id"]
    try:
        session = client.get_session(session_id)
    except (DevinApiError, InfraError) as exc:
        result["errors"].append(f"session: {exc}")
        return result
    write_json(folder / "session.json", session)
    if has_final_report(state, session):
        result["report"] = session["structured_output"]
        write_json(folder / "report.json", result["report"])
    elif session.get("structured_output"):
        write_json(folder / "stale_structured_output.json", session["structured_output"])

    try:
        messages = client.list_messages(session_id)
        write_json(folder / "messages.json", messages)
        (folder / "transcript.md").write_text(_transcript(messages), encoding="utf-8")
    except (DevinApiError, InfraError) as exc:
        result["errors"].append(f"messages: {exc}")

    try:
        attachments = client.list_attachments(session_id)
    except (DevinApiError, InfraError) as exc:
        result["errors"].append(f"attachments: {exc}")
        return result

    wanted = referenced_names(result["report"]) if result["report"] else None
    result["attachment_ids"] = sorted(seen_ids | {str(a.get("attachment_id")) for a in attachments})
    _download(client, folder, _wanted_attachments(attachments, wanted, seen_ids), result, download_videos)
    if wanted is not None:
        got = set(result["evidence"]) | {item["name"] for item in result["not_downloaded"]}
        result["missing_evidence"] = sorted(wanted - got)
    result["evidence_counts"] = evidence_index(folder, result["evidence"])
    write_json(folder / "collected.json", {k: v for k, v in result.items() if k != "report"})
    return result
