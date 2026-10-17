import datetime as dt

from tests.conftest import category, make_account, make_txn

D = dt.date


def bd(client, start, end):
    return client.get("/api/breakdown", params={"start": start, "end": end})


def test_categories_and_total_match_overview_for_a_month(client, db):
    acct = make_account(db)
    make_txn(db, acct, -5000, D(2026, 8, 3), category_id=category(db, "Groceries").id)
    make_txn(db, acct, -120000, D(2026, 8, 1), category_id=category(db, "Rent").id)
    make_txn(db, acct, 1500, D(2026, 8, 9), category_id=category(db, "Shopping").id)   # net-negative category
    make_txn(db, acct, -800, D(2026, 8, 31))                                            # uncategorized, last day
    make_txn(db, acct, -999, D(2026, 9, 1), category_id=category(db, "Groceries").id)  # outside range
    body = bd(client, "2026-08-01", "2026-08-31").json()
    overview = client.get("/api/overview", params={"month": "2026-08"}).json()
    assert [(c["category_id"], c["name"], c["cents"]) for c in body["categories"]] == [
        (r["category_id"], r["name"], r["cents"]) for r in overview["spending_by_category"]
    ]
    assert body["total_cents"] == overview["spent_cents"] == 120000 + 5000 + 800 - 1500
    uncategorized = [c for c in body["categories"] if c["category_id"] is None]
    assert uncategorized == [{"category_id": None, "name": "Uncategorized", "bucket": None, "cents": 800}]
    assert {c["name"]: c["bucket"] for c in body["categories"]}["Rent"] == "needs"


def test_top_merchants_ordered_counted_and_capped_at_ten(client, db):
    acct = make_account(db)
    shopping = category(db, "Shopping").id
    for i in range(12):
        make_txn(db, acct, -(1000 + i), D(2026, 8, 5), category_id=shopping, merchant=f"Shop {i:02d}")
    make_txn(db, acct, -500, D(2026, 8, 6), category_id=shopping, merchant="Shop 11")
    make_txn(db, acct, 4000, D(2026, 8, 7), category_id=shopping, merchant="Refunder")   # net > 0 inflow: left out
    make_txn(db, acct, -9000, D(2026, 8, 7), category_id=category(db, "Transfer").id, merchant="Bank")  # excluded
    merchants = bd(client, "2026-08-01", "2026-08-31").json()["merchants"]
    assert len(merchants) == 10
    assert merchants[0] == {"merchant": "Shop 11", "cents": 1511, "count": 2}
    assert [m["merchant"] for m in merchants[1:3]] == ["Shop 10", "Shop 09"]
    assert "Refunder" not in {m["merchant"] for m in merchants} and "Bank" not in {m["merchant"] for m in merchants}


def test_hidden_accounts_excluded(client, db):
    hidden = make_account(db, name="Hidden", is_hidden=True)
    make_txn(db, hidden, -5000, D(2026, 8, 3), category_id=category(db, "Groceries").id, merchant="Costco")
    body = bd(client, "2026-08-01", "2026-08-31").json()
    assert body == {"categories": [], "merchants": [], "total_cents": 0}


def test_bad_ranges_are_422(client):
    assert bd(client, "2026-08-31", "2026-08-01").status_code == 422
    assert bd(client, "2020-01-01", "2026-08-01").status_code == 422
    assert client.get("/api/breakdown", params={"start": "2026-08-01"}).status_code == 422


def test_end_at_max_date_is_422_not_500(client):
    assert bd(client, "9999-12-30", "9999-12-31").status_code == 422
    assert bd(client, "9999-12-31", "9999-12-31").status_code == 422


def test_range_boundary_is_3_times_366_days(client):
    start = D(2024, 1, 1)
    assert bd(client, start, start + dt.timedelta(days=3 * 366)).status_code == 200
    assert bd(client, start, start + dt.timedelta(days=3 * 366 + 1)).status_code == 422


def test_equal_merchants_are_ordered_by_name(client, db):
    acct = make_account(db)
    shopping = category(db, "Shopping").id
    for name in ("Zeta", "Alpha", "Mid"):
        make_txn(db, acct, -1000, D(2026, 8, 5), category_id=shopping, merchant=name)
    merchants = bd(client, "2026-08-01", "2026-08-31").json()["merchants"]
    assert [m["merchant"] for m in merchants] == ["Alpha", "Mid", "Zeta"]


def test_blank_merchants_are_left_out_of_top_merchants(client, db):
    acct = make_account(db)
    shopping = category(db, "Shopping").id
    make_txn(db, acct, -9000, D(2026, 8, 5), category_id=shopping, merchant="")
    make_txn(db, acct, -1000, D(2026, 8, 5), category_id=shopping, merchant="Target")
    body = bd(client, "2026-08-01", "2026-08-31").json()
    assert [m["merchant"] for m in body["merchants"]] == ["Target"]
    assert body["total_cents"] == 10000  # blank-merchant spending still counts toward the total


def test_transactions_merchant_filter_is_exact(client, db):
    acct = make_account(db)
    make_txn(db, acct, -100, D(2026, 8, 3), merchant="Costco")
    make_txn(db, acct, -200, D(2026, 8, 3), merchant="Costco Gas")
    make_txn(db, acct, -300, D(2026, 8, 3), merchant="costco")
    items = client.get("/api/transactions", params={"merchant": "Costco"}).json()["items"]
    assert [t["merchant"] for t in items] == ["Costco"]
