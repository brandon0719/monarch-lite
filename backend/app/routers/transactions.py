"""FR-TXN-01..04, FR-TXN-07 unlink."""
import datetime as dt
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.orm import Session, contains_eager, joinedload, selectinload

from ..db import get_db
from ..models import Account, Category, Tag, Transaction, utcnow
from ..services.tags import get_or_create_tag
from ..services.transfers import unlink
from .category_budgets import MAX_AMOUNT_CENTS
from .params import MAX_ID, Id, IdBody, OptionalIdQuery

router = APIRouter(prefix="/api/transactions", tags=["transactions"])
AmountQuery = Annotated[int | None, Query(ge=-MAX_AMOUNT_CENTS, le=MAX_AMOUNT_CENTS)]


class TagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str


class TxnOut(BaseModel):
    id: int
    account_id: int
    account_name: str
    posted_date: dt.date
    amount_cents: int
    raw_description: str
    merchant: str
    category_id: int | None
    category_name: str | None
    category_source: str
    notes: str | None
    tags: list[TagOut]
    reviewed_at: dt.datetime | None
    transfer_pair_id: int | None


class TxnPage(BaseModel):
    items: list[TxnOut]
    next_cursor: str | None
    total: int


class TxnPatch(BaseModel):
    category_id: IdBody | None = None
    merchant: str | None = None
    notes: str | None = None
    tag_names: list[str] | None = None
    reviewed: bool | None = None

    @field_validator("merchant")
    @classmethod
    def strip_merchant(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("merchant cannot be blank")
        return value


class ReviewIn(BaseModel):
    ids: list[IdBody]


def to_out(t: Transaction) -> TxnOut:
    return TxnOut(
        id=t.id,
        account_id=t.account_id,
        account_name=t.account.name,
        posted_date=t.posted_date,
        amount_cents=t.amount_cents,
        raw_description=t.raw_description,
        merchant=t.merchant,
        category_id=t.category_id,
        category_name=t.category.name if t.category else None,
        category_source=t.category_source,
        notes=t.notes,
        tags=[TagOut.model_validate(tag) for tag in t.tags],
        reviewed_at=t.reviewed_at,
        transfer_pair_id=t.transfer_pair_id,
    )


def _parse_cursor(cursor: str) -> tuple[dt.date, int]:
    try:
        day, txn_id = cursor.split(":")
        day, txn_id = dt.date.fromisoformat(day), int(txn_id)
        if not 1 <= txn_id <= MAX_ID:
            raise ValueError
        return day, txn_id
    except ValueError:
        raise HTTPException(422, "Invalid cursor") from None


@router.get("", response_model=TxnPage)
def list_transactions(
    start: dt.date | None = None,
    end: dt.date | None = None,
    account_id: OptionalIdQuery = None,
    category_id: OptionalIdQuery = None,
    uncategorized: bool = False,
    min_cents: AmountQuery = None,
    max_cents: AmountQuery = None,
    q: str | None = None,
    merchant: str | None = None,
    tag_id: OptionalIdQuery = None,
    needs_review: bool = False,
    cursor: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    conds = []
    if start:
        conds.append(Transaction.posted_date >= start)
    if end:
        conds.append(Transaction.posted_date <= end)
    if account_id is not None:
        conds.append(Transaction.account_id == account_id)
    else:
        conds.append(Account.is_hidden.is_(False))
    if category_id is not None:
        conds.append(Transaction.category_id == category_id)
    if uncategorized:
        conds.append(Transaction.category_id.is_(None))
    if min_cents is not None:
        conds.append(Transaction.amount_cents >= min_cents)
    if max_cents is not None:
        conds.append(Transaction.amount_cents <= max_cents)
    if q:
        like = f"%{q}%"
        conds.append(or_(Transaction.merchant.ilike(like), Transaction.raw_description.ilike(like), Transaction.notes.ilike(like)))
    if merchant is not None:
        conds.append(Transaction.merchant == merchant)
    if tag_id is not None:
        conds.append(Transaction.tags.any(Tag.id == tag_id))
    if needs_review:
        conds.append(Transaction.reviewed_at.is_(None))

    total = db.scalar(select(func.count(Transaction.id)).join(Transaction.account).where(*conds))
    stmt = (
        select(Transaction)
        .join(Transaction.account)
        .where(*conds)
        .options(contains_eager(Transaction.account), joinedload(Transaction.category), selectinload(Transaction.tags))
    )
    if cursor:
        day, txn_id = _parse_cursor(cursor)
        stmt = stmt.where(or_(Transaction.posted_date < day, and_(Transaction.posted_date == day, Transaction.id < txn_id)))
    rows = db.scalars(stmt.order_by(Transaction.posted_date.desc(), Transaction.id.desc()).limit(limit + 1)).unique().all()
    next_cursor = f"{rows[limit - 1].posted_date.isoformat()}:{rows[limit - 1].id}" if len(rows) > limit else None
    return TxnPage(items=[to_out(t) for t in rows[:limit]], next_cursor=next_cursor, total=total)


@router.patch("/{txn_id}", response_model=TxnOut)
def patch_transaction(txn_id: Id, body: TxnPatch, db: Session = Depends(get_db)):
    txn = db.get(Transaction, txn_id)
    if txn is None:
        raise HTTPException(404, "Transaction not found")
    data = body.model_dump(exclude_unset=True)
    if "category_id" in data:
        if data["category_id"] is not None and db.get(Category, data["category_id"]) is None:
            raise HTTPException(404, "Category not found")
        txn.category_id, txn.category_source = data["category_id"], "user"
    if data.get("merchant") is not None:
        txn.merchant, txn.merchant_locked = data["merchant"], True
    if "notes" in data:
        txn.notes = data["notes"] or None
    if data.get("tag_names") is not None:
        names = dict.fromkeys(n.strip() for n in data["tag_names"] if n.strip())
        txn.tags = [get_or_create_tag(db, name) for name in names]
    if data.get("reviewed") is not None:
        txn.reviewed_at = utcnow() if data["reviewed"] else None
    db.commit()
    db.refresh(txn)
    return to_out(txn)


@router.post("/review")
def mark_reviewed(body: ReviewIn, db: Session = Depends(get_db)) -> dict[str, int]:
    result = db.execute(
        update(Transaction)
        .where(Transaction.id.in_(body.ids), Transaction.reviewed_at.is_(None))
        .values(reviewed_at=utcnow())
    )
    db.commit()
    return {"updated": result.rowcount}


@router.delete("/{txn_id}/transfer", status_code=204)
def unlink_transfer(txn_id: Id, db: Session = Depends(get_db)) -> None:
    txn = db.get(Transaction, txn_id)
    if txn is None:
        raise HTTPException(404, "Transaction not found")
    if txn.transfer_pair_id is None:
        raise HTTPException(409, "Transaction is not part of a transfer")
    unlink(db, txn)
    db.commit()
