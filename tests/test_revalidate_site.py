"""Tests for worker on-demand Next.js cache revalidation helper (K3 #253)."""

import json
from unittest.mock import MagicMock, patch

import pytest

import revalidate_site


def test_noop_when_env_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(revalidate_site.URL_ENV, raising=False)
    monkeypatch.delenv(revalidate_site.SECRET_ENV, raising=False)
    with patch("revalidate_site.urllib.request.urlopen") as urlopen:
        assert revalidate_site.revalidate_site() is False
        urlopen.assert_not_called()


def test_posts_bearer_token_and_default_tag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(revalidate_site.URL_ENV, "https://guthub.tw/api/revalidate")
    monkeypatch.setenv(revalidate_site.SECRET_ENV, "secret-123")
    resp = MagicMock()
    resp.status = 200
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)

    with patch("revalidate_site.urllib.request.urlopen", return_value=resp) as urlopen:
        assert revalidate_site.revalidate_site() is True
        req = urlopen.call_args.args[0]
        assert req.full_url == "https://guthub.tw/api/revalidate"
        assert req.get_method() == "POST"
        assert req.get_header("Authorization") == "Bearer secret-123"
        assert json.loads(req.data.decode("utf-8")) == {"tags": ["guthub-content"]}


def test_network_error_is_non_fatal() -> None:
    with patch("revalidate_site.urllib.request.urlopen", side_effect=OSError("timeout")):
        assert (
            revalidate_site.revalidate_site(
                url="https://guthub.tw/api/revalidate",
                secret="secret-123",
            )
            is False
        )
