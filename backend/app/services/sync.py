"""Pull from SimpleFIN and store it (FR-ACC-01..04, NFR-DATA-01/02). See the M1 spec, "Sync pipeline"."""
import datetime as dt
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..models import Account, BalanceSnapshot, Holding, SyncRun, Transaction, utcnow
from ..money import to_cents
from ..routers.category_budgets import MAX_AMOUNT_CENTS
from . import simplefin
from .rules import apply_to, load_rules
from .transfers import detect_transfers

MAX_WINDOW_DAYS = 40  # SimpleFIN recommends <= 45
FIRST_SYNC_DAYS = 365
OVERLAP_DAYS = 7  # re-read a week back to catch late-posting transactions
STALE_AFTER_DAYS = 3

Fetch = Callable[[dt.date, dt.date], dict]
_lock = threading.Lock()

_TYPE_KEYWORDS = (
    (("credit", "card"), "credit"),
    (("saving",), "savings"),
    (("loan", "mortgage"), "loan"),
    (("brokerage", "401k", "401(k)", "ira", "stock plan", "invest"), "investment"),
    (("checking",), "checking"),
)


class SyncInProgress(Exception):
    """Another sync (manual or scheduled) is already running."""


def window_start(db: Session, today: dt.date) -> dt.date:
    """Start early enough to cover the account that has gone longest without a good sync."""
    floor = today - dt.timedelta(days=FIRST_SYNC_DAYS)
    accounts = db.scalars(select(Account).where(Account.closed_at.is_(None), Account.is_manual.is_(False))).all()
    if not accounts or any(a.last_synced_at is None for a in accounts):
        return floor
    oldest = min(min(a.last_synced_at.date() for a in accounts), today)  # never in the future
    return max(oldest - dt.timedelta(days=OVERLAP_DAYS), floor)


def date_chunks(start: dt.date, end: dt.date, max_days: int = MAX_WINDOW_DAYS) -> list[tuple[dt.date, dt.date]]:
    chunks, cur = [], start
    while cur < end:
        nxt = min(cur + dt.timedelta(days=max_days), end)
        chunks.append((cur, nxt))
        cur = nxt
    return chunks or [(start, end)]


def guess_type(acct: dict) -> str:
    if acct.get("holdings"):
        return "investment"
    name = (acct.get("name") or "").lower()
    for keywords, kind in _TYPE_KEYWORDS:
        if any(k in name for k in keywords):
            return kind
    return "other"


def _upsert_account(db: Session, acct: dict) -> Account:
    institution = (acct.get("org") or {}).get("name") or "Unknown"
    account = db.scalar(select(Account).where(Account.external_id == acct["id"]))
    if account is None:
        # name and type are set once; later edits by the owner stick
        account = Account(external_id=acct["id"], institution=institution, name=acct.get("name") or "Account", type=guess_type(acct))
        db.add(account)
        db.flush()
        return account
    account.institution = institution
    return account


def _upsert_snapshot(db: Session, account: Account, balance, today: dt.date) -> None:
    cents = to_cents(balance)
    snap = db.scalar(select(BalanceSnapshot).where(BalanceSnapshot.account_id == account.id, BalanceSnapshot.date == today))
    if snap is None:
        db.add(BalanceSnapshot(account=account, date=today, balance_cents=cents))
    else:
        snap.balance_cents = cents


def _insert_new(db: Session, account: Account, acct: dict) -> list[Transaction]:
    existing = set(db.scalars(select(Transaction.external_id).where(Transaction.account_id == account.id)))
    new = []
    for t in acct.get("transactions") or []:
        if t.get("pending") or t.get("id") is None or t["id"] in existing:
            continue
        if t.get("posted") is None or t.get("amount") is None:
            continue  # a posted transaction without an id, date or amount is unusable; one bad row must not fail the sync
        txn = Transaction(
            account=account,
            external_id=t["id"],
            posted_date=dt.datetime.fromtimestamp(t["posted"], dt.UTC).date(),
            amount_cents=to_cents(t["amount"]),
            raw_description=t.get("description") or "",
            raw_payee=t.get("payee") or None,
            raw_memo=t.get("memo") or None,
        )
        db.add(txn)
        existing.add(t["id"])
        new.append(txn)
    return new


def _mark_status(db: Session, balance_dates: dict[int, dt.date], errors: list[str], today: dt.date, now: dt.datetime) -> tuple[int, int]:
    detail = "; ".join(errors)
    ok = stale = 0
    for account in db.scalars(select(Account).where(Account.closed_at.is_(None), Account.is_manual.is_(False))):
        seen = balance_dates.get(account.id)
        if seen is not None and (today - seen).days <= STALE_AFTER_DAYS:
            account.last_synced_at, account.last_error = now, None
            ok += 1
            continue
        problem = "Not returned by SimpleFIN" if seen is None else f"No new data from {account.institution} since {seen.isoformat()}"
        account.last_error = f"{problem}. {detail}" if detail else problem
        stale += 1
    return ok, stale


@dataclass
class _State:
    accounts: dict[str, Account] = field(default_factory=dict)
    balance_dates: dict[int, dt.date] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    new_txns: list[Transaction] = field(default_factory=list)


def _fetch_all(fetch: Fetch, start: dt.date, end: dt.date) -> list[dict]:
    """Every window is fetched before anything is written, so no DB write lock is held across network calls."""
    return [fetch(s, e) for s, e in date_chunks(start, end)]


def _replace_holdings(db: Session, account: Account, holdings: list[dict], today: dt.date) -> None:
    """Holdings are point-in-time: the latest payload's list replaces the account's set.

    A holding with an unusable symbol, market value or share count is skipped, and an unusable cost basis is
    stored as unknown; holdings are secondary data and must never fail the sync.
    """
    db.execute(delete(Holding).where(Holding.account_id == account.id))
    for h in holdings:
        if not isinstance(h, dict):
            continue
        symbol = (h.get("symbol") or "").strip()
        shares = str(h.get("shares") or "0").replace(",", "").strip()
        try:
            if not symbol or h.get("market_value") is None or not Decimal(shares).is_finite():
                continue
            value = to_cents(h["market_value"])
        except (ValueError, ArithmeticError):
            continue
        try:
            basis = to_cents(h["cost_basis"]) if h.get("cost_basis") is not None else 0
        except (ValueError, ArithmeticError):
            basis = 0
        if abs(value) > MAX_AMOUNT_CENTS or abs(basis) > MAX_AMOUNT_CENTS:  # would overflow at flush
            continue
        db.add(Holding(account=account, symbol=symbol, description=(h.get("description") or symbol).strip(),
                       shares=shares, market_value_cents=value, cost_basis_cents=basis or None, as_of=today))


def _ingest(db: Session, payloads: list[dict], today: dt.date, state: _State) -> None:
    for payload in payloads:
        state.errors += [e for e in payload.get("errors") or [] if e not in state.errors]
        for acct in payload.get("accounts") or []:
            account = state.accounts.get(acct["id"])
            if account is None:
                account = _upsert_account(db, acct)
                state.accounts[acct["id"]] = account
            if account.id not in state.balance_dates:  # balances are point-in-time, not per window
                if account.closed_at is None and acct.get("balance") is not None:
                    _upsert_snapshot(db, account, acct["balance"], today)
                if account.closed_at is None and isinstance(acct.get("holdings"), list):
                    _replace_holdings(db, account, acct["holdings"], today)
                stamp = acct.get("balance-date")
                state.balance_dates[account.id] = dt.datetime.fromtimestamp(stamp, dt.UTC).date() if stamp else today
            state.new_txns += _insert_new(db, account, acct)
        db.flush()  # autoflush is off; the next window's duplicate check must see this one's rows


def _run(db: Session, fetch: Fetch, now: dt.datetime) -> SyncRun:
    today = now.date()
    run = SyncRun(started_at=now, status="running")
    db.add(run)
    db.commit()
    try:
        state = _State()
        start, end = window_start(db, today), today + dt.timedelta(days=1)
        payloads = _fetch_all(fetch, start, end)
        floor = today - dt.timedelta(days=FIRST_SYNC_DAYS)
        backfill: list[dict] = []
        if start > floor:  # a new account has history older than this window; fetch it before the first write
            known = set(db.scalars(select(Account.external_id)))
            if any(a["id"] not in known for p in payloads for a in p.get("accounts") or []):
                backfill = _fetch_all(fetch, floor, start)
        _ingest(db, payloads, today, state)  # main payloads first: balances are "first seen" from the latest window
        _ingest(db, backfill, today, state)
        rules = load_rules(db)
        for txn in state.new_txns:
            apply_to(db, txn, rules)
        db.flush()
        detect_transfers(db, state.new_txns)
        ok, stale = _mark_status(db, state.balance_dates, state.errors, today, now)
        run.status = "partial" if stale else "success"
        run.accounts_ok, run.accounts_stale, run.txns_added = ok, stale, len(state.new_txns)
        run.error = "; ".join(state.errors) or None
    except Exception as exc:  # roll back everything from this run, record why (NFR-DATA-01)
        db.rollback()
        run.status = "failed"
        run.error = str(exc) if isinstance(exc, simplefin.SimpleFinError) else f"{type(exc).__name__}: {exc}"
    run.finished_at = utcnow()
    db.commit()
    return run


def run_sync(db: Session, fetch: Fetch | None = None, now: dt.datetime | None = None) -> SyncRun:
    if not _lock.acquire(blocking=False):
        raise SyncInProgress()
    try:
        return _run(db, fetch or simplefin.fetch_accounts, now or utcnow())
    finally:
        _lock.release()
