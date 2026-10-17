"""Hourly check: sync and back up when the last success is >24h old (FR-ACC-02, FR-DATA-02)."""
import asyncio
import datetime as dt
import logging

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from . import config
from .db import SessionLocal
from .models import SyncRun, utcnow
from .services import backup as backup_service
from .services import sync

log = logging.getLogger("monarch-lite.scheduler")
EVERY = dt.timedelta(hours=24)
CHECK_SECONDS = 3600


def mark_interrupted_runs(db: Session) -> int:
    """A run still 'running' at startup died with the previous process; close it out."""
    result = db.execute(
        update(SyncRun).where(SyncRun.status == "running").values(status="failed", error="Interrupted (app restarted)", finished_at=utcnow())
    )
    db.commit()
    return result.rowcount


def run_due_jobs(db: Session, now: dt.datetime, local_now: dt.datetime) -> list[str]:
    """`now` is naive UTC (sync_runs); `local_now` is local time (backup filenames)."""
    done = []
    last_ok = db.scalar(select(func.max(SyncRun.started_at)).where(SyncRun.status.in_(("success", "partial"))))
    if last_ok is None or now - last_ok > EVERY:
        try:
            run = sync.run_sync(db, now=now)
            if run.status == "failed":
                log.warning("scheduled sync failed: %s", run.error)
            else:
                done.append("sync")
        except sync.SyncInProgress:
            pass
        except Exception:  # a crashed sync must not skip this hour's backup
            log.exception("scheduled sync failed")
    age = backup_service.newest_backup_age(config.BACKUP_DIR, local_now)
    if age is None or age > EVERY:
        backup_service.backup(config.DB_PATH, config.BACKUP_DIR, now=local_now)
        done.append("backup")
    return done


def _run_once() -> list[str]:
    """Session is opened and closed in the worker thread, never on the event loop."""
    with SessionLocal() as db:
        return run_due_jobs(db, utcnow(), dt.datetime.now())


async def loop() -> None:
    while True:
        try:
            done = await asyncio.to_thread(_run_once)
            if done:
                log.info("scheduled: %s", ", ".join(done))
        except Exception:  # never let one bad hour kill the loop
            log.exception("scheduled job failed")
        await asyncio.sleep(CHECK_SECONDS)
