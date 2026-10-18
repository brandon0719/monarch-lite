import datetime as dt

import pytest
import requests

from app import config
from app.models import Holding, Price
from app.services import prices
from tests.conftest import make_account

NOW = dt.datetime(2026, 10, 17, 12, 0)


def test_fresh_cache_skips_fetch(db):
    db.add(Price(symbol="VTI", price_cents=25000, as_of=NOW - dt.timedelta(minutes=30), source="finnhub"))
    db.commit()
    assert prices.get_price(db, "VTI", NOW, fetch=lambda s: 999.0) == (25000, NOW - dt.timedelta(minutes=30), "finnhub")


def test_stale_cache_is_refreshed_and_upserted(db):
    db.add(Price(symbol="VTI", price_cents=25000, as_of=NOW - dt.timedelta(hours=2), source="finnhub"))
    db.commit()
    assert prices.get_price(db, "VTI", NOW, fetch=lambda s: 260.125) == (26013, NOW, "finnhub")
    assert db.get(Price, "VTI").price_cents == 26013


def test_fetch_failure_falls_back_to_stale_cache_then_holding_then_none(db, caplog):
    def boom(symbol):
        raise requests.ConnectionError("https://finnhub.io/api/v1/quote?token=SECRET123")

    db.add(Price(symbol="VTI", price_cents=25000, as_of=NOW - dt.timedelta(hours=5), source="finnhub"))
    db.commit()
    assert prices.get_price(db, "VTI", NOW, fetch=boom)[0] == 25000
    assert "SECRET123" not in caplog.text
    acct = make_account(db, name="Brokerage", type="investment")
    db.add(Holding(account_id=acct.id, symbol="BND", description="Bond ETF", shares="4", market_value_cents=30000,
                   cost_basis_cents=None, as_of=NOW.date()))
    db.commit()
    assert prices.get_price(db, "BND", NOW, fetch=boom) == (7500, dt.datetime.combine(NOW.date(), dt.time()), "holding")
    assert prices.get_price(db, "XYZ", NOW, fetch=boom) is None


def test_non_positive_quote_is_ignored(db):
    assert prices.get_price(db, "XYZ", NOW, fetch=lambda s: 0.0) is None
    assert db.get(Price, "XYZ") is None


def test_finnhub_quote_without_key_returns_none(monkeypatch):
    monkeypatch.setattr(config, "FINNHUB_API_KEY", "")
    assert prices._finnhub_quote_impl("VTI") is None


class FakeResponse:
    def __init__(self, body=None, error=None, status=200):
        self._body, self._error, self.status_code = body, error, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError("https://finnhub.io/api/v1/quote?token=SECRET123", response=self)

    def json(self):
        if self._error:
            raise self._error
        return self._body


def _quote_with(monkeypatch, body=None, error=None):
    monkeypatch.setattr(config, "FINNHUB_API_KEY", "test-key")
    monkeypatch.setattr(prices.requests, "get", lambda *a, **kw: FakeResponse(body, error))
    return prices._finnhub_quote_impl("VTI")


@pytest.mark.parametrize("c", [True, False, float("inf"), float("-inf"), float("nan"), "abc", 0, -1, None, 1e300])
def test_finnhub_quote_rejects_unusable_current_price(monkeypatch, c):
    assert _quote_with(monkeypatch, {"c": c}) is None


def test_finnhub_key_is_sent_in_a_header_never_the_url(monkeypatch):
    seen = {}

    def fake_get(url, **kw):
        seen.update(url=url, **kw)
        return FakeResponse({"c": 10.0})

    monkeypatch.setattr(config, "FINNHUB_API_KEY", "test-key")
    monkeypatch.setattr(prices.requests, "get", fake_get)
    assert prices._finnhub_quote_impl("VTI") == 10.0
    assert seen["headers"] == {"X-Finnhub-Token": "test-key"}
    assert seen["params"] == {"symbol": "VTI"}
    assert "test-key" not in seen["url"]


def test_http_error_logs_status_and_type_but_never_the_key(monkeypatch, db, caplog):
    monkeypatch.setattr(config, "FINNHUB_API_KEY", "test-key")
    monkeypatch.setattr(prices.requests, "get", lambda *a, **kw: FakeResponse({}, status=401))
    assert prices.get_price(db, "VTI", NOW, fetch=prices._finnhub_quote_impl) is None
    assert "HTTPError" in caplog.text and "HTTP 401" in caplog.text
    assert "SECRET123" not in caplog.text and "test-key" not in caplog.text


def test_finnhub_quote_missing_c_and_non_dict_bodies(monkeypatch):
    assert _quote_with(monkeypatch, {}) is None
    assert _quote_with(monkeypatch, {"c": 123.45}) == 123.45


def test_finnhub_quote_decode_error_raises_and_get_price_falls_back(monkeypatch, db):
    with pytest.raises(ValueError):
        _quote_with(monkeypatch, error=ValueError("bad json"))
    assert prices.get_price(db, "VTI", NOW, fetch=prices._finnhub_quote_impl) is None


@pytest.mark.parametrize("bad", [float("inf"), float("nan"), 1e300, True, "9", 10**400, 0.001])
def test_injected_bad_quote_falls_back_without_raising(db, bad):
    db.add(Price(symbol="VTI", price_cents=25000, as_of=NOW - dt.timedelta(hours=2), source="finnhub"))
    db.commit()
    assert prices.get_price(db, "VTI", NOW, fetch=lambda s: bad)[0] == 25000
    assert prices.get_price(db, "NONE", NOW, fetch=lambda s: bad) is None
    assert db.get(Price, "NONE") is None


@pytest.mark.allow_blocked_fetch
def test_default_fetch_path_is_intercepted(db, _no_network_prices):
    assert prices.get_price(db, "XYZ", NOW) is None
    assert _no_network_prices == ["XYZ"]


@pytest.mark.parametrize("cached_first", [False, True])
def test_failed_cache_write_still_returns_the_quote_and_later_calls_work(db, monkeypatch, caplog, cached_first):
    if cached_first:
        db.add(Price(symbol="VTI", price_cents=25000, as_of=NOW - dt.timedelta(hours=2), source="finnhub"))
        db.commit()
    real_commit, calls = db.commit, []

    def locked():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("database is locked SECRET123")
        real_commit()

    monkeypatch.setattr(db, "commit", locked)
    assert prices.get_price(db, "VTI", NOW, fetch=lambda s: 260.0) == (26000, NOW, "finnhub")
    assert "RuntimeError" in caplog.text and "SECRET123" not in caplog.text
    assert "VTI" not in prices._failed_at  # the quote was fine; only the cache write failed
    later = NOW + dt.timedelta(minutes=1)
    assert prices.get_price(db, "VTI", later, fetch=lambda s: 261.0) == (26100, later, "finnhub")
    assert db.get(Price, "VTI").price_cents == 26100


def test_refresh_all_rolls_back_a_failed_commit_and_continues(db, monkeypatch):
    from app.models import RsuGrant

    for symbol in ("AAA", "BBB"):
        db.add(RsuGrant(label=symbol, symbol=symbol, grant_date=dt.date(2025, 3, 1), start_date=dt.date(2025, 3, 20),
                        total_shares=400, schedule="amazon_5_15_40_40"))
    db.commit()
    monkeypatch.setattr(prices, "finnhub_quote", lambda symbol: 100.0)
    real_commit, calls = db.commit, []

    def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("disk full")
        real_commit()

    monkeypatch.setattr(db, "commit", flaky)
    prices.refresh_all(db, NOW)
    assert db.get(Price, "AAA") is None  # rolled back, not flushed with the next commit
    assert db.get(Price, "BBB").price_cents == 10000


def counting(result):
    calls = []

    def fetch(symbol):
        calls.append(symbol)
        if isinstance(result, Exception):
            raise result
        return result

    return fetch, calls


@pytest.mark.parametrize("result", [requests.ConnectionError("down"), None, float("nan")])
def test_failed_fetch_is_not_retried_for_ten_minutes(db, result):
    fetch, calls = counting(result)
    assert prices.get_price(db, "XYZ", NOW, fetch=fetch) is None
    assert prices.get_price(db, "XYZ", NOW + dt.timedelta(minutes=9), fetch=fetch) is None
    assert calls == ["XYZ"]
    prices.get_price(db, "XYZ", NOW + dt.timedelta(minutes=11), fetch=fetch)
    assert calls == ["XYZ", "XYZ"]
    other, other_calls = counting(None)
    prices.get_price(db, "ABC", NOW, fetch=other)  # the backoff is per symbol
    assert other_calls == ["ABC"]


def test_backoff_still_returns_the_stale_cache_and_clear_resets_it(db):
    db.add(Price(symbol="VTI", price_cents=25000, as_of=NOW - dt.timedelta(hours=2), source="finnhub"))
    db.commit()
    fetch, calls = counting(requests.Timeout("slow"))
    assert prices.get_price(db, "VTI", NOW, fetch=fetch)[0] == 25000
    assert prices.get_price(db, "VTI", NOW + dt.timedelta(minutes=1), fetch=fetch)[0] == 25000
    assert len(calls) == 1
    prices.clear_failures()
    prices.get_price(db, "VTI", NOW + dt.timedelta(minutes=2), fetch=fetch)
    assert len(calls) == 2


def test_a_good_quote_after_the_backoff_clears_the_failure(db):
    fetch, calls = counting(None)
    prices.get_price(db, "VTI", NOW, fetch=fetch)
    later = NOW + dt.timedelta(minutes=11)
    assert prices.get_price(db, "VTI", later, fetch=lambda s: 100.0) == (10000, later, "finnhub")
    assert "VTI" not in prices._failed_at


def test_cached_price_never_fetches(db):
    assert prices.cached_price(db, "VTI") is None
    db.add(Price(symbol="VTI", price_cents=25000, as_of=NOW - dt.timedelta(days=3), source="finnhub"))
    db.commit()
    assert prices.cached_price(db, "VTI") == (25000, NOW - dt.timedelta(days=3), "finnhub")
