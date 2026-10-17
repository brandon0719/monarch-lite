import pytest

from app.models import Rule, Tag
from app.services.rules import apply_all, apply_to, evaluate
from tests.conftest import category, make_account, make_txn


def test_first_matching_category_wins(db):
    txn = make_txn(db, make_account(db), -450, raw_description="ZZQ COFFEE BAR")
    rules = [
        Rule(priority=0, contains_text="zzq", set_category_id=category(db, "Dining").id),
        Rule(priority=1, contains_text="coffee", set_category_id=category(db, "Shopping").id),
    ]
    assert evaluate(rules, txn).category_id == category(db, "Dining").id


def test_tags_from_every_match_accumulate(db):
    txn = make_txn(db, make_account(db), -450, raw_description="ZZQ COFFEE BAR")
    a, b = Tag(name="a"), Tag(name="b")
    db.add_all([a, b])
    db.commit()
    rules = [Rule(priority=0, contains_text="zzq", add_tag_id=a.id), Rule(priority=1, contains_text="coffee", add_tag_id=b.id)]
    assert evaluate(rules, txn).tag_ids == {a.id, b.id}


def test_account_and_amount_conditions(db):
    checking, card = make_account(db), make_account(db, name="Card", type="credit")
    small = make_txn(db, checking, -500, raw_description="ZZQ")
    big = make_txn(db, checking, -50000, raw_description="ZZQ")
    other_account = make_txn(db, card, -500, raw_description="ZZQ")
    rule = Rule(priority=0, contains_text="zzq", account_id=checking.id, amount_min_cents=-1000, set_merchant="Matched")
    assert [evaluate([rule], t).merchant for t in (small, big, other_account)] == ["Matched", None, None]


def test_match_is_case_insensitive_and_checks_payee(db):
    txn = make_txn(db, make_account(db), -100, raw_description="ACH 123", raw_payee="Puget Sound Energy")
    assert evaluate([Rule(priority=0, contains_text="PUGET", set_merchant="PSE")], txn).merchant == "PSE"


def test_apply_sets_rule_category_and_cleans_merchant(db):
    txn = make_txn(db, make_account(db), -450, raw_description="SQ *BLUE BOTTLE 0423", merchant="")
    rules = [Rule(priority=0, contains_text="blue bottle", set_category_id=category(db, "Dining").id)]
    assert apply_to(db, txn, rules) is True
    assert (txn.category_id, txn.category_source, txn.merchant) == (category(db, "Dining").id, "rule", "Blue Bottle")


def test_apply_never_changes_a_user_category(db):
    groceries = category(db, "Groceries")
    txn = make_txn(db, make_account(db), -450, raw_description="ZZQ", category_id=groceries.id, category_source="user")
    apply_to(db, txn, [Rule(priority=0, contains_text="zzq", set_category_id=category(db, "Dining").id)])
    assert (txn.category_id, txn.category_source) == (groceries.id, "user")


def test_apply_never_changes_a_locked_merchant(db):
    txn = make_txn(db, make_account(db), -450, raw_description="ZZQ", merchant="My Name", merchant_locked=True)
    apply_to(db, txn, [Rule(priority=0, contains_text="zzq", set_merchant="Rule Name")])
    assert txn.merchant == "My Name"


def test_apply_leaves_transfer_category_alone(db):
    a, b = make_account(db), make_account(db, name="Savings", type="savings")
    t1, t2 = make_txn(db, a, -100, raw_description="ZZQ"), make_txn(db, b, 100, raw_description="ZZQ")
    t1.transfer_pair_id, t1.category_id, t1.category_source = t2.id, category(db, "Transfer").id, "rule"
    db.commit()
    apply_to(db, t1, [Rule(priority=0, contains_text="zzq", set_category_id=category(db, "Dining").id)])
    assert t1.category_id == category(db, "Transfer").id


def test_no_match_leaves_category_none(db):
    txn = make_txn(db, make_account(db), -100, raw_description="ZZQ UNKNOWN")
    apply_to(db, txn, [])
    assert (txn.category_id, txn.category_source) == (None, "none")


def test_apply_all_dry_run_counts_without_writing(db):
    account = make_account(db)
    t1 = make_txn(db, account, -100, raw_description="ZZQ ONE")
    t2 = make_txn(db, account, -200, raw_description="ZZQ TWO")
    db.add(Rule(priority=-1, contains_text="zzq", set_category_id=category(db, "Dining").id))
    db.commit()
    assert apply_all(db, dry_run=True) == 2
    db.refresh(t1)
    assert t1.category_id is None
    assert apply_all(db, dry_run=False) == 2
    db.refresh(t1)
    db.refresh(t2)
    assert t1.category_id == t2.category_id == category(db, "Dining").id
    assert apply_all(db, dry_run=True) == 0


def test_apply_all_clears_a_rule_category_whose_rule_is_gone(db):
    txn = make_txn(
        db, make_account(db), -100, raw_description="ZZQ", merchant="Zzq",
        category_id=category(db, "Dining").id, category_source="rule",
    )
    assert apply_all(db, dry_run=False) == 1
    db.refresh(txn)
    assert (txn.category_id, txn.category_source) == (None, "none")


@pytest.mark.parametrize("pattern", ["", "   "])
def test_blank_pattern_never_matches(db, pattern):
    txn = make_txn(db, make_account(db), -100, raw_description="ZZQ")
    assert evaluate([Rule(priority=0, contains_text=pattern, set_merchant="Everything")], txn).merchant is None
