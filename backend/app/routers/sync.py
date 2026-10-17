import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import SyncRun
from ..services import sync as sync_service

router = APIRouter(prefix="/api/sync", tags=["sync"])


class SyncRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    started_at: dt.datetime
    finished_at: dt.datetime | None
    status: str
    accounts_ok: int
    accounts_stale: int
    txns_added: int
    error: str | None


@router.post("", response_model=SyncRunOut)
def sync_now(db: Session = Depends(get_db)):
    try:
        return sync_service.run_sync(db)
    except sync_service.SyncInProgress:
        raise HTTPException(409, "A sync is already running") from None


@router.get("/runs", response_model=list[SyncRunOut])
def list_runs(limit: int = Query(20, ge=1, le=200), db: Session = Depends(get_db)):
    return db.scalars(select(SyncRun).order_by(SyncRun.id.desc()).limit(limit)).all()
