import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import helpers  # noqa: F401
from client_validation_devin.api import DevinClient
from client_validation_devin.credentials import Credentials
from client_validation_devin.errors import DevinApiError


class Scripted(BaseHTTPRequestHandler):
    """429 twice then 200 on /v3/self; 307 to /storage, which rejects Authorization headers."""

    calls: list[str] = []

    def log_message(self, *args):
        pass

    def _send(self, status, payload=b"{}", headers=None):
        self.send_response(status)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        Scripted.calls.append(self.path)
        if self.path == "/v3/self":
            if Scripted.calls.count("/v3/self") <= 2:
                return self._send(429, b'{"title":"Too Many Requests","detail":"slow down"}', {"Retry-After": "3"})
            return self._send(200, json.dumps({"org_id": "org-x"}).encode())
        if self.path.startswith("/v3/organizations/org-x/attachments/"):
            port = self.server.server_address[1]
            return self._send(307, b"", {"Location": f"http://127.0.0.1:{port}/storage/file.png"})
        if self.path == "/storage/file.png":
            if self.headers.get("Authorization"):
                return self._send(400, b"two auth mechanisms")
            return self._send(200, b"PNGDATA")
        return self._send(404, b'{"title":"Not Found","detail":"nope"}')

    def do_POST(self):
        Scripted.calls.append("POST " + self.path)
        if self.path.endswith("/echo"):
            echoed = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode()
            return self._send(422, json.dumps({"title": "Unprocessable", "detail": echoed}).encode())
        self._send(500, b'{"title":"Internal","detail":"boom"}')


class ApiTest(unittest.TestCase):
    def setUp(self):
        Scripted.calls = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Scripted)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.sleeps = []
        self.client = DevinClient(Credentials("cog_testkey123456", "", base, "test"), sleep=self.sleeps.append)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def test_retries_429_with_retry_after_and_resolves_org(self):
        self.assertEqual(self.client.org_id, "org-x")
        self.assertEqual(self.sleeps, [3.0, 3.0])

    def test_download_does_not_forward_authorization(self):
        self.client._org_id = "org-x"
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "f.png"
            url = f"{self.client.base}/v3/organizations/org-x/attachments/u/file.png"
            self.assertEqual(self.client.download(url, dest), 7)
            self.assertEqual(dest.read_bytes(), b"PNGDATA")

    def test_download_refuses_non_https_urls(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(Exception, "non-https"):
                self.client.download("file:///etc/hosts", Path(tmp) / "hosts")

    def test_errors_never_echo_credentials(self):
        body = {"session_secrets": [{"key": "QA_PASSWORD", "value": "hunter2-secret"}]}
        with self.assertRaises(DevinApiError) as ctx:
            self.client.request("POST", "/v3/organizations/org-x/echo", body=body)
        message = str(ctx.exception)
        self.assertNotIn("hunter2-secret", message)
        self.assertIn("***", message)

    def test_session_create_is_not_retried_on_5xx(self):
        self.client._org_id = "org-x"
        with self.assertRaises(DevinApiError) as ctx:
            self.client.create_session({"prompt": "x"})
        self.assertEqual(ctx.exception.status, 500)
        self.assertEqual(Scripted.calls.count("POST /v3/organizations/org-x/sessions"), 1)
        self.assertIn("boom", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
