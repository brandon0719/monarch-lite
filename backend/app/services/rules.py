"""Rule evaluation and application (FR-TXN-05) plus merchant cleanup on apply (FR-TXN-06)."""
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..models import Rule, Tag, Transaction
from .merchant import clean


@dataclass
class Outcome:
    category_id: int | None = None
    merchant: str | None = None
    tag_ids: set[int] = field(default_factory=set)


def load_rules(db: Session) -> list[Rule]:
    return list(db.scalars(select(Rule).order_by(Rule.priority, Rule.id)))


def matches(rule: Rule, txn: Transaction) -> bool:
    haystack = f"{txn.raw_description} {txn.raw_payee or ''}".lower()
    needle = rule.contains_text.strip().lower()
    if not needle or needle not in haystack:
        return False
    if rule.account_id is not None and rule.account_id != txn.account_id:
        return False
    if rule.amount_min_cents is not None and txn.amount_cents < rule.amount_min_cents:
        return False
    if rule.amount_max_cents is not None and txn.amount_cents > rule.amount_max_cents:
        return False
    return True


def evaluate(rules: list[Rule], txn: Transaction) -> Outcome:
    """`rules` must be in priority order. First category/merchant wins; tags accumulate."""
    out = Outcome()
    for rule in rules:
        if not matches(rule, txn):
            continue
        if out.category_id is None and rule.set_category_id is not None:
            out.category_id = rule.set_category_id
        if out.merchant is None and rule.set_merchant:
            out.merchant = rule.set_merchant
        if rule.add_tag_id is not None:
            out.tag_ids.add(rule.add_tag_id)
    return out


def apply_to(db: Session, txn: Transaction, rules: list[Rule]) -> bool:
    """Make txn reflect the current rules. Never touches user categories, transfer pairs or locked merchants."""
    out = evaluate(rules, txn)
    changed = False
    if txn.category_source != "user" and txn.transfer_pair_id is None:
        new = (out.category_id, "rule" if out.category_id is not None else "none")
        if (txn.category_id, txn.category_source) != new:
            txn.category_id, txn.category_source = new
            changed = True
    if not txn.merchant_locked:
        merchant = out.merchant or clean(txn.raw_description, txn.raw_payee)
        if txn.merchant != merchant:
            txn.merchant = merchant
            changed = True
    missing = out.tag_ids - {t.id for t in txn.tags}
    if missing:
        txn.tags.extend(db.get(Tag, tag_id) for tag_id in missing)
        changed = True
    return changed


def apply_all(db: Session, dry_run: bool) -> int:
    """Re-run every rule over every transaction; returns how many change. Dry run rolls back."""
    rules = load_rules(db)
    txns = db.scalars(select(Transaction).options(selectinload(Transaction.tags))).all()
    changed = sum(apply_to(db, txn, rules) for txn in txns)
    if dry_run:
        db.rollback()
    else:
        db.commit()
    return changed
