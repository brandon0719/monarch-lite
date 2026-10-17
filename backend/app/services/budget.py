"""50/30/20 budget (rent counts in Needs) and cash flow (M2 spec). Integer cents only."""
import datetime as dt

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, aliased

from ..models import Account, BudgetSettings, Category, Transaction
from .overview import SPENDING_BUCKETS, month_range, spending_total

SETTINGS_ID = 1
CASH_TYPES = ("checking", "other")
SAVINGS_TYPES = ("savings", "investment")


def load_settings(db: Session) -> BudgetSettings:
    """The saved row, or unsaved defaults. Never writes."""
    return db.get(BudgetSettings, SETTINGS_ID) or BudgetSettings(
        id=SETTINGS_ID, take_home_cents=None, needs_pct=50, wants_pct=30, savings_pct=20
    )


def last_months(today: dt.date, count: int) -> list[str]:
    """['2026-10', '2026-09', ...] newest first, ending at today's month."""
    year, month, out = today.year, today.month, []
    for _ in range(count):
        out.append(f"{year:04d}-{month:02d}")
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    return out


def _in_range(start: dt.date, end: dt.date):
    return and_(Transaction.posted_date >= start, Transaction.posted_date < end, Account.is_hidden.is_(False))


def bucket_spending(db: Session, start: dt.date, end: dt.date) -> dict[str, int]:
    """Net outflow per spending bucket (needs/wants/other); refunds net out and may go negative."""
    totals = dict.fromkeys(SPENDING_BUCKETS, 0)
    rows = db.execute(
        select(Category.bucket, func.sum(Transaction.amount_cents))
        .join(Transaction.account)
        .join(Category, Category.id == Transaction.category_id)
        .where(_in_range(start, end), Category.bucket.in_(SPENDING_BUCKETS))
        .group_by(Category.bucket)
    ).all()
    for bucket, total in rows:
        totals[bucket] = -total
    return totals


def savings_moved(db: Session, start: dt.date, end: dt.date) -> int:
    """Money deliberately moved to savings; withdrawals count negative (see spec 'Savings rule')."""
    categorized = db.scalar(
        select(func.coalesce(func.sum(Transaction.amount_cents), 0))
        .join(Transaction.account)
        .join(Category, Category.id == Transaction.category_id)
        .where(_in_range(start, end), Category.bucket == "savings", Account.type.not_in(SAVINGS_TYPES))
    )
    partner = aliased(Transaction)
    partner_account = aliased(Account)
    paired = db.scalar(
        select(func.coalesce(func.sum(Transaction.amount_cents), 0))
        .join(Transaction.account)
        .join(partner, partner.id == Transaction.transfer_pair_id)
        .join(partner_account, partner_account.id == partner.account_id)
        .outerjoin(Category, Category.id == Transaction.category_id)
        .where(
            _in_range(start, end),
            Account.type.in_(CASH_TYPES),
            partner_account.type.in_(SAVINGS_TYPES),
            or_(Category.bucket.is_(None), Category.bucket == "excluded"),
        )
    )
    return -(categorized + paired)


def income_total(db: Session, start: dt.date, end: dt.date) -> int:
    return db.scalar(
        select(func.coalesce(func.sum(Transaction.amount_cents), 0))
        .join(Transaction.account)
        .join(Category, Category.id == Transaction.category_id)
        .where(_in_range(start, end), Category.bucket == "income")
    )


def spent_total(db: Session, start: dt.date, end: dt.date) -> int:
    """Same rule as the Overview's 'spent' tile."""
    return spending_total(db, start, end)
