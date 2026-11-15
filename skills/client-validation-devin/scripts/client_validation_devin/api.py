"""Minimal Devin REST v3 client on the standard library."""

from __future__ import annotations

import json
import mimetypes
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

from . import __version__
from .credentials import Credentials
from .errors import DevinApiError, InfraError

RETRYABLE_STATUS = {429, 500, 502, 503, 504}
USER_AGENT = f"client-validation-devin/{__version__}"


def _secret_values(body: Any) -> list[str]:
    if not isinstance(body, dict):
        return []
    return [s["value"] for s in body.get("session_secrets") or [] if isinstance(s, dict) and s.get("value")]


def _redact(text: str, secrets: list[str]) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    return text


def _items(data: Any) -> list[dict[str, Any]]:
    """List payloads arrive as a bare array, {"items": [...]} or {"data": [...]} depending on the endpoint."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("items", "data"):
            if isinstance(data.get(key), list):
                return data[key]
    return []


def _problem(body: bytes) -> tuple[str, str]:
    try:
        data = json.loads(body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return "", body.decode("utf-8", "replace")[:500]
    if not isinstance(data, dict):
        return "", str(data)[:500]
    detail = data.get("detail")
    if not isinstance(detail, str):
        detail = json.dumps(detail or data.get("errors") or data)[:1000]
    return str(data.get("title") or ""), detail


class DevinClient:
    def __init__(
        self,
        credentials: Credentials,
        *,
        sleep: Callable[[float], None] = time.sleep,
        max_attempts: int = 5,
        timeout: float = 60.0,
    ):
        self.credentials = credentials
        self.base = credentials.api_base
        self._org_id = credentials.org_id
        self._sleep = sleep
        self._max_attempts = max_attempts
        self._timeout = timeout

    # ---------- transport ----------

    def _open(self, request: urllib.request.Request):
        return urllib.request.urlopen(request, timeout=self._timeout)

    def _build(self, method: str, url: str, data: bytes | None, content_type: str | None) -> urllib.request.Request:
        request = urllib.request.Request(url, data=data, method=method)
        # Unredirected: never forwarded when the API answers 307 to a presigned storage URL.
        request.add_unredirected_header("Authorization", f"Bearer {self.credentials.api_key}")
        request.add_header("Accept", "application/json")
        request.add_header("User-Agent", USER_AGENT)
        if content_type:
            request.add_header("Content-Type", content_type)
        return request

    def request(
        self,
        method: str,
        path: str,
        *,
        body: Any = None,
        query: dict[str, Any] | None = None,
        raw: bytes | None = None,
        content_type: str | None = None,
        retry_unsafe: bool = False,
    ) -> Any:
        url = self.base + path
        if query:
            clean = {k: v for k, v in query.items() if v is not None}
            if clean:
                url += "?" + urllib.parse.urlencode(clean)
        data = raw
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            content_type = "application/json"
        safe = method in ("GET", "HEAD", "DELETE") or retry_unsafe
        attempt = 0
        while True:
            attempt += 1
            try:
                with self._open(self._build(method, url, data, content_type)) as response:
                    payload = response.read()
                return json.loads(payload.decode("utf-8")) if payload.strip() else {}
            except urllib.error.HTTPError as exc:
                payload = exc.read()
                retryable = exc.code == 429 or (safe and exc.code in RETRYABLE_STATUS)
                if retryable and attempt < self._max_attempts:
                    self._sleep(self._backoff(attempt, exc.headers.get("Retry-After")))
                    continue
                title, detail = _problem(payload)
                # Validation errors can echo request fields; never let a credential reach logs or run.json.
                detail = _redact(detail, [self.credentials.api_key, *_secret_values(body)])
                raise DevinApiError(method, path, exc.code, title or exc.reason or "", detail) from None
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                if safe and attempt < self._max_attempts:
                    self._sleep(self._backoff(attempt, None))
                    continue
                raise InfraError(f"Devin API {method} {path} unreachable: {exc}") from None

    @staticmethod
    def _backoff(attempt: int, retry_after: str | None) -> float:
        if retry_after:
            try:
                return min(120.0, max(1.0, float(retry_after)))
            except ValueError:
                pass
        return float(min(60, 2 ** attempt))

    def _paginate(self, path: str, page_size: int = 100) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        after = None
        while True:
            page = self.request("GET", path, query={"first": page_size, "after": after})
            items.extend(_items(page))
            if not isinstance(page, dict):
                return items
            after = page.get("end_cursor")
            if not page.get("has_next_page") or not after:
                return items

    # ---------- identity ----------

    def self_info(self) -> dict[str, Any]:
        return self.request("GET", "/v3/self")

    @property
    def org_id(self) -> str:
        if not self._org_id:
            org = self.self_info().get("org_id")
            if not org:
                raise InfraError("could not resolve the organization from /v3/self; "
                                 "set DEVIN_ORG_ID (Settings > Devin API)")
            self._org_id = org
        return self._org_id

    def org(self, suffix: str) -> str:
        return f"/v3/organizations/{self.org_id}{suffix}"

    # ---------- sessions ----------

    def create_session(self, body: dict[str, Any]) -> dict[str, Any]:
        return self.request("POST", self.org("/sessions"), body=body)

    def get_session(self, session_id: str) -> dict[str, Any]:
        return self.request("GET", self.org(f"/sessions/{session_id}"))

    def send_message(self, session_id: str, message: str) -> dict[str, Any]:
        return self.request("POST", self.org(f"/sessions/{session_id}/messages"), body={"message": message})

    def list_messages(self, session_id: str) -> list[dict[str, Any]]:
        return self._paginate(self.org(f"/sessions/{session_id}/messages"), page_size=200)

    def list_attachments(self, session_id: str) -> list[dict[str, Any]]:
        return _items(self.request("GET", self.org(f"/sessions/{session_id}/attachments")))

    def terminate_session(self, session_id: str, archive: bool = False) -> None:
        self.request("DELETE", self.org(f"/sessions/{session_id}"), query={"archive": str(archive).lower()})

    # ---------- files ----------

    def upload_attachment(self, path: Path) -> dict[str, Any]:
        boundary = "client_validation_devin" + secrets.token_hex(12)
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        head = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
            f"Content-Type: {mime}\r\n\r\n"
        ).encode("utf-8")
        tail = f"\r\n--{boundary}--\r\n".encode("utf-8")
        return self.request(
            "POST",
            self.org("/attachments"),
            raw=head + path.read_bytes() + tail,
            content_type=f"multipart/form-data; boundary={boundary}",
            retry_unsafe=True,
        )

    def download_attachment(self, attachment: dict[str, Any], dest: Path) -> int:
        """Attachment lists carry web-app URLs that reject API tokens; the API endpoint serves the same file."""
        attachment_id = attachment.get("attachment_id")
        name = attachment.get("name")
        if not attachment_id or not name:
            return self.download(attachment["url"], dest)
        path = f"/attachments/{urllib.parse.quote(str(attachment_id))}/{urllib.parse.quote(str(name))}"
        return self.download(self.base + self.org(path), dest)

    def download(self, url: str, dest: Path) -> int:
        if not (url.startswith("https://") or url.startswith(self.base + "/")):
            raise InfraError(f"refusing to download {dest.name} from a non-https URL")
        request = urllib.request.Request(url, method="GET")
        request.add_header("User-Agent", USER_AGENT)
        if url.startswith(self.base):
            request.add_unredirected_header("Authorization", f"Bearer {self.credentials.api_key}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self._open(request) as response, open(dest, "wb") as handle:
                size = 0
                while chunk := response.read(1 << 16):
                    handle.write(chunk)
                    size += len(chunk)
                return size
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            dest.unlink(missing_ok=True)
            raise InfraError(f"download failed for {dest.name}: {exc}") from None

    # ---------- environment ----------

    def list_repositories(self) -> list[dict[str, Any]]:
        return self._paginate(self.org("/repositories"))

    def list_blueprints(self) -> list[dict[str, Any]]:
        return _items(self.request("GET", self.org("/snapshot-setup/blueprints")))

    def create_blueprint(self, repo_name: str, contents: str) -> dict[str, Any]:
        body = {"repo_name": repo_name, "contents": contents, "source": "database"}
        return self.request("POST", self.org("/snapshot-setup/blueprints"), body=body)

    def update_blueprint(self, blueprint_id: str, contents: str) -> dict[str, Any]:
        body = {"contents": contents, "source": "database"}
        return self.request("PATCH", self.org(f"/snapshot-setup/blueprints/{blueprint_id}"), body=body)

    def sync_blueprint(self, repo_name: str) -> dict[str, Any]:
        path = f"/v3beta1/organizations/{self.org_id}/snapshot-setup/sync"
        return self.request("POST", path, body={"repo_name": repo_name})

    def trigger_build(self) -> dict[str, Any]:
        return self.request("POST", self.org("/snapshot-setup/builds"), body={})

    def get_build(self, build_id: str) -> dict[str, Any]:
        return self.request("GET", self.org(f"/snapshot-setup/builds/{build_id}"))

    def list_builds(self, first: int = 20) -> list[dict[str, Any]]:
        return _items(self.request("GET", self.org("/snapshot-setup/builds"), query={"first": first}))

    def build_log_url(self, build_id: str) -> str:
        return self.request("GET", self.org(f"/snapshot-setup/builds/{build_id}/logs")).get("url", "")
