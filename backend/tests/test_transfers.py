import datetime as dt

import pytest

from app.services.transfers import detect_transfers, unlink
from tests.conftest import category, make_account, make_txn

D = dt.date(2026, 10, 1)


def test_pairs_a_single_opposite_match(db):
    checking, savings = make_account(db), make_account(db, name="Savings", type="savings")
    out = make_txn(db, checking, -50000, D)
    into = make_txn(db, savings, 50000, D + dt.timedelta(days=2))
    assert detect_transfers(db, [out]) == 1
    assert (out.transfer_pair_id, into.transfer_pair_id) == (into.id, out.id)
    assert out.category_id == into.category_id == category(db, "Transfer").id
    assert out.category_source == into.category_source == "rule"


def test_credit_side_uses_card_payment(db):
    checking, card = make_account(db), make_account(db, name="Card", type="credit")
    out = make_txn(db, checking, -12000, D)
    make_txn(db, card, 12000, D)
    detect_transfers(db, [out])
    assert out.category_id == category(db, "Credit Card Payment").id


def test_ambiguous_match_is_left_alone(db):
    checking, savings = make_account(db), make_account(db, name="Savings", type="savings")
    out = make_txn(db, checking, -100, D)
    make_txn(db, savings, 100, D)
    make_txn(db, savings, 100, D + dt.timedelta(days=1))
    assert detect_transfers(db, [out]) == 0
    assert out.transfer_pair_id is None


def test_outside_window_or_same_account_is_not_paired(db):
    checking, savings = make_account(db), make_account(db, name="Savings", type="savings")
    out = make_txn(db, checking, -100, D)
    make_txn(db, savings, 100, D + dt.timedelta(days=6))
    make_txn(db, checking, 100, D)
    assert detect_transfers(db, [out]) == 0


def test_user_category_is_kept_on_that_side(db):
    checking, savings = make_account(db), make_account(db, name="Savings", type="savings")
    out = make_txn(db, checking, -100, D)
    mine = category(db, "Savings Transfer")
    into = make_txn(db, savings, 100, D, category_id=mine.id, category_source="user")
    detect_transfers(db, [out])
    assert (into.category_id, into.category_source) == (mine.id, "user")
    assert out.category_id == category(db, "Transfer").id


def test_zero_amounts_are_ignored(db):
    checking, savings = make_account(db), make_account(db, name="Savings", type="savings")
    zero = make_txn(db, checking, 0, D)
    make_txn(db, savings, 0, D)
    assert detect_transfers(db, [zero]) == 0


def test_unlink_clears_both_and_resets_rule_categories(db):
    checking, savings = make_account(db), make_account(db, name="Savings", type="savings")
    out = make_txn(db, checking, -100, D)
    mine = category(db, "Savings Transfer")
    into = make_txn(db, savings, 100, D, category_id=mine.id, category_source="user")
    detect_transfers(db, [out])
    out.reviewed_at = into.reviewed_at = dt.datetime(2026, 10, 2, 9, 0)
    unlink(db, out)
    db.commit()
    assert out.transfer_pair_id is None and into.transfer_pair_id is None
    assert (out.category_id, out.category_source) == (None, "none")
    assert (into.category_id, into.category_source) == (mine.id, "user")
    assert out.reviewed_at is None  # back in "To review" with its category cleared
    assert into.reviewed_at == dt.datetime(2026, 10, 2, 9, 0)


@pytest.mark.parametrize("order", [(0, 1, 2), (1, 2, 0), (2, 0, 1)])
def test_ambiguity_is_order_independent(db, order):
    checking, savings = make_account(db), make_account(db, name="Savings", type="savings")
    txns = [make_txn(db, checking, -100, D), make_txn(db, savings, 100, D), make_txn(db, savings, 100, D + dt.timedelta(days=1))]
    assert detect_transfers(db, [txns[i] for i in order]) == 0
    assert all(t.transfer_pair_id is None for t in txns)
