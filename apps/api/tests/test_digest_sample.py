"""The comment digest's test mail (G8 #119), against a mock Resend; no database, no real email."""

import json
import threading
from collections.abc import Iterator
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from guthub_api import maintenance
from guthub_api.digest import send_sample

TO = "maintainer@example.test"


@pytest.fixture
def resend() -> Iterator[tuple[str, list[dict[str, Any]], list[int]]]:
    requests: list[dict[str, Any]] = []
    statuses: list[int] = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            pass

        def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler protocol
            body = json.loads(self.rfile.read(int(self.headers["content-length"])))
            requests.append({"path": self.path, "key": self.headers.get("Idempotency-Key"), "body": body})
            self.send_response(statuses.pop(0) if statuses else 200)
            self.send_header("content-length", "2")
            self.end_headers()
            self.wfile.write(b"{}")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}", requests, statuses
    server.shutdown()


def test_the_sample_looks_like_a_digest_and_says_it_is_a_test(resend: Any) -> None:
    base, requests, _ = resend
    result = send_sample(TO, date(2026, 11, 20), "https://guthub.tw", "re_test", base)
    assert result == {"status": "sent", "httpStatus": 200}
    assert TO not in json.dumps(result)  # the job log never gets the address
    [request] = requests
    message = request["body"]
    assert request["path"] == "/emails" and request["key"].startswith("comment-digest-sample/")
    assert message["to"] == [TO] and message["subject"] == "[測試] GutHub｜你追蹤的文獻有 2 則新留言"
    assert "（測試）範例文獻" in message["text"]
    # The blank token cannot unsubscribe anyone.
    assert "t=00000000-0000-0000-0000-000000000000" in message["text"]


def test_a_refused_sample_reports_the_status(resend: Any) -> None:
    base, _, statuses = resend
    statuses.append(403)
    assert send_sample(TO, date(2026, 11, 20), "https://guthub.tw", "re_bad", base) == {
        "status": "failed",
        "httpStatus": 403,
    }


def test_the_sample_needs_a_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GUTHUB_DATABASE_URL", "postgresql://unused")
    monkeypatch.delenv("GUTHUB_RESEND_API_KEY", raising=False)
    assert maintenance.main(["comment-digest", "--sample-to", TO]) == 1
