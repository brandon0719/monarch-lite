"""SimpleFIN Bridge client: the app's only network boundary for bank data."""
import datetime as dt
from urllib.parse import urlparse, urlunparse

import requests

from .. import config


class SimpleFinError(Exception):
    """Any failure talking to SimpleFIN."""


class SimpleFinAuthError(SimpleFinError):
    """The access token was revoked or is invalid (HTTP 403)."""


def _split_access_url(access_url: str) -> tuple[str, tuple[str, str]]:
    parsed = urlparse(access_url)
    if not parsed.username or not parsed.password:
        raise SimpleFinError("SIMPLEFIN_TOKEN is not a SimpleFIN access URL (expected https://user:pass@host/path)")
    netloc = parsed.hostname + (f":{parsed.port}" if parsed.port else "")
    base = urlunparse((parsed.scheme, netloc, parsed.path.rstrip("/"), "", "", ""))
    return base, (parsed.username, parsed.password)


def _epoch(d: dt.date) -> str:
    return str(int(dt.datetime.combine(d, dt.time(), dt.UTC).timestamp()))


def fetch_accounts(start: dt.date, end: dt.date, token: str | None = None) -> dict:
    """Balances plus posted transactions in [start, end). Pending ones are not requested.

    SimpleFIN recommends windows of 45 days or less; callers chunk (see services/sync.py).
    The payload's `errors` list is returned, not raised, so one broken bank can't block the rest.
    """
    token = config.SIMPLEFIN_TOKEN if token is None else token
    if not token:
        raise SimpleFinError("SIMPLEFIN_TOKEN is not set in .env")
    base, auth = _split_access_url(token)
    try:
        resp = requests.get(
            f"{base}/accounts",
            params={"start-date": _epoch(start), "end-date": _epoch(end)},
            auth=auth,
            timeout=60,
        )
    except requests.RequestException as exc:
        raise SimpleFinError(f"Could not reach SimpleFIN: {exc}") from exc
    if resp.status_code == 403:
        raise SimpleFinAuthError(
            "SimpleFIN denied access (403): the token was revoked or expired. "
            "Create a new setup token at bridge.simplefin.org and claim it into SIMPLEFIN_TOKEN."
        )
    try:
        resp.raise_for_status()
    except requests.HTTPError as exc:
        raise SimpleFinError(f"SimpleFIN returned HTTP {resp.status_code}") from exc
    return resp.json()
