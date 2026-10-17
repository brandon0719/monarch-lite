import copy
import datetime as dt

import pytest
from sqlalchemy import func, select

from app.models import Account, BalanceSnapshot, Transaction
from app.services import sync
from app.services.simplefin import SimpleFinAuthError
from tests.conftest import category, make_account, make_txn

NOW = dt.datetime(2026, 10, 16, 12, 0)


def epoch(y, m, d):
    return int(dt.datetime(y, m, d, tzinfo=dt.UTC).timestamp())


def payload(checking_balance_date=None, include_savings=True, checking_balance="1234.56"):
    checking = {
        "id": "sf-chk", "name": "Everyday Checking", "org": {"name": "Chase"},
        "balance": checking_balance, "balance-date": checking_balance_date or epoch(2026, 10, 16),
        "transactions": [
            {"id": "t1", "posted": epoch(2026, 10, 10), "amount": "-9.99", "description": "NETFLIX.COM", "payee": "Netflix"},
            {"id": "t2", "posted": epoch(2026, 10, 11), "amount": "-500.00", "description": "ONLINE TRANSFER TO SAV"},
            {"id": "t3", "posted": 0, "amount": "-4.50", "description": "SQ *BLUE BOTTLE 0423", "pending": True},
        ],
    }
    savings = {
        "id": "sf-sav", "name": "High Yield Savings", "org": {"name": "Ally"},
        "balance": "10000.00", "balance-date": epoch(2026, 10, 16),
        "transactions": [{"id": "s1", "posted": epoch(2026, 10, 12), "amount": "500.00", "description": "TRANSFER FROM CHK"}],
    }
    return {"errors": [], "accounts": [checking, savings] if include_savings else [checking]}


def fetcher(*payloads):
    """Returns payloads in order, repeating the last one for every remaining chunk."""
    calls = []

    def fetch(start, end):
        calls.append((start, end))
        item = payloads[min(len(calls) - 1, len(payloads) - 1)]
        if isinstance(item, Exception):
            raise item
        return item

    fetch.calls = calls
    return fetch


def count(db, model):
    return db.scalar(select(func.count()).select_from(model))


def test_date_chunks():
    assert sync.date_chunks(dt.date(2026, 1, 1), dt.date(2026, 3, 1)) == [
        (dt.date(2026, 1, 1), dt.date(2026, 2, 10)),
        (dt.date(2026, 2, 10), dt.date(2026, 3, 1)),
    ]
    assert sync.date_chunks(dt.date(2026, 1, 1), dt.date(2026, 1, 1)) == [(dt.date(2026, 1, 1), dt.date(2026, 1, 1))]


def test_window_start_uses_oldest_account_sync(db):
    today = dt.date(2026, 10, 16)
    assert sync.window_start(db, today) == dt.date(2025, 10, 16)  # no accounts
    a = make_account(db, last_synced_at=dt.datetime(2026, 10, 15, 9))
    b = make_account(db, name="Savings", type="savings", last_synced_at=None)
    assert sync.window_start(db, today) == dt.date(2025, 10, 16)  # b never synced
    b.last_synced_at = dt.datetime(2026, 10, 1, 9)
    db.commit()
    assert sync.window_start(db, today) == dt.date(2026, 9, 24)  # oldest (b) - 7
    b.last_synced_at = dt.datetime(2024, 1, 1)
    db.commit()
    assert sync.window_start(db, today) == dt.date(2025, 10, 16)  # capped at 365
    b.closed_at = dt.date(2026, 1, 1)
    a.last_synced_at = dt.datetime(2027, 1, 1)  # clock skew / future
    db.commit()
    assert sync.window_start(db, today) == dt.date(2026, 10, 9)  # min(future, today) - 7


def test_guess_type():
    assert sync.guess_type({"name": "Sapphire Credit Card"}) == "credit"
    assert sync.guess_type({"name": "High Yield Savings"}) == "savings"
    assert sync.guess_type({"name": "Stock Plan", "holdings": [{"symbol": "AMZN"}]}) == "investment"
    assert sync.guess_type({"name": "Everyday Checking"}) == "checking"
    assert sync.guess_type({"name": "Mystery"}) == "other"


def test_first_sync_stores_categorizes_and_pairs(db):
    fetch = fetcher(payload())
    run = sync.run_sync(db, fetch=fetch, now=NOW)
    assert (run.status, run.accounts_ok, run.accounts_stale, run.txns_added) == ("success", 2, 0, 3)
    assert fetch.calls[0][0] == dt.date(2025, 10, 16) and fetch.calls[-1][1] == dt.date(2026, 10, 17)
    assert all((end - start).days <= sync.MAX_WINDOW_DAYS for start, end in fetch.calls)

    netflix = db.scalar(select(Transaction).where(Transaction.external_id == "t1"))
    assert (netflix.amount_cents, netflix.merchant, netflix.category_source) == (-999, "Netflix", "rule")
    assert netflix.category_id == category(db, "Subscriptions").id
    assert db.scalar(select(Transaction).where(Transaction.external_id == "t3")) is None  # pending skipped

    out = db.scalar(select(Transaction).where(Transaction.external_id == "t2"))
    into = db.scalar(select(Transaction).where(Transaction.external_id == "s1"))
    assert out.transfer_pair_id == into.id and out.category_id == category(db, "Transfer").id

    snap = db.scalar(select(BalanceSnapshot).join(Account).where(Account.external_id == "sf-chk"))
    assert (snap.date, snap.balance_cents) == (dt.date(2026, 10, 16), 123456)
    types = dict(db.execute(select(Account.external_id, Account.type)).all())
    assert types == {"sf-chk": "checking", "sf-sav": "savings"}


def test_second_identical_sync_changes_nothing(db):
    sync.run_sync(db, fetch=fetcher(payload()), now=NOW)
    before = (count(db, Transaction), count(db, BalanceSnapshot), count(db, Account))
    run = sync.run_sync(db, fetch=fetcher(payload()), now=NOW + dt.timedelta(hours=1))
    assert run.txns_added == 0
    assert (count(db, Transaction), count(db, BalanceSnapshot), count(db, Account)) == before


def test_user_edits_survive_resync(db):
    sync.run_sync(db, fetch=fetcher(payload()), now=NOW)
    netflix = db.scalar(select(Transaction).where(Transaction.external_id == "t1"))
    netflix.category_id, netflix.category_source = category(db, "Entertainment").id, "user"
    account = db.scalar(select(Account).where(Account.external_id == "sf-chk"))
    account.name, account.type = "Bills", "other"
    db.commit()
    sync.run_sync(db, fetch=fetcher(payload()), now=NOW + dt.timedelta(days=1))
    db.refresh(netflix)
    db.refresh(account)
    assert netflix.category_id == category(db, "Entertainment").id
    assert (account.name, account.type) == ("Bills", "other")


def test_stale_account_makes_run_partial(db):
    data = payload(checking_balance_date=epoch(2026, 10, 11))
    data["errors"] = ["Chase: please reauthenticate"]
    run = sync.run_sync(db, fetch=fetcher(data), now=NOW)
    assert (run.status, run.accounts_ok, run.accounts_stale) == ("partial", 1, 1)
    assert "reauthenticate" in run.error
    checking = db.scalar(select(Account).where(Account.external_id == "sf-chk"))
    assert "since 2026-10-11" in checking.last_error and "reauthenticate" in checking.last_error


def test_account_missing_from_payload_is_stale(db):
    sync.run_sync(db, fetch=fetcher(payload()), now=NOW)
    run = sync.run_sync(db, fetch=fetcher(payload(include_savings=False)), now=NOW + dt.timedelta(days=1))
    savings = db.scalar(select(Account).where(Account.external_id == "sf-sav"))
    assert run.status == "partial" and savings.last_error == "Not returned by SimpleFIN"


def test_closed_account_balance_is_frozen(db):
    sync.run_sync(db, fetch=fetcher(payload()), now=NOW)
    checking = db.scalar(select(Account).where(Account.external_id == "sf-chk"))
    checking.closed_at = dt.date(2026, 10, 16)
    db.commit()
    run = sync.run_sync(db, fetch=fetcher(payload(checking_balance="1.00")), now=NOW + dt.timedelta(hours=1))
    snap = db.scalar(select(BalanceSnapshot).where(BalanceSnapshot.account_id == checking.id))
    assert snap.balance_cents == 123456 and run.accounts_stale == 0


def test_auth_error_fails_run_and_writes_nothing(db):
    run = sync.run_sync(db, fetch=fetcher(SimpleFinAuthError("SimpleFIN denied access (403)")), now=NOW)
    assert run.status == "failed" and "403" in run.error and run.finished_at is not None
    assert count(db, Account) == 0


def test_crash_mid_sync_rolls_back(db):
    run = sync.run_sync(db, fetch=fetcher(payload(), RuntimeError("boom")), now=NOW)
    assert run.status == "failed" and run.error == "RuntimeError: boom"
    assert count(db, Transaction) == 0 and count(db, Account) == 0


def test_concurrent_sync_is_rejected(db):
    sync._lock.acquire()
    try:
        with pytest.raises(sync.SyncInProgress):
            sync.run_sync(db, fetch=fetcher(payload()), now=NOW)
    finally:
        sync._lock.release()


def windowed(fetch):
    """Like SimpleFIN: only returns transactions posted inside the requested window."""

    def inner(start, end):
        data = copy.deepcopy(fetch(start, end))
        for acct in data["accounts"]:
            acct["transactions"] = [
                t for t in acct["transactions"]
                if start <= dt.datetime.fromtimestamp(t["posted"], dt.UTC).date() < end
            ]
        return data

    inner.calls = fetch.calls
    return inner


def test_outage_recovery_refetches_missing_days(db):
    sync.run_sync(db, fetch=fetcher(payload()), now=NOW)
    down = payload(checking_balance_date=epoch(2026, 10, 30), include_savings=False)
    down["accounts"][0]["transactions"].append(  # checking keeps posting while Ally is down
        {"id": "t9", "posted": epoch(2026, 10, 29), "amount": "-1.00", "description": "X"}
    )
    sync.run_sync(db, fetch=fetcher(down), now=dt.datetime(2026, 10, 30, 12))
    back = payload(checking_balance_date=epoch(2026, 10, 31))
    back["accounts"][1]["balance-date"] = epoch(2026, 10, 31)
    back["accounts"][1]["transactions"].append(
        {"id": "s9", "posted": epoch(2026, 10, 18), "amount": "-3.00", "description": "Y"}
    )
    fetch = fetcher(back)
    sync.run_sync(db, fetch=windowed(fetch), now=dt.datetime(2026, 10, 31, 12))
    assert db.scalar(select(Transaction).where(Transaction.external_id == "s9")) is not None
    assert fetch.calls[0][0] <= dt.date(2026, 10, 9)


def test_null_balance_and_null_lists_do_not_fail(db):
    data = payload()
    data["accounts"][0]["balance"] = None
    data["accounts"][0]["transactions"].append({"id": "t4", "amount": "-1.00", "description": "NO POSTED DATE"})
    data["accounts"][0]["transactions"].append({"posted": epoch(2026, 10, 12), "amount": "-1.00", "description": "NO ID"})
    data["accounts"][1]["transactions"] = None
    run = sync.run_sync(db, fetch=fetcher(data), now=NOW)
    assert run.status != "failed"
    checking = db.scalar(select(Account).where(Account.external_id == "sf-chk"))
    assert db.scalar(select(BalanceSnapshot).where(BalanceSnapshot.account_id == checking.id)) is None
    ids = set(db.scalars(select(Transaction.external_id)))
    assert ids == {"t1", "t2"}  # pending t3 and malformed t4/no-id skipped
    assert sync.run_sync(db, fetch=fetcher({"errors": None, "accounts": None}), now=NOW).status != "failed"


def test_account_first_seen_in_later_chunk_is_not_stale(db):
    run = sync.run_sync(db, fetch=fetcher(payload(include_savings=False), payload()), now=NOW)
    savings = db.scalar(select(Account).where(Account.external_id == "sf-sav"))
    assert run.status == "success" and savings.last_error is None
    assert db.scalar(select(BalanceSnapshot).where(BalanceSnapshot.account_id == savings.id)) is not None


def test_new_account_triggers_backfill(db):
    sync.run_sync(db, fetch=fetcher(payload(include_savings=False)), now=NOW)
    both = payload()
    both["accounts"][1]["transactions"].append(
        {"id": "old", "posted": epoch(2026, 4, 29), "amount": "-7.00", "description": "OLD"}  # ~200 days back
    )
    now = NOW + dt.timedelta(days=1)
    fetch = fetcher(both)
    sync.run_sync(db, fetch=windowed(fetch), now=now)
    assert db.scalar(select(Transaction).where(Transaction.external_id == "old")) is not None
    assert any(start == now.date() - dt.timedelta(days=365) for start, _ in fetch.calls)


def test_backfill_is_fetched_before_anything_is_written(db):
    sync.run_sync(db, fetch=fetcher(payload(include_savings=False)), now=NOW)
    baseline = (count(db, Account), count(db, Transaction))
    both = payload()
    both["accounts"][1]["transactions"].append(
        {"id": "old", "posted": epoch(2026, 4, 29), "amount": "-7.00", "description": "OLD"}
    )
    inner = windowed(fetcher(both))
    seen = []

    def watching(start, end):  # a fetch with pending or flushed writes would hold the DB write lock across the network
        seen.append((bool(db.new or db.dirty), (count(db, Account), count(db, Transaction))))
        return inner(start, end)

    now = NOW + dt.timedelta(days=1)
    sync.run_sync(db, fetch=watching, now=now)
    assert len(seen) > 1 and any(start == now.date() - dt.timedelta(days=365) for start, _ in inner.calls)
    assert all(pending is False and rows == baseline for pending, rows in seen)
    assert db.scalar(select(Transaction).where(Transaction.external_id == "old")) is not None


def test_manual_accounts_never_widen_the_window_or_go_stale(db):
    today = dt.date(2026, 10, 16)
    make_account(db, last_synced_at=dt.datetime(2026, 10, 15, 9))
    manual = make_account(db, name="Online Savings", type="savings", is_manual=True, last_synced_at=None)
    assert sync.window_start(db, today) == dt.date(2026, 10, 8)  # synced account - 7, manual ignored
    sync.run_sync(db, fetch=fetcher(payload()), now=NOW)
    db.refresh(manual)
    assert manual.last_error is None and manual.last_synced_at is None


def brokerage(holdings):
    return {"errors": [], "accounts": [{
        "id": "sf-inv", "name": "Brokerage", "org": {"name": "Broker"},
        "balance": "1500.00", "balance-date": epoch(2026, 10, 16), "transactions": [], "holdings": holdings,
    }]}


def test_holdings_are_replaced_on_each_sync(db):
    from app.models import Holding
    first = [
        {"id": "h1", "symbol": "VTI", "description": "Total Market ETF", "shares": "5.5", "market_value": "1400.00", "cost_basis": "1000.00"},
        {"id": "h2", "symbol": "QSWEEP", "description": "Deposit Sweep Account", "shares": "100.00", "market_value": "100.00", "cost_basis": "0.00"},
        {"id": "h3", "symbol": "", "description": "No symbol", "shares": "1", "market_value": "1.00"},
        {"id": "h4", "symbol": "BAD", "description": "No value", "shares": "1"},
    ]
    sync.run_sync(db, fetch=fetcher(brokerage(first)), now=NOW)
    rows = db.scalars(select(Holding).order_by(Holding.symbol)).all()
    assert [(h.symbol, h.shares, h.market_value_cents, h.cost_basis_cents, h.as_of) for h in rows] == [
        ("QSWEEP", "100.00", 10000, None, NOW.date()), ("VTI", "5.5", 140000, 100000, NOW.date()),
    ]
    second = [{"id": "h1", "symbol": "VTI", "description": "Total Market ETF", "shares": "6", "market_value": "1500.00", "cost_basis": "1100.00"}]
    sync.run_sync(db, fetch=fetcher(brokerage(second)), now=NOW + dt.timedelta(days=1))
    assert [(h.symbol, h.shares) for h in db.scalars(select(Holding)).all()] == [("VTI", "6")]


def test_payload_without_holdings_leaves_them_and_closed_accounts_are_untouched(db):
    from app.models import Holding
    vti = [{"id": "h1", "symbol": "VTI", "description": "ETF", "shares": "1", "market_value": "100.00", "cost_basis": "90.00"}]
    sync.run_sync(db, fetch=fetcher(brokerage(vti)), now=NOW)
    no_key = brokerage(vti)
    del no_key["accounts"][0]["holdings"]
    sync.run_sync(db, fetch=fetcher(no_key), now=NOW + dt.timedelta(days=1))
    assert count(db, Holding) == 1
    acct = db.scalar(select(Account).where(Account.external_id == "sf-inv"))
    acct.closed_at = NOW.date()
    db.commit()
    sync.run_sync(db, fetch=fetcher(brokerage([])), now=NOW + dt.timedelta(days=2))
    assert count(db, Holding) == 1


def test_malformed_holding_values_never_fail_the_sync(db):
    from app.models import Holding
    acct = brokerage([
        {"id": "h1", "symbol": "VTI", "description": "ETF", "shares": "2", "market_value": "200.00", "cost_basis": "150.00"},
        {"id": "h2", "symbol": "NANV", "description": "Bad value", "shares": "1", "market_value": "NaN"},
        {"id": "h3", "symbol": "BADB", "description": "Bad basis", "shares": "1", "market_value": "50.00", "cost_basis": "abc"},
        {"id": "h4", "symbol": "INFS", "description": "Bad shares", "shares": "Infinity", "market_value": "10.00"},
        {"id": "h5", "symbol": "EMPT", "description": "Empty value", "shares": "1", "market_value": ""},
    ])
    acct["accounts"][0]["transactions"] = [{"id": "t9", "posted": epoch(2026, 10, 10), "amount": "-5.00", "description": "FEE"}]
    run = sync.run_sync(db, fetch=fetcher(acct), now=NOW)
    assert run.status == "success"
    assert db.scalar(select(Transaction).where(Transaction.external_id == "t9")) is not None
    rows = db.scalars(select(Holding).order_by(Holding.symbol)).all()
    assert [(h.symbol, h.market_value_cents, h.cost_basis_cents) for h in rows] == [("BADB", 5000, None), ("VTI", 20000, 15000)]


def test_backfill_pass_does_not_wipe_holdings(db):
    from app.models import Holding
    sync.run_sync(db, fetch=fetcher(payload(include_savings=False)), now=NOW)
    now = NOW + dt.timedelta(days=1)
    vti = {"id": "h1", "symbol": "VTI", "description": "ETF", "shares": "1", "market_value": "100.00", "cost_basis": "90.00"}
    both = payload()
    both["accounts"].append(brokerage([])["accounts"][0])  # a new account, so a backfill fetch happens
    fetch = fetcher(both)

    def with_holdings_only_in_recent_windows(start, end):
        data = copy.deepcopy(fetch(start, end))
        data["accounts"][-1]["holdings"] = [vti] if start >= now.date() - dt.timedelta(days=30) else []
        return data

    sync.run_sync(db, fetch=with_holdings_only_in_recent_windows, now=now)
    assert any(start == now.date() - dt.timedelta(days=365) for start, _ in fetch.calls)  # the backfill ran
    assert [h.symbol for h in db.scalars(select(Holding)).all()] == ["VTI"]


def test_non_dict_and_out_of_range_holdings_are_skipped_and_commas_stripped(db):
    from app.models import Holding
    from app.routers.category_budgets import MAX_AMOUNT_CENTS
    huge = f"{MAX_AMOUNT_CENTS // 100 + 1}.00"
    acct = brokerage([
        "VTI", None, 7,
        {"id": "h1", "symbol": "VTI", "description": "ETF", "shares": "1,234.5", "market_value": "200.00", "cost_basis": "150.00"},
        {"id": "h2", "symbol": "BIGV", "description": "Huge value", "shares": "1", "market_value": huge},
        {"id": "h3", "symbol": "BIGN", "description": "Huge negative", "shares": "1", "market_value": f"-{huge}"},
        {"id": "h4", "symbol": "BIGB", "description": "Huge basis", "shares": "1", "market_value": "10.00", "cost_basis": huge},
        {"id": "h5", "symbol": "EDGE", "description": "At the limit", "shares": "1", "market_value": f"{MAX_AMOUNT_CENTS // 100}.00"},
    ])
    run = sync.run_sync(db, fetch=fetcher(acct), now=NOW)
    assert run.status == "success"
    rows = db.scalars(select(Holding).order_by(Holding.symbol)).all()
    assert [(h.symbol, h.shares, h.market_value_cents) for h in rows] == [
        ("EDGE", "1", MAX_AMOUNT_CENTS), ("VTI", "1234.5", 20000)]
