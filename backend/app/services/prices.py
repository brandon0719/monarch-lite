"""Latest price per symbol (M5): Finnhub quote cached for an hour, else the stale cache, else a synced holding."""
import datetime as dt
import logging
import math
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config
from ..models import Account, Holding, Price, RsuGrant, utcnow

FRESH_FOR = dt.timedelta(hours=1)
RETRY_AFTER = dt.timedelta(minutes=10)  # after a failed fetch, leave that symbol alone for this long
_failed_at: dict[str, dt.datetime] = {}  # in-process negative cache; a restart simply retries
QUOTE_URL = "https://finnhub.io/api/v1/quote"
log = logging.getLogger("monarch-lite.prices")


MAX_QUOTE = 10_000_000
MIN_QUOTE = 0.01  # a sub-cent quote would cache as 0 cents


def _valid_quote(value) -> bool:
    """A real, finite, sane price; bools, NaN, infinities and absurd magnitudes are not."""
    # Range first: NaN fails it, and isfinite() would overflow on a huge int.
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and MIN_QUOTE <= value <= MAX_QUOTE and math.isfinite(value))


def _finnhub_quote_impl(symbol: str) -> float | None:
    if not config.FINNHUB_API_KEY:
        return None
    resp = requests.get(QUOTE_URL, params={"symbol": symbol},
                        headers={"X-Finnhub-Token": config.FINNHUB_API_KEY}, timeout=5)  # header, so no URL carries the key
    resp.raise_for_status()
    current = resp.json().get("c")
    return float(current) if _valid_quote(current) else None


finnhub_quote = _finnhub_quote_impl  # module attribute so tests can replace it


def _failure_label(exc: Exception) -> str:
    """Exception type, plus the HTTP status when there is one (an expired key shows as 401). Never the message or URL."""
    status = getattr(getattr(exc, "response", None), "status_code", None)
    return f"{type(exc).__name__} (HTTP {status})" if isinstance(status, int) else type(exc).__name__


def _cents(value) -> int:
    return int((Decimal(str(value)) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def holding_price(db: Session, symbol: str) -> tuple[int, dt.datetime, str] | None:
    h = db.scalar(select(Holding).join(Holding.account)
                  .where(Holding.symbol == symbol, Account.is_hidden.is_(False))
                  .order_by(Holding.as_of.desc(), Holding.id.desc()).limit(1))
    if h is None:
        return None
    try:
        shares = Decimal(h.shares)
    except InvalidOperation:
        return None
    if not shares.is_finite() or shares == 0:
        return None
    cents = int((Decimal(h.market_value_cents) / shares).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    return cents, dt.datetime.combine(h.as_of, dt.time()), "holding"


def clear_failures() -> None:
    _failed_at.clear()


def cached_price(db: Session, symbol: str) -> tuple[int, dt.datetime, str] | None:
    """The cache (however stale), else a synced holding. Never fetches."""
    cached = db.get(Price, symbol)
    if cached is not None:
        return cached.price_cents, cached.as_of, cached.source
    return holding_price(db, symbol)


def get_price(db: Session, symbol: str, now: dt.datetime | None = None, fetch=None) -> tuple[int, dt.datetime, str] | None:
    now = now or utcnow()
    cached = db.get(Price, symbol)
    if cached is not None and now - cached.as_of < FRESH_FOR:
        return cached.price_cents, cached.as_of, cached.source
    failed = _failed_at.get(symbol)
    if failed is not None and now - failed < RETRY_AFTER:
        return cached_price(db, symbol)
    try:
        quote = (fetch or finnhub_quote)(symbol)
    except Exception as exc:  # any network/JSON failure falls back; log the type only (the URL carries the key)
        log.warning("price fetch failed for %s: %s", symbol, _failure_label(exc))
        quote = None
    if quote is not None and not _valid_quote(quote):
        log.warning("price fetch for %s returned an unusable quote", symbol)
        quote = None
    if quote is not None:
        _failed_at.pop(symbol, None)
        cents = _cents(quote)
        try:
            row = cached or Price(symbol=symbol)
            row.price_cents, row.as_of, row.source = cents, now, "finnhub"
            db.add(row)
            db.commit()
        except Exception as exc:  # a locked DB or a concurrent first insert must not fail the read; the quote is good
            db.rollback()
            log.warning("price cache write failed for %s: %s", symbol, type(exc).__name__)
        return cents, now, "finnhub"
    _failed_at[symbol] = now
    return cached_price(db, symbol)


def refresh_all(db: Session, now: dt.datetime) -> None:
    """Hourly: refresh every symbol that has a grant; failures never escape."""
    for symbol in db.scalars(select(RsuGrant.symbol).distinct().order_by(RsuGrant.symbol)).all():
        try:
            get_price(db, symbol, now)
        except Exception as exc:
            db.rollback()  # a failed commit must not poison the next symbol
            log.warning("price refresh failed for %s: %s", symbol, type(exc).__name__)
