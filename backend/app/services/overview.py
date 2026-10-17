"""Overview numbers (UI refresh spec): balances, month spending, review counts. Integer cents only."""
import datetime as dt

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from ..models import Account, BalanceSnapshot, Category, SyncRun, Transaction

SPENDING_BUCKETS = ("needs", "wants", "other")  # other: counted as spent, outside the 50/30/20 meters
REVIEW_WINDOW_DAYS = 90
GROUPS = ("cash", "investments", "credit", "loans", "other")
GROUP_OF_TYPE = {"checking": "cash", "savings": "cash", "investment": "investments", "credit": "credit", "loan": "loans"}


def balances(db: Session) -> dict[str, int]:
    """Latest snapshot per open, visible account, summed by account group."""
    totals = dict.fromkeys(GROUPS, 0)
    latest = (
        select(BalanceSnapshot.account_id, func.max(BalanceSnapshot.date).label("day"))
        .group_by(BalanceSnapshot.account_id)
        .subquery()
    )
    rows = db.execute(
        select(Account.type, BalanceSnapshot.balance_cents)
        .join(BalanceSnapshot, BalanceSnapshot.account_id == Account.id)
        .join(latest, and_(latest.c.account_id == BalanceSnapshot.account_id, latest.c.day == BalanceSnapshot.date))
        .where(Account.closed_at.is_(None), Account.is_hidden.is_(False))
    )
    for account_type, cents in rows:
        totals[GROUP_OF_TYPE.get(account_type, "other")] += cents
    return totals


def month_range(month: str) -> tuple[dt.date, dt.date]:
    """'2026-10' -> (2026-10-01, 2026-11-01). Raises ValueError for anything else."""
    if len(month) != 7 or month[4] != "-":
        raise ValueError(month)
    start = dt.date.fromisoformat(f"{month}-01")
    end = (start.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    return start, end


def _spending_where(start: dt.date, end: dt.date) -> tuple:
    """Spending in [start, end) on visible accounts: spending-bucket rows plus uncategorized outflows."""
    return (
        Transaction.posted_date >= start,
        Transaction.posted_date < end,
        Account.is_hidden.is_(False),
        or_(
            Category.bucket.in_(SPENDING_BUCKETS),
            and_(Transaction.category_id.is_(None), Transaction.amount_cents < 0),
        ),
    )


def spending_by_category(db: Session, start: dt.date, end: dt.date) -> list[dict]:
    """Net outflow per spending category in [start, end), plus uncategorized outflows. Largest first."""
    rows = db.execute(
        select(Transaction.category_id, Category.name, Category.bucket, func.sum(Transaction.amount_cents))
        .join(Transaction.account)
        .outerjoin(Category, Category.id == Transaction.category_id)
        .where(*_spending_where(start, end))
        .group_by(Transaction.category_id, Category.name, Category.bucket)
    ).all()
    out = [
        {"category_id": cid, "name": name or "Uncategorized", "bucket": bucket, "cents": -total}
        for cid, name, bucket, total in rows if -total > 0
    ]
    return sorted(out, key=lambda r: (-r["cents"], r["name"]))


def spending_total(db: Session, start: dt.date, end: dt.date) -> int:
    """Net spend in [start, end): the UNCLAMPED sum, so a refund-heavy category reduces it, as the meters do."""
    return -db.scalar(
        select(func.coalesce(func.sum(Transaction.amount_cents), 0))
        .join(Transaction.account)
        .outerjoin(Category, Category.id == Transaction.category_id)
        .where(*_spending_where(start, end))
    )


def top_merchants(db: Session, start: dt.date, end: dt.date, limit: int = 10) -> list[dict]:
    """Merchants by net spend in [start, end), largest first; only those with net outflow and a name."""
    net = func.sum(Transaction.amount_cents)
    rows = db.execute(
        select(Transaction.merchant, net, func.count(Transaction.id))
        .join(Transaction.account)
        .outerjoin(Category, Category.id == Transaction.category_id)
        .where(*_spending_where(start, end), Transaction.merchant != "")
        .group_by(Transaction.merchant)
        .having(net < 0)
        .order_by(net, Transaction.merchant)
        .limit(limit)
    ).all()
    return [{"merchant": merchant, "cents": -cents, "count": count} for merchant, cents, count in rows]


def review_counts(db: Session, today: dt.date) -> tuple[int, int]:
    """(unreviewed, uncategorized) over the last 90 days on visible accounts."""
    base = (
        select(func.count(Transaction.id))
        .join(Transaction.account)
        .where(Account.is_hidden.is_(False), Transaction.posted_date >= today - dt.timedelta(days=REVIEW_WINDOW_DAYS))
    )
    return (
        db.scalar(base.where(Transaction.reviewed_at.is_(None))),
        db.scalar(base.where(Transaction.category_id.is_(None))),
    )


def last_synced(db: Session) -> dt.datetime | None:
    return db.scalar(select(func.max(SyncRun.finished_at)).where(SyncRun.status.in_(("success", "partial"))))
