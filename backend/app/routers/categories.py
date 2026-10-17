"""FR-CAT-01/02. DELETE with replacement_id doubles as merge."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Category, Rule, Transaction
from ..services.transfers import CARD_PAYMENT, TRANSFER

router = APIRouter(prefix="/api/categories", tags=["categories"])
Bucket = Literal["needs", "wants", "other", "savings", "income", "excluded"]
LOCKED = (TRANSFER, CARD_PAYMENT)  # transfer detection looks these up by name


def _strip_or_reject(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("cannot be blank")
    return value


class CategoryIn(BaseModel):
    name: str = Field(min_length=1)
    group_name: str = Field(min_length=1)
    bucket: Bucket

    @field_validator("name", "group_name")
    @classmethod
    def _no_blank(cls, value: str) -> str:
        return _strip_or_reject(value)


class CategoryPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    group_name: str | None = Field(default=None, min_length=1)
    bucket: Bucket | None = None

    @field_validator("name", "group_name")
    @classmethod
    def _no_blank(cls, value: str | None) -> str | None:
        return None if value is None else _strip_or_reject(value)


class CategoryOut(BaseModel):
    id: int
    name: str
    group_name: str
    bucket: str
    locked: bool


def _out(category: Category) -> CategoryOut:
    return CategoryOut(
        id=category.id,
        name=category.name,
        group_name=category.group_name,
        bucket=category.bucket,
        locked=category.name in LOCKED,
    )


def _commit_or_409(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A category with that name already exists") from None


def _get(db: Session, category_id: int) -> Category:
    category = db.get(Category, category_id)
    if category is None:
        raise HTTPException(404, "Category not found")
    return category


@router.get("", response_model=list[CategoryOut])
def list_categories(db: Session = Depends(get_db)):
    return [_out(c) for c in db.scalars(select(Category).order_by(Category.group_name, Category.name))]


@router.post("", response_model=CategoryOut, status_code=201)
def create_category(body: CategoryIn, db: Session = Depends(get_db)):
    category = Category(name=body.name.strip(), group_name=body.group_name.strip(), bucket=body.bucket)
    db.add(category)
    _commit_or_409(db)
    return _out(category)


@router.patch("/{category_id}", response_model=CategoryOut)
def patch_category(category_id: int, body: CategoryPatch, db: Session = Depends(get_db)):
    category = _get(db, category_id)
    if category.name in LOCKED and body.name is not None and body.name != category.name:
        raise HTTPException(409, "This category is used by transfer detection and can't be renamed")
    for key, value in body.model_dump(exclude_unset=True, exclude_none=True).items():
        setattr(category, key, value.strip() if isinstance(value, str) else value)
    _commit_or_409(db)
    return _out(category)


@router.delete("/{category_id}", status_code=204)
def delete_category(category_id: int, replacement_id: int = Query(...), db: Session = Depends(get_db)) -> None:
    if replacement_id == category_id:
        raise HTTPException(422, "Pick a different category to move transactions to")
    source = _get(db, category_id)
    if source.name in LOCKED:
        raise HTTPException(409, "This category is used by transfer detection and can't be deleted")
    target = _get(db, replacement_id)
    db.execute(update(Transaction).where(Transaction.category_id == source.id).values(category_id=target.id))
    db.execute(update(Rule).where(Rule.set_category_id == source.id).values(set_category_id=target.id))
    db.delete(source)
    db.commit()
