"""FR-TXN-05 rule management."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Account, Category, Rule
from ..services.rules import apply_all, load_rules
from ..services.tags import get_or_create_tag
from .category_budgets import MAX_AMOUNT_CENTS
from .params import Id, IdBody

router = APIRouter(prefix="/api/rules", tags=["rules"])


class RuleIn(BaseModel):
    contains_text: str = Field(min_length=1)
    account_id: IdBody | None = None
    amount_min_cents: int | None = Field(default=None, ge=-MAX_AMOUNT_CENTS, le=MAX_AMOUNT_CENTS)
    amount_max_cents: int | None = Field(default=None, ge=-MAX_AMOUNT_CENTS, le=MAX_AMOUNT_CENTS)
    set_category_id: IdBody | None = None
    set_merchant: str | None = None
    add_tag_name: str | None = None

    @field_validator("contains_text")
    @classmethod
    def _no_blank_pattern(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("contains_text cannot be blank")
        return value

    @model_validator(mode="after")
    def _min_not_above_max(self):
        low, high = self.amount_min_cents, self.amount_max_cents
        if low is not None and high is not None and low > high:
            raise ValueError("Minimum amount can't be greater than maximum")
        return self

    @model_validator(mode="after")
    def _needs_an_action(self):
        if self.set_category_id is None and not (self.set_merchant or "").strip() and not (self.add_tag_name or "").strip():
            raise ValueError("A rule needs at least one action: set a category, rename the merchant, or add a tag")
        return self


class RuleOut(BaseModel):
    id: int
    priority: int
    contains_text: str
    account_id: int | None
    amount_min_cents: int | None
    amount_max_cents: int | None
    set_category_id: int | None
    set_merchant: str | None
    add_tag_name: str | None


class ReorderIn(BaseModel):
    ids: list[IdBody]


def _out(rule: Rule) -> RuleOut:
    return RuleOut(
        id=rule.id,
        priority=rule.priority,
        contains_text=rule.contains_text,
        account_id=rule.account_id,
        amount_min_cents=rule.amount_min_cents,
        amount_max_cents=rule.amount_max_cents,
        set_category_id=rule.set_category_id,
        set_merchant=rule.set_merchant,
        add_tag_name=rule.add_tag.name if rule.add_tag else None,
    )


def _fill(db: Session, rule: Rule, body: RuleIn) -> None:
    if body.set_category_id is not None and db.get(Category, body.set_category_id) is None:
        raise HTTPException(404, "Category not found")
    if body.account_id is not None and db.get(Account, body.account_id) is None:
        raise HTTPException(404, "Account not found")
    rule.contains_text = body.contains_text.strip()
    rule.account_id = body.account_id
    rule.amount_min_cents = body.amount_min_cents
    rule.amount_max_cents = body.amount_max_cents
    rule.set_category_id = body.set_category_id
    rule.set_merchant = (body.set_merchant or "").strip() or None
    tag_name = (body.add_tag_name or "").strip()
    rule.add_tag = get_or_create_tag(db, tag_name) if tag_name else None


def _get(db: Session, rule_id: int) -> Rule:
    rule = db.get(Rule, rule_id)
    if rule is None:
        raise HTTPException(404, "Rule not found")
    return rule


@router.get("", response_model=list[RuleOut])
def list_rules(db: Session = Depends(get_db)):
    return [_out(r) for r in load_rules(db)]


@router.post("", response_model=RuleOut, status_code=201)
def create_rule(body: RuleIn, db: Session = Depends(get_db)):
    # New rules go first: a rule you just wrote is usually more specific than the ones already there.
    first = db.scalar(select(func.min(Rule.priority)))
    rule = Rule(priority=first - 1 if first is not None else 0)
    _fill(db, rule, body)
    db.add(rule)
    db.commit()
    return _out(rule)


@router.patch("/{rule_id}", response_model=RuleOut)
def update_rule(rule_id: Id, body: RuleIn, db: Session = Depends(get_db)):
    rule = _get(db, rule_id)
    _fill(db, rule, body)
    db.commit()
    return _out(rule)


@router.delete("/{rule_id}", status_code=204)
def delete_rule(rule_id: Id, db: Session = Depends(get_db)) -> None:
    db.delete(_get(db, rule_id))
    db.commit()


@router.post("/reorder", response_model=list[RuleOut])
def reorder_rules(body: ReorderIn, db: Session = Depends(get_db)):
    rules = {r.id: r for r in load_rules(db)}
    if sorted(body.ids) != sorted(rules):
        raise HTTPException(422, "ids must list every rule exactly once")
    for priority, rule_id in enumerate(body.ids):
        rules[rule_id].priority = priority
    db.commit()
    return [_out(rules[i]) for i in body.ids]


@router.post("/apply")
def apply_rules(dry_run: bool = False, db: Session = Depends(get_db)) -> dict[str, int]:
    return {"changed": apply_all(db, dry_run)}
