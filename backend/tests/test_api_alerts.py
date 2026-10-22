import datetime as dt
import hashlib
import time

from sqlalchemy import func, select

from app.models import DismissedAlert, Holding, SyncRun, utcnow
from app.routers import alerts as alerts_router
from app.services.recurring import step
from tests.conftest import make_account, make_txn
from tests.test_api_income import BIG, put, vest_grant, vti_price
from tests.test_api_recurring import RECENT, START
from tests.test_api_recurring import add as add_item

TODAY = dt.date.today()
TARGETS = {"stocks_pct": 80, "bonds_pct": 15, "cash_pct": 5, "drift_threshold": 5}


def get(client):
    return client.get("/api/alerts").json()


def of_kind(client, kind):
    return [a for a in get(client)["alerts"] if a["kind"] == kind]


def fresh_sync(db):
    db.add(SyncRun(started_at=utcnow(), finished_at=utcnow(), status="success"))
    db.commit()


def sync_key(text):
    return hashlib.sha1(text.encode()).hexdigest()[:10]


def dismiss(client, key):
    assert client.post("/api/alerts/dismiss", json={"key": key}).status_code == 204


def drifted_holdings(db, client):
    inv = make_account(db, name="Brokerage", type="investment")
    for symbol, value, desc in (("VTI", 90000, "Fund"), ("BND", 5000, "Bond ETF"), ("QSWEEP", 5000, "Deposit Sweep Account")):
        db.add(Holding(account_id=inv.id, symbol=symbol, description=desc, shares="1",
                       market_value_cents=value, cost_basis_cents=None, as_of=TODAY))
    db.commit()
    client.put("/api/holdings/classes/BND", json={"asset_class": "bonds"})


def test_empty_db_only_reports_that_nothing_has_synced(client):
    body = get(client)
    assert body["unavailable"] == []
    assert [(a["key"], a["kind"], a["severity"], a["link"]) for a in body["alerts"]] == [
        ("stale:never", "sync_stale", "warn", "/settings")]


def test_recent_successful_sync_is_not_stale(client, db):
    fresh_sync(db)
    assert get(client) == {"alerts": [], "unavailable": []}


def test_old_or_failed_sync_is_stale(client, db):
    old = utcnow() - dt.timedelta(hours=40)
    db.add(SyncRun(started_at=old, finished_at=old, status="partial"))
    db.add(SyncRun(started_at=utcnow(), finished_at=utcnow(), status="failed"))
    db.commit()
    (alert,) = of_kind(client, "sync_stale")
    local = old.replace(tzinfo=dt.UTC).astimezone().date()  # the detail shows the server's local date
    assert alert["key"] == f"stale:{old.date()}" and str(local) in alert["detail"]


def test_stale_detail_shows_the_local_date_but_the_key_keeps_the_utc_date(client, db, monkeypatch):
    # 03:00 UTC on a given day is still the day before at UTC-10.
    old = (utcnow() - dt.timedelta(days=5)).replace(hour=3, minute=0, second=0, microsecond=0)
    db.add(SyncRun(started_at=old, finished_at=old, status="success"))
    db.commit()
    monkeypatch.setenv("TZ", "Pacific/Honolulu")
    time.tzset()
    try:
        (alert,) = of_kind(client, "sync_stale")
    finally:
        monkeypatch.undo()
        time.tzset()
    assert alert["key"] == f"stale:{old.date()}"
    assert alert["detail"] == f"Last successful sync: {old.date() - dt.timedelta(days=1)}."


def test_sync_error_per_account_skips_hidden_and_closed(client, db):
    fresh_sync(db)
    broken = make_account(db, name="Broken", last_error="Login required")
    make_account(db, name="Hidden", last_error="Login required", is_hidden=True)
    make_account(db, name="Closed", last_error="Login required", closed_at=TODAY)
    make_account(db, name="Fine")
    (alert,) = get(client)["alerts"]
    assert alert["key"] == f"sync:{broken.id}:{sync_key('Login required')}"
    assert (alert["kind"], alert["severity"], alert["link"]) == ("sync_error", "warn", "/accounts")
    assert "Broken" in alert["title"] and alert["detail"] == "Login required"


def test_price_increase(client, db):
    fresh_sync(db)
    acct = make_account(db)
    item = add_item(client, anchor_date=str(START)).json()
    second = step(START, "monthly", 1)
    make_txn(db, acct, -1899, START, merchant="Spotify")
    make_txn(db, acct, -1999, second, merchant="Spotify")
    (alert,) = get(client)["alerts"]
    assert alert["key"] == f"price:{item['id']}:-1899:-1999"
    assert (alert["kind"], alert["severity"], alert["link"]) == ("price_increase", "info", "/recurring")
    assert "$18.99" in alert["title"] and "$19.99" in alert["title"]


def test_new_recurring_and_long_merchant_key_is_dismissable(client, db):
    fresh_sync(db)
    acct = make_account(db)
    merchant = "M" * 300
    for k in range(3):
        make_txn(db, acct, -500, step(RECENT, "monthly", k), merchant="Gym")
        make_txn(db, acct, -700, step(RECENT, "monthly", k), merchant=merchant)
    alerts = of_kind(client, "new_recurring")
    assert len(alerts) == 2 and all(len(a["key"]) <= 200 for a in alerts)
    gym = next(a for a in alerts if "Gym" in a["title"])
    assert gym["key"] == f"newrec:{sync_key('Gym')}:out:monthly" and gym["link"] == "/recurring" and gym["severity"] == "info"
    for a in alerts:
        dismiss(client, a["key"])
    assert of_kind(client, "new_recurring") == []


def test_dismissed_new_recurring_stays_dismissed_while_the_amount_drifts(client, db):
    fresh_sync(db)
    acct = make_account(db)
    make_txn(db, acct, -8000, RECENT, merchant="Power Co")
    make_txn(db, acct, -8300, step(RECENT, "monthly", 1), merchant="Power Co")
    last = make_txn(db, acct, -8100, step(RECENT, "monthly", 2), merchant="Power Co")
    (alert,) = of_kind(client, "new_recurring")
    dismiss(client, alert["key"])
    last.amount_cents = -8400  # the next normal bill, still inside the match window
    db.commit()
    assert of_kind(client, "new_recurring") == []


def price_rise(client, db):
    """A bill that jumps past the 10% window ($18.99 to $22.99)."""
    acct = make_account(db)
    item = add_item(client, anchor_date=str(START)).json()
    make_txn(db, acct, -1899, START, merchant="Spotify")
    make_txn(db, acct, -2299, step(START, "monthly", 1), merchant="Spotify")
    return acct, item


def test_dismissed_price_alert_stays_dismissed_at_the_same_new_price(client, db):
    fresh_sync(db)
    acct, item = price_rise(client, db)
    (alert,) = of_kind(client, "price_increase")
    assert alert["key"] == f"price:{item['id']}:-1899:-2299"
    dismiss(client, alert["key"])
    make_txn(db, acct, -2299, step(START, "monthly", 2), merchant="Spotify")  # next month, same new price
    assert of_kind(client, "price_increase") == []


def test_a_further_price_increase_brings_the_alert_back(client, db):
    fresh_sync(db)
    acct, item = price_rise(client, db)
    (alert,) = of_kind(client, "price_increase")
    dismiss(client, alert["key"])
    make_txn(db, acct, -2999, step(START, "monthly", 2), merchant="Spotify")
    (again,) = of_kind(client, "price_increase")
    assert again["key"] == f"price:{item['id']}:-1899:-2999" != alert["key"]


def test_under_withholding(client, db):
    fresh_sync(db)
    put(client, **BIG)
    vti_price(db)
    assert vest_grant(client, vest_date=f"{TODAY.year}-06-15").status_code == 201
    (alert,) = get(client)["alerts"]
    balance = client.get(f"/api/income/tax-estimate?year={TODAY.year}").json()["balance_cents"]
    assert alert["key"] == f"tax:{TODAY.year}:{balance // 50000}"
    assert (alert["kind"], alert["severity"], alert["link"]) == ("under_withholding", "warn", "/income")


def test_allocation_drift(client, db):
    fresh_sync(db)
    drifted_holdings(db, client)
    assert of_kind(client, "allocation_drift") == []  # no targets, no drift
    client.put("/api/allocation/targets", json=TARGETS)
    alerts = {a["key"]: a for a in of_kind(client, "allocation_drift")}
    assert set(alerts) == {"drift:stocks:over:2", "drift:bonds:under:2"}  # cash is exactly on the threshold
    stocks = alerts["drift:stocks:over:2"]
    assert (stocks["severity"], stocks["link"]) == ("info", "/networth")
    assert stocks["title"] == "Stocks over target by 10 pts" and stocks["detail"] == "Target 80% · now 90%."


def test_dismiss_hides_until_the_situation_changes(client, db):
    fresh_sync(db)
    acct = make_account(db, last_error="Login required")
    key = f"sync:{acct.id}:{sync_key('Login required')}"
    dismiss(client, key)
    dismiss(client, key)
    assert db.scalar(select(func.count()).select_from(DismissedAlert)) == 1
    assert get(client)["alerts"] == []
    acct.last_error = "Password changed"
    db.commit()
    (alert,) = get(client)["alerts"]
    assert alert["key"] == f"sync:{acct.id}:{sync_key('Password changed')}"


def test_dismiss_validates_the_key(client):
    for key in ("", "   ", "k" * 201):
        assert client.post("/api/alerts/dismiss", json={"key": key}).status_code == 422
    assert client.post("/api/alerts/dismiss", json={}).status_code == 422
    assert client.post("/api/alerts/dismiss", json={"key": "k" * 200}).status_code == 204


def test_failing_source_is_reported_and_the_rest_still_show(client, db, monkeypatch):
    acct = make_account(db, last_error="Login required")
    drifted_holdings(db, client)
    client.put("/api/allocation/targets", json=TARGETS)
    order = list(alerts_router.SOURCES)
    assert order.index("allocation") > order.index("recurring") > order.index("sync")

    def boom(_db):
        raise RuntimeError("broken")

    monkeypatch.setitem(alerts_router.SOURCES, "recurring", boom)
    res = client.get("/api/alerts")
    assert res.status_code == 200
    body = res.json()
    assert body["unavailable"] == ["recurring"]
    # sync runs before the failing source and allocation after it: both must still report
    assert {a["kind"] for a in body["alerts"]} == {"sync_error", "sync_stale", "allocation_drift"}
    assert any(a["key"].startswith(f"sync:{acct.id}:") for a in body["alerts"])


def test_sorted_warn_first_then_title(client, db):
    make_account(db, name="Zed", last_error="x")
    make_account(db, name="Amy", last_error="y")
    acct = make_account(db, name="Inv", type="investment")
    db.add(Holding(account_id=acct.id, symbol="VTI", description="Fund", shares="1", market_value_cents=1000,
                   cost_basis_cents=None, as_of=TODAY))
    db.commit()
    client.put("/api/allocation/targets", json={"stocks_pct": 10, "bonds_pct": 80, "cash_pct": 10, "drift_threshold": 5})
    alerts = get(client)["alerts"]
    assert [a["severity"] for a in alerts] == sorted((a["severity"] for a in alerts), key=lambda s: s != "warn")
    assert "info" in {a["severity"] for a in alerts}
    warn_titles = [a["title"] for a in alerts if a["severity"] == "warn"]
    assert warn_titles == sorted(warn_titles) and len(warn_titles) == 3
