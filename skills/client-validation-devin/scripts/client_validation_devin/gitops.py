"""Thin git wrappers. Every command runs in the repository root."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .errors import GitError


def git(root: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {result.stderr.strip() or result.stdout.strip()}")
    return result.stdout.strip()


def repo_root(cwd: Path) -> Path:
    result = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise GitError(f"{cwd} is not inside a git repository")
    return Path(result.stdout.strip())


def head_sha(root: Path) -> str:
    return git(root, "rev-parse", "HEAD")


def current_branch(root: Path) -> str:
    branch = git(root, "rev-parse", "--abbrev-ref", "HEAD")
    return "" if branch == "HEAD" else branch


def is_dirty(root: Path) -> bool:
    return bool(git(root, "status", "--porcelain", "--untracked-files=no"))


def remote_url(root: Path, remote: str) -> str:
    url = git(root, "remote", "get-url", remote, check=False)
    if not url:
        raise GitError(f"git remote '{remote}' is not configured")
    return url


def repo_slug(url: str) -> str:
    """owner/name (GitLab subgroups kept) from https, ssh or scp-style remote URLs."""
    text = url.strip().removesuffix("/").removesuffix(".git")
    match = re.match(r"^[\w.-]+@[\w.-]+:(?P<path>.+)$", text)
    if match:
        return match.group("path").strip("/")
    match = re.match(r"^[a-z+]+://(?:[^@/]+@)?[^/]+/(?P<path>.+)$", text)
    if match:
        return match.group("path").strip("/")
    raise GitError(f"cannot derive owner/name from remote URL {url!r}; set [product].repo")


def default_branch(root: Path, remote: str) -> str:
    ref = git(root, "symbolic-ref", "--quiet", f"refs/remotes/{remote}/HEAD", check=False)
    if ref:
        return ref.removeprefix(f"refs/remotes/{remote}/")
    for candidate in ("main", "master"):
        if git(root, "rev-parse", "--verify", "--quiet", f"refs/remotes/{remote}/{candidate}", check=False):
            return candidate
    return ""


def merge_base(root: Path, remote: str) -> str:
    branch = default_branch(root, remote)
    if not branch:
        return ""
    return git(root, "merge-base", "HEAD", f"refs/remotes/{remote}/{branch}", check=False)


def changed_files(root: Path, base: str) -> list[str]:
    if not base:
        return []
    out = git(root, "diff", "--name-only", f"{base}...HEAD", check=False)
    return [line for line in out.splitlines() if line]


def diff_stat(root: Path, base: str, max_lines: int = 60) -> str:
    if not base:
        return ""
    lines = git(root, "diff", "--stat", f"{base}...HEAD", check=False).splitlines()
    if len(lines) > max_lines:
        lines = lines[: max_lines - 1] + [f"... ({len(lines) - max_lines + 1} more lines)", lines[-1]]
    return "\n".join(lines)


def push_scratch_ref(root: Path, remote: str, ref: str) -> None:
    git(root, "push", "--force", "--quiet", remote, f"HEAD:refs/heads/{ref}")


def push_dry_run(root: Path, remote: str, ref: str) -> tuple[bool, str]:
    result = subprocess.run(
        ["git", "push", "--dry-run", "--force", remote, f"HEAD:refs/heads/{ref}"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0, (result.stderr or result.stdout).strip()


def delete_remote_ref(root: Path, remote: str, ref: str) -> None:
    git(root, "push", "--quiet", remote, "--delete", f"refs/heads/{ref}")


def create_bundle(root: Path, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    git(root, "bundle", "create", str(dest), "HEAD")
    return dest


def safe_name(text: str) -> str:
    """A single path component: no separators, no leading dots (so never '.' or '..')."""
    return re.sub(r"[^A-Za-z0-9._-]+", "-", text).lstrip(".-").rstrip("-") or "unnamed"
