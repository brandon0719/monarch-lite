"""M1 schema. Money is integer cents; datetimes are naive UTC."""
import datetime as dt

from sqlalchemy import Column, ForeignKey, Table, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

ACCOUNT_TYPES = ("checking", "savings", "credit", "investment", "loan", "other")
BUCKETS = ("needs", "wants", "other", "savings", "income", "excluded")


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC).replace(tzinfo=None)


transaction_tags = Table(
    "transaction_tags",
    Base.metadata,
    Column("transaction_id", ForeignKey("transactions.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    external_id: Mapped[str] = mapped_column(unique=True)
    institution: Mapped[str]
    name: Mapped[str]
    type: Mapped[str] = mapped_column(default="other")
    is_hidden: Mapped[bool] = mapped_column(default=False)
    is_manual: Mapped[bool] = mapped_column(default=False)  # owner-entered balance; sync never touches it
    closed_at: Mapped[dt.date | None]
    last_synced_at: Mapped[dt.datetime | None]
    last_error: Mapped[str | None]


class BalanceSnapshot(Base):
    __tablename__ = "balance_snapshots"
    __table_args__ = (UniqueConstraint("account_id", "date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    date: Mapped[dt.date]
    balance_cents: Mapped[int]

    account: Mapped[Account] = relationship()


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)
    group_name: Mapped[str]
    bucket: Mapped[str]  # one of BUCKETS


class CategoryBudget(Base):
    """A category's monthly budget from start_month on, until a later row (M2 round 2). None = no budget."""

    __tablename__ = "category_budgets"
    __table_args__ = (UniqueConstraint("category_id", "start_month"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id", ondelete="CASCADE"), index=True)
    start_month: Mapped[str]  # 'YYYY-MM'; sorts correctly as text
    amount_cents: Mapped[int | None]


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (UniqueConstraint("account_id", "external_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    # Bank data: never written after insert (NFR-DATA-02).
    external_id: Mapped[str]
    posted_date: Mapped[dt.date] = mapped_column(index=True)
    amount_cents: Mapped[int]
    raw_description: Mapped[str]
    raw_payee: Mapped[str | None]
    raw_memo: Mapped[str | None]
    # Derived or edited.
    merchant: Mapped[str] = mapped_column(default="")
    merchant_locked: Mapped[bool] = mapped_column(default=False)
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id", ondelete="SET NULL"), index=True)
    category_source: Mapped[str] = mapped_column(default="none")  # none | rule | user
    notes: Mapped[str | None]
    reviewed_at: Mapped[dt.datetime | None] = mapped_column(index=True)
    transfer_pair_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id", ondelete="SET NULL"))
    created_at: Mapped[dt.datetime] = mapped_column(default=utcnow)

    account: Mapped[Account] = relationship()
    category: Mapped[Category | None] = relationship()
    tags: Mapped[list[Tag]] = relationship(secondary=transaction_tags)


class Rule(Base):
    __tablename__ = "rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    priority: Mapped[int] = mapped_column(index=True)
    contains_text: Mapped[str]
    account_id: Mapped[int | None] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"))
    amount_min_cents: Mapped[int | None]
    amount_max_cents: Mapped[int | None]
    set_category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id", ondelete="CASCADE"))
    set_merchant: Mapped[str | None]
    add_tag_id: Mapped[int | None] = mapped_column(ForeignKey("tags.id", ondelete="CASCADE"))

    add_tag: Mapped[Tag | None] = relationship()


class SyncRun(Base):
    __tablename__ = "sync_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[dt.datetime] = mapped_column(default=utcnow)
    finished_at: Mapped[dt.datetime | None]
    status: Mapped[str] = mapped_column(default="running")  # running | success | partial | failed
    accounts_ok: Mapped[int] = mapped_column(default=0)
    accounts_stale: Mapped[int] = mapped_column(default=0)
    txns_added: Mapped[int] = mapped_column(default=0)
    error: Mapped[str | None]


class BudgetSettings(Base):
    """Single row (id=1): monthly take-home and the 50/30/20 split (M2 spec)."""

    __tablename__ = "budget_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    take_home_cents: Mapped[int | None]
    needs_pct: Mapped[int] = mapped_column(default=50)
    wants_pct: Mapped[int] = mapped_column(default=30)
    savings_pct: Mapped[int] = mapped_column(default=20)
    updated_at: Mapped[dt.datetime] = mapped_column(default=utcnow, onupdate=utcnow)


class RecurringItem(Base):
    """An expected bill or income on a schedule (M3 round 1). amount_cents is signed: bills < 0, income > 0."""

    __tablename__ = "recurring_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    merchant: Mapped[str]  # matches Transaction.merchant exactly
    name: Mapped[str]
    amount_cents: Mapped[int]
    cadence: Mapped[str]  # weekly | monthly | yearly
    anchor_date: Mapped[dt.date]
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id", ondelete="SET NULL"))
    created_at: Mapped[dt.datetime] = mapped_column(default=utcnow)


class RecurringDismissal(Base):
    """A merchant the owner dismissed, so it is never suggested again."""

    __tablename__ = "recurring_dismissals"

    merchant: Mapped[str] = mapped_column(primary_key=True)
    dismissed_at: Mapped[dt.datetime] = mapped_column(default=utcnow)


class Goal(Base):
    """A savings goal (M3 round 2): progress from linked account balances or a manual contribution log."""

    __tablename__ = "goals"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    target_cents: Mapped[int]
    target_date: Mapped[dt.date | None]
    kind: Mapped[str]  # linked | manual; fixed at creation
    created_at: Mapped[dt.datetime] = mapped_column(default=utcnow)

    links: Mapped[list["GoalAccount"]] = relationship(cascade="all, delete-orphan")
    contributions: Mapped[list["GoalContribution"]] = relationship(
        cascade="all, delete-orphan",
        order_by=lambda: [GoalContribution.date.desc(), GoalContribution.id.desc()],
    )


class GoalAccount(Base):
    """Links an account to a goal; an account belongs to at most one goal."""

    __tablename__ = "goal_accounts"

    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), primary_key=True)
    goal_id: Mapped[int] = mapped_column(ForeignKey("goals.id", ondelete="CASCADE"), index=True)

    account: Mapped[Account] = relationship()


class GoalContribution(Base):
    """A manual deposit (> 0) or withdrawal (< 0) toward a manual goal."""

    __tablename__ = "goal_contributions"

    id: Mapped[int] = mapped_column(primary_key=True)
    goal_id: Mapped[int] = mapped_column(ForeignKey("goals.id", ondelete="CASCADE"), index=True)
    date: Mapped[dt.date]
    amount_cents: Mapped[int]
    note: Mapped[str | None]


class Holding(Base):
    """An investment position as SimpleFIN last reported it (M4); an account's set is replaced on every sync."""

    __tablename__ = "holdings"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), index=True)
    symbol: Mapped[str]
    description: Mapped[str]
    shares: Mapped[str]  # exact decimal text from SimpleFIN
    market_value_cents: Mapped[int]
    cost_basis_cents: Mapped[int | None]  # None when SimpleFIN reports 0 (unknown)
    as_of: Mapped[dt.date]

    account: Mapped[Account] = relationship()


class AssetClass(Base):
    """Owner's override of a symbol's asset class (M4); symbols without a row use the default."""

    __tablename__ = "asset_classes"

    symbol: Mapped[str] = mapped_column(primary_key=True)
    asset_class: Mapped[str]  # stocks | bonds | cash


DEFAULT_THRESHOLD = 5  # allocation drift alert, in percentage points


class AllocationTargets(Base):
    """Single row (id=1): target split across asset classes and the drift alert threshold (M4)."""

    __tablename__ = "allocation_targets"

    id: Mapped[int] = mapped_column(primary_key=True)
    stocks_pct: Mapped[int]
    bonds_pct: Mapped[int]
    cash_pct: Mapped[int]
    drift_threshold: Mapped[int] = mapped_column(default=DEFAULT_THRESHOLD)
