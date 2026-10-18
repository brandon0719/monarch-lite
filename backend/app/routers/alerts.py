"""FR-DASH-02: one list of open alerts from every source, minus the ones the owner dismissed."""
import datetime as dt
import hashlib
import logging

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Account, DismissedAlert, SyncRun, utcnow
from . import income, investments, recurring

router = APIRouter(prefix="/api/alerts", tags=["alerts"])
log = logging.getLogger("monarch-lite.alerts")
STALE_AFTER = dt.timedelta(hours=36)
KEY_MAX = 200


class AlertOut(BaseModel):
    key: str
    kind: str
    severity: str  # warn | info
    title: str
    detail: str
    link: str


class AlertsOut(BaseModel):
    alerts: list[AlertOut]
    unavailable: list[str]


class DismissIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    key: str = Field(min_length=1, max_length=KEY_MAX)


def _money(cents: int) -> str:
    return f"${abs(cents) / 100:,.2f}"


def _sync(db: Session) -> list[AlertOut]:
    out = []
    accounts = db.scalars(select(Account).where(Account.is_hidden.is_(False), Account.closed_at.is_(None),
                                                Account.last_error.is_not(None)))
    for a in accounts:
        digest = hashlib.sha1(a.last_error.encode()).hexdigest()[:10]
        out.append(AlertOut(key=f"sync:{a.id}:{digest}", kind="sync_error", severity="warn",
                            title=f"Sync error: {a.name}", detail=a.last_error, link="/accounts"))
    last_ok = db.scalar(select(func.max(SyncRun.finished_at)).where(SyncRun.status.in_(("success", "partial"))))
    if last_ok is None or utcnow() - last_ok > STALE_AFTER:
        when = last_ok.date().isoformat() if last_ok else "never"  # the key stays on the stored UTC date
        # Stored times are naive UTC; the owner reads the server's local date.
        shown = last_ok.replace(tzinfo=dt.UTC).astimezone().date().isoformat() if last_ok else "never"
        out.append(AlertOut(key=f"stale:{when}", kind="sync_stale", severity="warn",
                            title="Accounts haven't synced recently",
                            detail=f"Last successful sync: {shown}.", link="/settings"))
    return out


def _recurring(db: Session) -> list[AlertOut]:
    out = []
    for a in recurring.get_recurring(db).alerts:
        if a.kind == "price_increase":
            out.append(AlertOut(key=f"price:{a.item_id}:{a.previous_cents}:{a.latest_cents}", kind="price_increase", severity="info",
                                title=f"{a.name} went up: {_money(a.previous_cents)} → {_money(a.latest_cents)}",
                                detail=f"Charged on {a.date}.", link="/recurring"))
        else:  # no amount in the key (a varying bill must stay dismissed); the hash bounds the unbounded merchant
            merchant = hashlib.sha1(a.merchant.encode()).hexdigest()[:10]
            out.append(AlertOut(key=f"newrec:{merchant}:{'in' if a.amount_cents > 0 else 'out'}:{a.cadence}", kind="new_recurring",
                                severity="info", title=f"New recurring charge: {a.merchant}",
                                detail=f"{_money(a.amount_cents)} {a.cadence}.", link="/recurring"))
    return out


def _tax(db: Session) -> list[AlertOut]:
    est = income.tax_estimate(dt.date.today().year, db)
    if not est.alert:
        return []
    return [AlertOut(key=f"tax:{est.year}:{est.balance_cents // 50000}", kind="under_withholding", severity="warn",
                     title=f"Projected {est.year} under-withholding {_money(est.balance_cents)}",
                     detail=f"Consider setting aside {_money(est.balance_cents)}.", link="/income")]


def _allocation(db: Session) -> list[AlertOut]:
    out = []
    for c in investments.get_allocation(db).classes:
        if c.over and c.drift_pts is not None:
            side = "over" if c.drift_pts > 0 else "under"
            out.append(AlertOut(key=f"drift:{c.asset_class}:{side}:{int(abs(c.drift_pts) // 5)}", kind="allocation_drift",
                                severity="info", title=f"{c.asset_class.capitalize()} {side} target by {abs(c.drift_pts):g} pts",
                                detail=f"Target {c.target_pct}% · now {round(c.pct * 100)}%.", link="/networth"))
    return out


SOURCES = {"sync": _sync, "recurring": _recurring, "tax": _tax, "allocation": _allocation}


@router.get("", response_model=AlertsOut)
def list_alerts(db: Session = Depends(get_db)):
    dismissed = set(db.scalars(select(DismissedAlert.key)))
    alerts, unavailable = [], []
    for name, source in SOURCES.items():
        try:
            alerts += [a for a in source(db) if a.key not in dismissed]
        except Exception:  # one broken source must never hide the rest
            db.rollback()
            log.exception("alert source %s failed", name)
            unavailable.append(name)
    alerts.sort(key=lambda a: (a.severity != "warn", a.title))
    return AlertsOut(alerts=alerts, unavailable=unavailable)


@router.post("/dismiss", status_code=204)
def dismiss(body: DismissIn, db: Session = Depends(get_db)):
    db.execute(insert(DismissedAlert).values(key=body.key, dismissed_at=utcnow()).on_conflict_do_nothing())
    db.commit()
    return Response(status_code=204)
