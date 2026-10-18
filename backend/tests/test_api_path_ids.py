import pytest

BIG = 10**20
BODY = {"name": "x"}


@pytest.mark.parametrize(
    "method,url,body",
    [
        ("patch", f"/api/accounts/{BIG}", BODY),
        ("patch", f"/api/categories/{BIG}", BODY),
        ("delete", f"/api/categories/{BIG}?replacement_id=1", None),
        ("delete", f"/api/categories/1?replacement_id={BIG}", None),
        ("put", f"/api/category-budgets/{BIG}", {"month": "2026-01", "amount_cents": 100}),
        ("patch", f"/api/transactions/{BIG}", {"notes": "x"}),
        ("delete", f"/api/transactions/{BIG}/transfer", None),
        ("patch", f"/api/recurring/items/{BIG}", BODY),
        ("delete", f"/api/recurring/items/{BIG}", None),
        ("patch", f"/api/rules/{BIG}", {"contains_text": "x"}),
        ("delete", f"/api/rules/{BIG}", None),
        ("patch", f"/api/goals/{BIG}", BODY),
        ("delete", f"/api/goals/{BIG}", None),
        ("post", f"/api/goals/{BIG}/contributions", {"date": "2026-01-01", "amount_cents": 1}),
        ("delete", f"/api/goals/{BIG}/contributions/1", None),
        ("delete", f"/api/goals/1/contributions/{BIG}", None),
    ],
)
def test_oversized_path_ids_are_422_not_500(client, method, url, body):
    res = getattr(client, method)(url, **({"json": body} if body is not None else {}))
    assert res.status_code == 422, (url, res.status_code)


RULE = {"contains_text": "TEST", "set_merchant": "Test"}


@pytest.mark.parametrize(
    "method,url,body",
    [
        ("post", f"/api/accounts/{BIG}/balance", {"balance_cents": 1}),
        ("delete", f"/api/accounts/{BIG}", None),
        ("post", "/api/rules", {**RULE, "account_id": BIG}),
        ("post", "/api/rules", {**RULE, "set_category_id": BIG}),
        ("post", "/api/rules", {**RULE, "amount_min_cents": -BIG}),
        ("post", "/api/rules", {**RULE, "amount_max_cents": BIG}),
        ("patch", "/api/rules/1", {**RULE, "account_id": BIG}),
        ("post", "/api/rules/reorder", {"ids": [BIG]}),
        ("patch", "/api/transactions/1", {"category_id": BIG}),
        ("post", "/api/transactions/review", {"ids": [BIG]}),
        ("get", f"/api/transactions?account_id={BIG}", None),
        ("get", f"/api/transactions?category_id={BIG}", None),
        ("get", f"/api/transactions?tag_id={BIG}", None),
        ("get", f"/api/transactions?min_cents=-{BIG}", None),
        ("get", f"/api/transactions?max_cents={BIG}", None),
        ("get", f"/api/transactions?cursor=2026-01-01:{BIG}", None),
        ("put", "/api/budget/settings", {"take_home_cents": BIG, "needs_pct": 50, "wants_pct": 30, "savings_pct": 20}),
    ],
)
def test_oversized_body_and_query_ints_are_422_not_500(client, method, url, body):
    res = getattr(client, method)(url, **({"json": body} if body is not None else {}))
    assert res.status_code == 422, (method, url, body, res.status_code)


def test_zero_ids_in_bodies_and_filters_are_422(client):
    assert client.post("/api/rules", json={**RULE, "account_id": 0}).status_code == 422
    assert client.post("/api/transactions/review", json={"ids": [0]}).status_code == 422
    assert client.get("/api/transactions?account_id=0").status_code == 422
