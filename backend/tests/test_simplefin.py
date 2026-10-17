import datetime as dt

import pytest
import requests

from app.services import simplefin

TOKEN = "https://user:secret@bridge.example/simplefin"


class FakeResponse:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload if payload is not None else {"errors": [], "accounts": []}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


def epoch(d: dt.date) -> str:
    return str(int(dt.datetime(d.year, d.month, d.day, tzinfo=dt.UTC).timestamp()))


def test_sends_window_and_basic_auth_without_pending(monkeypatch):
    seen = {}

    def fake_get(url, params, auth, timeout):
        seen.update(url=url, params=params, auth=auth)
        return FakeResponse()

    monkeypatch.setattr(simplefin.requests, "get", fake_get)
    simplefin.fetch_accounts(dt.date(2026, 1, 1), dt.date(2026, 2, 1), token=TOKEN)
    assert seen["url"] == "https://bridge.example/simplefin/accounts"
    assert seen["auth"] == ("user", "secret")
    assert seen["params"] == {"start-date": epoch(dt.date(2026, 1, 1)), "end-date": epoch(dt.date(2026, 2, 1))}


def test_403_raises_auth_error(monkeypatch):
    monkeypatch.setattr(simplefin.requests, "get", lambda *a, **k: FakeResponse(403))
    with pytest.raises(simplefin.SimpleFinAuthError, match="403"):
        simplefin.fetch_accounts(dt.date(2026, 1, 1), dt.date(2026, 1, 2), token=TOKEN)


def test_other_http_errors_raise_simplefin_error(monkeypatch):
    monkeypatch.setattr(simplefin.requests, "get", lambda *a, **k: FakeResponse(500))
    with pytest.raises(simplefin.SimpleFinError, match="500"):
        simplefin.fetch_accounts(dt.date(2026, 1, 1), dt.date(2026, 1, 2), token=TOKEN)


def test_network_errors_are_wrapped(monkeypatch):
    def boom(*a, **k):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(simplefin.requests, "get", boom)
    with pytest.raises(simplefin.SimpleFinError, match="Could not reach"):
        simplefin.fetch_accounts(dt.date(2026, 1, 1), dt.date(2026, 1, 2), token=TOKEN)


def test_missing_token_raises():
    with pytest.raises(simplefin.SimpleFinError, match="SIMPLEFIN_TOKEN"):
        simplefin.fetch_accounts(dt.date(2026, 1, 1), dt.date(2026, 1, 2), token="")


def test_malformed_token_raises():
    with pytest.raises(simplefin.SimpleFinError, match="access URL"):
        simplefin.fetch_accounts(dt.date(2026, 1, 1), dt.date(2026, 1, 2), token="https://no-creds.example")


def test_payload_errors_are_returned_not_raised(monkeypatch):
    payload = {"errors": ["Fidelity: login required"], "accounts": []}
    monkeypatch.setattr(simplefin.requests, "get", lambda *a, **k: FakeResponse(200, payload))
    assert simplefin.fetch_accounts(dt.date(2026, 1, 1), dt.date(2026, 1, 2), token=TOKEN)["errors"] == [
        "Fidelity: login required"
    ]
