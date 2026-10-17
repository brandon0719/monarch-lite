import datetime as dt

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app import seed
from app.models import BUCKETS, Category, Rule
from tests.conftest import make_account, make_txn


def test_seed_creates_categories_and_rules(db):
    names = set(db.scalars(select(Category.name)))
    assert {"Rent", "Groceries", "Paycheck", "Transfer", "Credit Card Payment"} <= names
    assert db.scalar(select(func.count(Category.id))) == len(seed.CATEGORIES)
    assert db.scalar(select(func.count(Rule.id))) == len(seed.KEYWORD_RULES)


def test_seed_is_idempotent(db):
    seed.seed_defaults(db)
    assert db.scalar(select(func.count(Category.id))) == len(seed.CATEGORIES)


def test_payroll_outranks_amazon_and_card_payments_outrank_autopay(db):
    texts = [r.contains_text for r in db.scalars(select(Rule).order_by(Rule.priority))]
    assert texts.index("payroll") < texts.index("amazon")
    assert texts.index("credit crd") < texts.index("autopay")
    assert "rent" not in texts


def test_every_bucket_is_valid(db):
    assert set(db.scalars(select(Category.bucket))) <= set(BUCKETS)


def test_external_id_unique_per_account(db):
    account = make_account(db)
    make_txn(db, account, -100, dt.date(2026, 10, 1), external_id="x")
    with pytest.raises(IntegrityError):
        make_txn(db, account, -100, dt.date(2026, 10, 1), external_id="x")
