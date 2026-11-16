"""Smoke test: the packaged app starts under uvicorn and answers health (B2 #59)."""

import json
import socket
import subprocess
import sys
import time
import urllib.request
from collections.abc import Iterator

import pytest


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def server() -> Iterator[str]:
    port = free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "guthub_api.main:app", "--host", "127.0.0.1", "--port", str(port)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def test_server_starts_and_reports_health(server: str) -> None:
    deadline = time.monotonic() + 15
    while True:
        try:
            with urllib.request.urlopen(f"{server}/api/v1/health", timeout=2) as response:
                assert response.status == 200
                assert json.load(response) == {"status": "ok"}
                return
        except OSError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.2)
