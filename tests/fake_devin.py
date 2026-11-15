"""In-process fake of the Devin v3 API endpoints client-validation-devin uses, with scripted validator behaviour."""

from __future__ import annotations

import json
import re
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

ORG = "org-test"
TOKEN_RE = re.compile(r"round token `(r\d+-[0-9a-f]+)`")
ROUND_RE = re.compile(r"Run `[^`]+`, round (\d+)")
COMMIT_RE = re.compile(r"commit `([0-9a-f]{40})`")
PLATFORM_RE = re.compile(r"Platform `(\w+)` on Devin VM")
ALLOWED_PLATFORMS = ("default", "macos")


def archive_name(round_no: int, platform: str) -> str:
    return f"r{round_no}-{platform}__launch__complete-evidence_light_en_std__01.zip"


def make_report(token: str, round_no: int, platform: str, commit: str, outcome: str) -> dict[str, Any]:
    shot = f"r{round_no}-{platform}__create-note__small_light_en_default__01.png"
    phases = {name: {"status": "pass"} for name in ("checkout", "build", "tests", "launch", "scenarios", "layout")}
    report: dict[str, Any] = {
        "schema_version": "1", "round_token": token, "report_status": "final", "platform": platform,
        "commit": commit, "verdict": "pass", "summary": f"{platform} looks good.", "phases": phases,
        "scenarios": [{"id": "create-note", "status": "pass", "evidence": [shot]}],
        "issues": [], "evidence_files": [shot, archive_name(round_no, platform)],
    }
    if outcome == "fail":
        report["verdict"] = "fail"
        report["phases"]["layout"] = {"status": "fail", "detail": "overlap"}
        report["issues"] = [{
            "id": f"{platform}-001", "severity": "major", "category": "layout",
            "title": "Save button overlaps the note title on small screens", "scenario": "create-note",
            "screen": "Editor", "actual": "Button covers the title", "evidence": [shot],
            "suggested_fix": "Wrap the toolbar", "confidence": "high",
        }]
    return report


class FakeDevin:
    """Behaviours per platform: pass, fail, ask (needs an auto-reply), silent (needs a nudge), quota."""

    def __init__(self, behaviours: dict[str, str] | None = None, polls_before_report: int = 2):
        self.behaviours = behaviours or {}
        self.polls_before_report = polls_before_report
        self.sessions: dict[str, dict[str, Any]] = {}
        self.files: dict[str, bytes] = {}
        self.requests: list[tuple[str, str, dict[str, str]]] = []
        self.created_bodies: list[dict[str, Any]] = []
        self.blueprints: list[dict[str, Any]] = []
        self.blueprint_patches = 0
        self.builds: dict[str, dict[str, Any]] = {}
        self.uploads: list[str] = []
        self.lock = threading.Lock()
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def __enter__(self) -> "FakeDevin":
        self.thread.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.server.shutdown()
        self.server.server_close()

    # ---------- behaviour ----------

    def _arm(self, session: dict[str, Any], prompt: str) -> None:
        token = TOKEN_RE.search(prompt).group(1)
        session.update(token=token, round=int(ROUND_RE.search(prompt).group(1)),
                       commit=COMMIT_RE.search(prompt).group(1), polls=0, status="running",
                       status_detail="working", replied=False)

    def _advance(self, s: dict[str, Any]) -> None:
        behaviour = self.behaviours.get(s["platform"], "pass")
        s["polls"] += 1
        if s.get("structured_output", {}).get("round_token") == s["token"] or s["status"] == "exit":
            return
        if behaviour == "quota":
            s.update(status="suspended", status_detail="out_of_quota")
            return
        if s["polls"] < self.polls_before_report:
            return
        if behaviour == "ask" and not s["replied"]:
            s.update(status_detail="waiting_for_user")
            return
        if behaviour == "silent" and not s["replied"]:
            s.update(status_detail="finished")
            return
        outcome = "fail" if behaviour == "fail" else "pass"
        s["structured_output"] = make_report(s["token"], s["round"], s["platform"], s["commit"], outcome)
        s.update(status="running", status_detail="finished")
        for name in s["structured_output"]["evidence_files"]:
            self.files[name] = b"\x89PNG fake"
            # Like the real list: a web-app URL that rejects API tokens; clients must use the API endpoint.
            url = f"https://app.devin.invalid/attachments/{name}/{name}"
            kind = "application/zip" if name.endswith(".zip") else "image/png"
            s["attachments"].append({"attachment_id": name, "name": name, "source": "devin",
                                     "content_type": kind, "url": url})
        s["attachments"].append({"attachment_id": f"vid-{s['session_id']}-{s['round']}",
                                 "name": f"r{s['round']}-walkthrough.mp4", "source": "devin",
                                 "content_type": "video/mp4", "url": f"{self.base}/files/video.mp4"})

    # ---------- HTTP ----------

    def _handler(self):
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: Any) -> None:
                pass

            def _send(self, status: int, payload: Any = None, raw: bytes | None = None, headers: dict | None = None):
                body = raw if raw is not None else json.dumps(payload if payload is not None else {}).encode()
                self.send_response(status)
                for key, value in (headers or {}).items():
                    self.send_header(key, value)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _body(self) -> bytes:
                return self.rfile.read(int(self.headers.get("Content-Length") or 0))

            def _route(self, method: str) -> None:
                parsed = urllib.parse.urlparse(self.path)
                path = parsed.path
                fake.requests.append((method, path, dict(self.headers)))
                if path.startswith("/files/"):
                    # Build logs are served from the API host in this fake; attachments mimic presigned storage.
                    if self.headers.get("Authorization") and not path.startswith("/files/build-"):
                        return self._send(400, {"detail": "auth header leaked to storage"})
                    return self._send(200, raw=fake.files.get(path.rsplit("/", 1)[-1], b"video"))
                if self.headers.get("Authorization") != "Bearer cog_testkey123456":
                    return self._send(401, {"title": "Unauthorized", "detail": "bad key"})
                with fake.lock:
                    return self._dispatch(method, path, urllib.parse.parse_qs(parsed.query))

            def _dispatch(self, method: str, path: str, query: dict[str, list[str]]) -> None:
                org = f"/v3/organizations/{ORG}"
                if path == "/v3/self":
                    return self._send(200, {"principal_type": "user", "org_id": ORG})
                if method == "POST" and path == f"{org}/sessions":
                    body = json.loads(self._body())
                    if body.get("platform") not in ALLOWED_PLATFORMS:
                        return self._send(400, {"title": "Bad Request",
                                                "detail": f"Unknown platform '{body.get('platform')}'. "
                                                          f"Available platforms: {', '.join(ALLOWED_PLATFORMS)}"})
                    fake.created_bodies.append(body)
                    sid = f"devin-{len(fake.sessions) + 1:04d}"
                    platform = PLATFORM_RE.search(body["prompt"]).group(1)
                    session = {"session_id": sid, "platform": platform, "messages": [], "attachments": [],
                               "url": f"https://app.devin.ai/sessions/{sid}", "acus_consumed": 1.5}
                    fake._arm(session, body["prompt"])
                    session["messages"].append({"event_id": "e0", "source": "user", "message": body["prompt"][:80],
                                                "created_at": 1})
                    fake.sessions[sid] = session
                    return self._send(200, self._public(session))
                if path == f"{org}/attachments" and method == "POST":
                    data = self._body()
                    name = re.search(rb'filename="([^"]+)"', data).group(1).decode()
                    fake.uploads.append(name)
                    return self._send(200, {"attachment_id": "up1", "name": name, "url": f"{fake.base}/files/{name}"})
                if path.startswith(f"{org}/attachments/"):
                    name = path.rsplit("/", 1)[-1]
                    return self._send(307, raw=b"", headers={"Location": f"{fake.base}/files/{name}"})
                match = re.match(rf"^{org}/sessions/([\w-]+)(/\w+)?$", path)
                if match:
                    return self._session(method, fake.sessions.get(match.group(1)), match.group(2) or "", query)
                if path == f"{org}/repositories":
                    return self._send(200, {"items": [{"repo_full_name": "acme/notes"}], "has_next_page": False})
                if path == f"{org}/snapshot-setup/blueprints":
                    if method == "POST":
                        item = {"blueprint_id": f"bp{len(fake.blueprints) + 1}", "source": "database",
                                **json.loads(self._body())}
                        fake.blueprints.append(item)
                        return self._send(200, item)
                    return self._send(200, {"data": fake.blueprints})  # real envelope: BlueprintList
                if path.startswith(f"{org}/snapshot-setup/blueprints/") and method == "PATCH":
                    target = next(b for b in fake.blueprints if b["blueprint_id"] == path.rsplit("/", 1)[-1])
                    target.update(json.loads(self._body()))
                    fake.blueprint_patches += 1
                    return self._send(200, target)
                if path == f"{org}/snapshot-setup/builds" and method == "POST":
                    fake.builds["b1"] = {"build_id": "b1", "status": "succeeded", "started_at": 100,
                                         "completed_at": 160}
                    rows = [{"repo_name": "acme/notes", "phase": "maintenance", "step": 0, "msg": "command: npm ci"},
                            {"repo_name": "acme/notes", "phase": "maintenance", "step": 0, "msg": "BUILD SUCCESSFUL"},
                            {"repo_name": "acme/notes", "phase": "maintenance", "step": 1,
                             "msg": "WARN: iOS warm build failed"}]
                    fake.files["build-b1.log"] = "\n".join(json.dumps(r) for r in rows).encode()
                    return self._send(200, {"build_id": "b1", "status": "pending"})
                if path == f"{org}/snapshot-setup/builds":
                    return self._send(200, {"items": list(fake.builds.values())})
                if path.startswith(f"{org}/snapshot-setup/builds/") and path.endswith("/logs"):
                    build_id = path.split("/")[-2]
                    return self._send(200, {"url": f"{fake.base}/files/build-{build_id}.log", "expires_at": 0})
                if path.startswith(f"{org}/snapshot-setup/builds/"):
                    return self._send(200, fake.builds.get(path.rsplit("/", 1)[-1], {}))
                return self._send(404, {"title": "Not Found", "detail": path})

            def _public(self, s: dict[str, Any]) -> dict[str, Any]:
                keys = ("session_id", "url", "status", "status_detail", "acus_consumed", "structured_output")
                return {k: s.get(k) for k in keys}

            def _session(self, method: str, s: dict[str, Any] | None, tail: str, query: dict) -> None:
                if s is None:
                    return self._send(404, {"title": "Not Found", "detail": "no session"})
                if method == "GET" and not tail:
                    fake._advance(s)
                    return self._send(200, self._public(s))
                if method == "DELETE" and not tail:
                    s.update(status="exit", status_detail=None)
                    return self._send(200, self._public(s))
                if tail == "/messages" and method == "POST":
                    text = json.loads(self._body())["message"]
                    s["messages"].append({"event_id": f"e{len(s['messages'])}", "source": "user", "message": text,
                                          "created_at": 2})
                    if text.startswith("NEW ROUND"):
                        fake._arm(s, text)
                    else:
                        s["replied"] = True
                        s.update(status="running", status_detail="working")
                    return self._send(200, self._public(s))
                if tail == "/messages":
                    return self._send(200, {"items": s["messages"], "has_next_page": False})
                if tail == "/attachments":
                    return self._send(200, s["attachments"])
                return self._send(404, {"title": "Not Found", "detail": tail})

            def do_GET(self) -> None:
                self._route("GET")

            def do_POST(self) -> None:
                self._route("POST")

            def do_DELETE(self) -> None:
                self._route("DELETE")

            def do_PATCH(self) -> None:
                self._route("PATCH")

        return Handler
