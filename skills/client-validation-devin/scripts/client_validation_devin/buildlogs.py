"""Summarize snapshot build logs: builds report success even when a warm-up step failed and printed a warning."""

from __future__ import annotations

import json
import re
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

from .api import DevinClient
from .errors import DevinApiError, InfraError

SIGNAL = re.compile(r"\bWARN\b|BUILD (SUCCESSFUL|FAILED|SUCCEEDED)|\berror:|What went wrong|FAILED\b|command not found",
                    re.IGNORECASE)
NOISE = re.compile(r"npm warn|DeprecationWarning|warning: '|ExecuteExternalTool", re.IGNORECASE)
BATCH_WINDOW = 300  # builds started within this many seconds of the newest belong to the same trigger
MAX_LINES_PER_REPO = 12


def batch_build_ids(client: DevinClient) -> list[str]:
    builds = client.list_builds()
    if not builds:
        return []
    started = [b.get("started_at") or b.get("created_at") or 0 for b in builds]
    newest = max(started)
    return [b["build_id"] for b, at in zip(builds, started) if at >= newest - BATCH_WINDOW]


def _rows(client: DevinClient, build_id: str) -> list[dict[str, Any]]:
    url = client.build_log_url(build_id)
    if not url:
        return []
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "build.log"
        client.download(url, path)
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip().startswith("{")]


def summarize(client: DevinClient, build_id: str) -> tuple[list[str], int]:
    """Readable lines for one build plus the number of warnings that need attention."""
    try:
        build = client.get_build(build_id)
        rows = _rows(client, build_id)
    except (DevinApiError, InfraError) as exc:
        return [f"build {build_id}: logs unavailable ({exc})"], 0
    per_repo: dict[str, list[str]] = defaultdict(list)
    warnings = 0
    for row in rows:
        text = str(row.get("msg") or "").strip().splitlines()
        message = text[0] if text else ""
        repo = row.get("repo_name") or "-"
        if repo.startswith("__") or not SIGNAL.search(message) or NOISE.search(message):
            continue
        if message.startswith("command:"):
            continue
        warnings += bool(re.search(r"\bWARN\b|FAILED|error:|What went wrong", message))
        per_repo[repo].append(f"  [{row.get('phase')}:{row.get('step')}] {message[:200]}")
    seconds = (build.get("completed_at") or 0) - (build.get("started_at") or 0)
    lines = [f"build {build_id}: {build.get('status', '?')} in {max(seconds, 0)} s"]
    for repo, items in per_repo.items():
        lines.append(f" {repo}")
        lines += items[:MAX_LINES_PER_REPO]
        if len(items) > MAX_LINES_PER_REPO:
            lines.append(f"  ... {len(items) - MAX_LINES_PER_REPO} more")
    if not per_repo:
        lines.append(" no warnings or build results in the log")
    return lines, warnings


def report(client: DevinClient, build_ids: list[str]) -> int:
    total = 0
    for build_id in build_ids:
        lines, warnings = summarize(client, build_id)
        total += warnings
        print("\n".join(lines))
    if total:
        print(f"{total} warning(s): a warm-up step failed. Sessions still boot, but they redo that work at run time; "
              "fix .devin/blueprint.yaml and apply again.")
    return total
