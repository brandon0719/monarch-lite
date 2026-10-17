from tests.conftest import category, make_account, make_txn

NEW = {"contains_text": "zzq", "account_id": None, "amount_min_cents": None, "amount_max_cents": None,
       "set_category_id": None, "set_merchant": None, "add_tag_name": None}


def test_create_goes_first_and_resolves_tag(client, db):
    existing = client.get("/api/rules").json()
    body = client.post("/api/rules", json={**NEW, "set_category_id": category(db, "Dining").id, "add_tag_name": "coffee"})
    assert body.status_code == 201
    assert body.json()["priority"] < min(r["priority"] for r in existing)
    assert client.get("/api/rules").json()[0]["id"] == body.json()["id"]
    assert body.json()["add_tag_name"] == "coffee"


def test_more_specific_new_rule_beats_seed_rule(client, db):
    subs = category(db, "Subscriptions")
    client.post("/api/rules", json={**NEW, "contains_text": "amazon prime", "set_category_id": subs.id})
    txn = make_txn(db, make_account(db), -1499, raw_description="AMAZON PRIME*AB12", merchant="Amazon Prime")
    client.post("/api/rules/apply")
    db.refresh(txn)
    assert txn.category_id == subs.id


def test_create_on_empty_rule_list_starts_at_zero(client, db):
    for r in client.get("/api/rules").json():
        client.delete(f"/api/rules/{r['id']}")
    assert client.post("/api/rules", json={**NEW, "set_merchant": "Zed"}).json()["priority"] == 0


def test_min_amount_cannot_exceed_max(client):
    body = {**NEW, "set_merchant": "Zed", "amount_min_cents": 500, "amount_max_cents": 100}
    res = client.post("/api/rules", json=body)
    assert res.status_code == 422 and "Minimum amount" in res.text
    assert client.post("/api/rules", json={**body, "amount_min_cents": 100, "amount_max_cents": 100}).status_code == 201


def test_create_validation(client):
    assert client.post("/api/rules", json=NEW).status_code == 422  # no action
    assert client.post("/api/rules", json={**NEW, "contains_text": ""}).status_code == 422
    assert client.post("/api/rules", json={**NEW, "set_category_id": 9999}).status_code == 404


def test_rules_reject_blank_pattern(client, db):
    body = {**NEW, "contains_text": "   ", "set_category_id": category(db, "Dining").id}
    assert client.post("/api/rules", json=body).status_code == 422


def test_update_and_delete(client, db):
    rule = client.post("/api/rules", json={**NEW, "set_merchant": "Zed"}).json()
    updated = client.patch(f"/api/rules/{rule['id']}", json={**NEW, "contains_text": "zzz", "set_merchant": "Zed 2"}).json()
    assert (updated["contains_text"], updated["set_merchant"], updated["priority"]) == ("zzz", "Zed 2", rule["priority"])
    assert client.delete(f"/api/rules/{rule['id']}").status_code == 204
    assert client.patch(f"/api/rules/{rule['id']}", json={**NEW, "set_merchant": "x"}).status_code == 404


def test_reorder(client):
    ids = [r["id"] for r in client.get("/api/rules").json()]
    reordered = client.post("/api/rules/reorder", json={"ids": list(reversed(ids))}).json()
    assert [r["id"] for r in reordered] == list(reversed(ids))
    assert client.post("/api/rules/reorder", json={"ids": ids[:-1]}).status_code == 422


def test_apply_dry_run_then_apply(client, db):
    make_txn(db, make_account(db), -100, raw_description="ZZQ ONE", merchant="Zzq One")
    client.post("/api/rules", json={**NEW, "set_category_id": category(db, "Dining").id})
    assert client.post("/api/rules/apply", params={"dry_run": True}).json() == {"changed": 1}
    assert client.post("/api/rules/apply").json() == {"changed": 1}
    assert client.post("/api/rules/apply", params={"dry_run": True}).json() == {"changed": 0}
