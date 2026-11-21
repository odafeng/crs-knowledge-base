"""tools/setup_monitoring.py against a fake Monitoring API: reruns change nothing, channels reach existing policies."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import setup_monitoring

P = "projects/test-project"


class FakeMonitoring:
    def __init__(self) -> None:
        self.channels: list[dict] = []
        self.policies: list[dict] = []
        self.checks: list[dict] = []
        self.writes: list[tuple[str, str]] = []

    def __call__(self, method: str, url: str, body: dict | None = None) -> dict:
        path = url.removeprefix(setup_monitoring.API + "/").split("?")[0]
        if method != "GET":
            self.writes.append((method, path))
        collection = path.rsplit("/", 1)[-1]
        store = {"notificationChannels": self.channels, "alertPolicies": self.policies,
                 "uptimeCheckConfigs": self.checks}  # fmt: skip
        if method == "GET":
            return {collection: store[collection]}
        if method == "POST":
            item = {**(body or {}), "name": f"{path}/{len(store[collection]) + 1}"}
            store[collection].append(item)
            return item
        assert method == "PATCH" and "updateMask=notificationChannels" in url
        policy = next(p for p in self.policies if p["name"] == path)
        policy["notificationChannels"] = (body or {})["notificationChannels"]
        return policy


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> FakeMonitoring:
    fake = FakeMonitoring()
    monkeypatch.setattr(setup_monitoring, "call", fake)
    return fake


def test_email_channel_is_created_once(api: FakeMonitoring) -> None:
    first = setup_monitoring.email_channel("test-project", "maintainer@example.org")
    again = setup_monitoring.email_channel("test-project", "maintainer@example.org")
    assert first == again and len(api.channels) == 1
    assert api.channels[0]["labels"] == {"email_address": "maintainer@example.org"}


def test_channels_are_added_to_policies_that_already_exist(api: FakeMonitoring) -> None:
    setup_monitoring.main("test-project", "api.example.org", [])
    assert len(api.policies) == 2 and all(p["notificationChannels"] == [] for p in api.policies)

    channel = setup_monitoring.email_channel("test-project", "maintainer@example.org")
    setup_monitoring.main("test-project", "api.example.org", [channel])
    assert all(p["notificationChannels"] == [channel] for p in api.policies)
    assert len(api.checks) == 1 and len(api.policies) == 2

    api.writes.clear()
    setup_monitoring.main("test-project", "api.example.org", [channel])
    assert api.writes == []  # a rerun with the same channels changes nothing


def test_existing_channels_on_a_policy_are_kept(api: FakeMonitoring) -> None:
    setup_monitoring.main("test-project", "api.example.org", [f"{P}/notificationChannels/old"])
    setup_monitoring.main("test-project", "api.example.org", [f"{P}/notificationChannels/new"])
    assert all(
        p["notificationChannels"] == [f"{P}/notificationChannels/old", f"{P}/notificationChannels/new"]
        for p in api.policies
    )
