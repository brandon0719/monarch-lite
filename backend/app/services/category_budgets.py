"""Per-category monthly budgets, in effect from a start month onward (M2 round 2 spec). Integer cents only."""
import datetime as dt

from sqlalchemy import and_, delete, func, select
from sqlalchemy.orm import Session

from ..models import Account, Category, CategoryBudget, Transaction
from .overview import SPENDING_BUCKETS


def in_effect(db: Session, month: str) -> dict[int, int]:
    """category_id -> amount for budgets in effect in `month`: each category's latest row with start_month <= month."""
    latest = (
        select(CategoryBudget.category_id, func.max(CategoryBudget.start_month).label("start"))
        .where(CategoryBudget.start_month <= month)
        .group_by(CategoryBudget.category_id)
        .subquery()
    )
    rows = db.execute(
        select(CategoryBudget.category_id, CategoryBudget.amount_cents).join(
            latest, and_(latest.c.category_id == CategoryBudget.category_id, latest.c.start == CategoryBudget.start_month)
        )
    )
    return {category_id: cents for category_id, cents in rows if cents is not None}


def net_by_category(db: Session, start: dt.date, end: dt.date) -> dict[int, int]:
    """Net outflow per budgetable category in [start, end) on visible accounts; refunds subtract."""
    rows = db.execute(
        select(Transaction.category_id, func.sum(Transaction.amount_cents))
        .join(Transaction.account)
        .join(Category, Category.id == Transaction.category_id)
        .where(
            Transaction.posted_date >= start,
            Transaction.posted_date < end,
            Account.is_hidden.is_(False),
            Category.bucket.in_(SPENDING_BUCKETS),
        )
        .group_by(Transaction.category_id)
    )
    return {category_id: -total for category_id, total in rows}


def set_from(db: Session, category_id: int, month: str, amount_cents: int | None) -> None:
    """Budget `amount_cents` from `month` onward, replacing this and any later change for the category."""
    db.execute(delete(CategoryBudget).where(CategoryBudget.category_id == category_id, CategoryBudget.start_month >= month))
    db.add(CategoryBudget(category_id=category_id, start_month=month, amount_cents=amount_cents))
    db.commit()
