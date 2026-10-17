"""Pair opposite-amount transactions between owned accounts (FR-TXN-07)."""
import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Category, Transaction

WINDOW_DAYS = 5
TRANSFER = "Transfer"
CARD_PAYMENT = "Credit Card Payment"


def _candidates(db: Session, txn: Transaction) -> list[Transaction]:
    window = dt.timedelta(days=WINDOW_DAYS)
    return list(
        db.scalars(
            select(Transaction).where(
                Transaction.id != txn.id,
                Transaction.account_id != txn.account_id,
                Transaction.amount_cents == -txn.amount_cents,
                Transaction.transfer_pair_id.is_(None),
                Transaction.posted_date.between(txn.posted_date - window, txn.posted_date + window),
            )
        ).all()
    )


def detect_transfers(db: Session, new_txns: list[Transaction]) -> int:
    """Link each new txn to its single opposite-amount twin in another account within 5 days."""
    category_ids = dict(db.execute(select(Category.name, Category.id).where(Category.name.in_((TRANSFER, CARD_PAYMENT)))).all())
    paired = 0
    for txn in new_txns:
        if txn.transfer_pair_id is not None or txn.amount_cents == 0:
            continue
        candidates = _candidates(db, txn)
        # none or ambiguous from either side: leave for the user
        if len(candidates) != 1 or _candidates(db, candidates[0]) != [txn]:
            continue
        other = candidates[0]
        txn.transfer_pair_id, other.transfer_pair_id = other.id, txn.id
        name = CARD_PAYMENT if "credit" in (txn.account.type, other.account.type) else TRANSFER
        for side in (txn, other):
            if side.category_source != "user" and name in category_ids:
                side.category_id, side.category_source = category_ids[name], "rule"
        db.flush()
        paired += 1
    return paired


def unlink(db: Session, txn: Transaction) -> None:
    """Undo a pair. Non-user categories go back to uncategorized and unreviewed so the review queue picks them up."""
    other = db.get(Transaction, txn.transfer_pair_id) if txn.transfer_pair_id else None
    for side in (txn, other):
        if side is None:
            continue
        side.transfer_pair_id = None
        if side.category_source != "user":
            side.category_id, side.category_source = None, "none"
            side.reviewed_at = None
