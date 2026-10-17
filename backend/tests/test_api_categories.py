from sqlalchemy import select

from app.models import Rule
from tests.conftest import category, make_account, make_txn


def test_lists_seeded_categories(client):
    names = [c["name"] for c in client.get("/api/categories").json()]
    assert "Groceries" in names and "Transfer" in names


def test_create_and_duplicate(client):
    body = {"name": "Pets", "group_name": "Lifestyle", "bucket": "wants"}
    created = client.post("/api/categories", json=body)
    assert created.status_code == 201 and created.json()["name"] == "Pets"
    assert client.post("/api/categories", json=body).status_code == 409


def test_patch_and_validation(client, db):
    dining = category(db, "Dining")
    assert client.patch(f"/api/categories/{dining.id}", json={"bucket": "wants"}).json()["bucket"] == "wants"
    assert client.patch(f"/api/categories/{dining.id}", json={"bucket": "fun"}).status_code == 422
    assert client.patch("/api/categories/9999", json={"name": "x"}).status_code == 404


def test_categories_reject_blank_names(client, db):
    dining = category(db, "Dining")
    assert client.post("/api/categories", json={"name": "  ", "group_name": "Lifestyle", "bucket": "wants"}).status_code == 422
    assert client.patch(f"/api/categories/{dining.id}", json={"group_name": " "}).status_code == 422


def test_transfer_categories_are_locked(client, db):
    transfer, card = category(db, "Transfer"), category(db, "Credit Card Payment")
    assert client.patch(f"/api/categories/{transfer.id}", json={"name": "Moves"}).status_code == 409
    assert client.patch(f"/api/categories/{transfer.id}", json={"group_name": "Internal"}).json()["group_name"] == "Internal"
    assert client.delete(f"/api/categories/{card.id}", params={"replacement_id": transfer.id}).status_code == 409
    listed = {c["name"]: c["locked"] for c in client.get("/api/categories").json()}
    assert listed["Transfer"] and listed["Credit Card Payment"] and not listed["Dining"]


def test_delete_moves_transactions_and_rules(client, db):
    coffee = client.post("/api/categories", json={"name": "Coffee", "group_name": "Lifestyle", "bucket": "wants"}).json()
    txn = make_txn(db, make_account(db), -450, category_id=coffee["id"], category_source="user")
    db.add(Rule(priority=99, contains_text="espresso", set_category_id=coffee["id"]))
    db.commit()
    dining = category(db, "Dining")
    assert client.delete(f"/api/categories/{coffee['id']}", params={"replacement_id": dining.id}).status_code == 204
    db.refresh(txn)
    assert (txn.category_id, txn.category_source) == (dining.id, "user")
    assert db.scalar(select(Rule).where(Rule.contains_text == "espresso")).set_category_id == dining.id


def test_delete_requires_a_different_existing_replacement(client, db):
    dining = category(db, "Dining")
    assert client.delete(f"/api/categories/{dining.id}").status_code == 422
    assert client.delete(f"/api/categories/{dining.id}", params={"replacement_id": dining.id}).status_code == 422
    assert client.delete(f"/api/categories/{dining.id}", params={"replacement_id": 9999}).status_code == 404
