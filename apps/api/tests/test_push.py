"""The Web Push sender without a database (C5 #95): what a browser receives must decrypt to the story, and the
request must carry a VAPID signature made with our key. A local fake push service stands in for the real ones."""

import base64
import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import http_ece
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils

from guthub_api.announce import Subscription, payload, web_push

SUBJECT = "mailto:privacy@example.org"


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def unb64url(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def vapid_keys() -> tuple[str, str]:
    key = ec.generate_private_key(ec.SECP256R1())
    public = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return b64url(public), b64url(key.private_numbers().private_value.to_bytes(32, "big"))


@pytest.fixture
def push_service() -> Iterator[tuple[str, list[tuple[dict[str, str], bytes]]]]:
    received: list[tuple[dict[str, str], bytes]] = []

    class Fake(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            pass

        def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler protocol
            headers = {key.lower(): value for key, value in self.headers.items()}
            received.append((headers, self.rfile.read(int(self.headers["content-length"]))))
            self.send_response(201)
            self.send_header("content-length", "0")
            self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}", received
    server.shutdown()


def test_payload_is_what_the_service_worker_reads() -> None:
    assert json.loads(
        payload("niche2-five-year", ["NICHE-2 五年追蹤：", "111 例無一復發"], "術後中位追蹤 58.7 個月")
    ) == {
        "title": "NICHE-2 五年追蹤：111 例無一復發",
        "body": "術後中位追蹤 58.7 個月",
        "url": "/news/niche2-five-year/",
        "tag": "niche2-five-year",
    }


def test_notification_decrypts_to_the_story_and_is_signed(push_service) -> None:
    url, received = push_service
    public, private = vapid_keys()
    browser_key = ec.generate_private_key(ec.SECP256R1())
    auth = b"0123456789abcdef"
    browser = Subscription(
        f"{url}/push/phone",
        b64url(
            browser_key.public_key().public_bytes(
                serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
            )
        ),
        b64url(auth),
    )
    data = payload("niche2-five-year", ["NICHE-2"], "dek")

    web_push(private, SUBJECT)(browser, data, "niche2-five-year")

    headers, body = received[0]
    decrypted = http_ece.decrypt(body, private_key=browser_key, auth_secret=auth, version="aes128gcm")
    assert json.loads(decrypted) == json.loads(data)
    assert (headers["content-encoding"], headers["topic"], headers["ttl"]) == ("aes128gcm", "niche2-five-year", "86400")
    scheme, _, params = headers["authorization"].partition(" ")
    fields = dict(part.strip().split("=", 1) for part in params.split(","))
    assert scheme == "vapid" and fields["k"] == public
    signing_input, _, signature = fields["t"].rpartition(".")
    raw = unb64url(signature)
    ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), unb64url(public)).verify(
        utils.encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")),
        signing_input.encode(),
        ec.ECDSA(hashes.SHA256()),
    )
    claims = json.loads(unb64url(signing_input.split(".")[1]))
    assert claims["aud"] == url and claims["sub"] == SUBJECT
