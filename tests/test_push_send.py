"""The sender against a fake push service and a fake store.

What a browser would receive must decrypt to the story, the request must carry a valid VAPID signature,
and a subscription the push service reports as gone must be deleted from the store.
"""

import base64
import json
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import http_ece
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils
from push.keys import generate
from push.send import Outcome, payload, send
from push.store import Store

STORY = {
    "id": "niche2-five-year",
    "headline": ["NICHE-2 五年追蹤：", "術前雙免疫後 ", "111 例", "無一復發"],
    "dek": "術後中位追蹤 58.7 個月，3 年無病存活與 5 年整體存活都是 100%。",
}
SUBJECT = "mailto:editor@example.org"


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _unb64url(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class Browser:
    """The receiving end of one subscription: its key pair and auth secret."""

    def __init__(self) -> None:
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.auth = b"0123456789abcdef"

    def row(self, endpoint: str) -> dict[str, str]:
        public = self.key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
        return {"endpoint": endpoint, "p256dh": _b64url(public), "auth": _b64url(self.auth)}

    def decrypt(self, body: bytes) -> dict:
        return json.loads(http_ece.decrypt(body, private_key=self.key, auth_secret=self.auth, version="aes128gcm"))


@dataclass
class Recorder:
    """What the fake services were asked to do."""

    rows: list[dict] = field(default_factory=list)
    pushes: dict[str, tuple[dict, bytes]] = field(default_factory=dict)
    deleted: list[str] = field(default_factory=list)
    seen_keys: list[str | None] = field(default_factory=list)


def _handler(seen: Recorder) -> type[BaseHTTPRequestHandler]:
    class Fake(BaseHTTPRequestHandler):
        """Push service under /push/<name> and the subscription store under /rest/."""

        def log_message(self, *args) -> None:  # keep test output quiet
            pass

        def _reply(self, status: int, body: bytes = b"") -> None:
            self.send_response(status)
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler protocol
            seen.seen_keys.append(self.headers.get("apikey"))
            self._reply(200, json.dumps(seen.rows).encode())

        def do_DELETE(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler protocol
            seen.deleted.append(parse_qs(urlparse(self.path).query)["endpoint"][0])
            self._reply(204)

        def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler protocol
            name = self.path.rsplit("/", 1)[-1]
            headers = {key.lower(): value for key, value in self.headers.items()}
            seen.pushes[name] = (headers, self.rfile.read(int(self.headers["content-length"])))
            self._reply({"gone": 410, "broken": 500}.get(name, 201))

    return Fake


@pytest.fixture
def service():
    seen = Recorder()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(seen))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}", seen
    server.shutdown()


def test_payload_is_what_the_service_worker_reads():
    assert json.loads(payload(STORY)) == {
        "title": "NICHE-2 五年追蹤：術前雙免疫後 111 例無一復發",
        "body": STORY["dek"],
        "url": "news/niche2-five-year/",
        "tag": "niche2-five-year",
    }


def test_notification_decrypts_to_the_story_and_is_signed(service):
    url, seen = service
    public, private = generate()
    browser = Browser()
    seen.rows.append(browser.row(f"{url}/push/phone"))

    outcome = send(STORY, Store(f"{url}/rest", "service-key"), private, SUBJECT)

    assert outcome == Outcome(sent=1, removed=0, failed=0)
    assert seen.seen_keys == ["service-key"]
    headers, body = seen.pushes["phone"]
    assert browser.decrypt(body) == json.loads(payload(STORY))
    assert (headers["content-encoding"], headers["topic"], headers["ttl"]) == ("aes128gcm", "niche2-five-year", "86400")

    scheme, _, params = headers["authorization"].partition(" ")
    fields = dict(part.strip().split("=", 1) for part in params.split(","))
    assert scheme == "vapid" and fields["k"] == public
    signing_input, _, signature = fields["t"].rpartition(".")
    raw = _unb64url(signature)
    key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), _unb64url(public))
    key.verify(  # raises if the token was not signed by our private key
        utils.encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")),
        signing_input.encode(),
        ec.ECDSA(hashes.SHA256()),
    )
    claims = json.loads(_unb64url(signing_input.split(".")[1]))
    assert claims["aud"] == url and claims["sub"] == SUBJECT


def test_gone_subscription_is_removed_and_a_failure_does_not_stop_the_rest(service):
    url, seen = service
    _, private = generate()
    browsers = {name: Browser() for name in ("gone", "broken", "phone")}
    seen.rows.extend(b.row(f"{url}/push/{name}") for name, b in browsers.items())

    outcome = send(STORY, Store(f"{url}/rest", "service-key"), private, SUBJECT)

    assert outcome == Outcome(sent=1, removed=1, failed=1)
    assert seen.deleted == [f"eq.{url}/push/gone"]
    assert browsers["phone"].decrypt(seen.pushes["phone"][1])["tag"] == "niche2-five-year"
