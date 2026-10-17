import datetime as dt
import sqlite3

from sqlalchemy import select

from app import config
from app.models import SyncRun
from app.scheduler import mark_interrupted_runs, run_due_jobs
from app.services import simplefin, sync

NOW = dt.datetime(2026, 10, 16, 12, 0)


def test_runs_jobs_only_when_more_than_24h_stale(db, tmp_path, monkeypatch):
    monkeypatch.setattr(simplefin, "fetch_accounts", lambda start, end: {"errors": [], "accounts": []})
    live = tmp_path / "live.db"
    sqlite3.connect(live).close()
    monkeypatch.setattr(config, "DB_PATH", live)
    monkeypatch.setattr(config, "BACKUP_DIR", tmp_path / "backups")

    assert run_due_jobs(db, NOW, NOW) == ["sync", "backup"]
    later = NOW + dt.timedelta(hours=1)
    assert run_due_jobs(db, later, later) == []
    next_day = NOW + dt.timedelta(hours=25)
    assert run_due_jobs(db, next_day, next_day) == ["sync", "backup"]


def test_failed_sync_is_retried_next_hour(db, tmp_path, monkeypatch):
    def down(start, end):
        raise simplefin.SimpleFinError("Could not reach SimpleFIN")

    monkeypatch.setattr(simplefin, "fetch_accounts", down)
    live = tmp_path / "live.db"
    sqlite3.connect(live).close()
    monkeypatch.setattr(config, "DB_PATH", live)
    monkeypatch.setattr(config, "BACKUP_DIR", tmp_path / "backups")

    assert run_due_jobs(db, NOW, NOW) == ["backup"]
    later = NOW + dt.timedelta(hours=1)
    assert run_due_jobs(db, later, later) == []
    # the hourly retry still ran: a failed run is recorded each time, but never listed as done
    statuses = db.scalars(select(SyncRun.status)).all()
    assert statuses == ["failed", "failed"]


def test_sync_crash_does_not_skip_backup(db, tmp_path, monkeypatch):
    def boom(db, **kwargs):
        raise RuntimeError("db exploded")

    monkeypatch.setattr(sync, "run_sync", boom)
    live = tmp_path / "live.db"
    sqlite3.connect(live).close()
    monkeypatch.setattr(config, "DB_PATH", live)
    monkeypatch.setattr(config, "BACKUP_DIR", tmp_path / "backups")

    assert run_due_jobs(db, NOW, NOW) == ["backup"]
    assert len(list((tmp_path / "backups").glob("*.db"))) == 1


def test_mark_interrupted_runs_fails_only_running_rows(db):
    db.add_all([
        SyncRun(started_at=NOW, status="running"),
        SyncRun(started_at=NOW, status="success", finished_at=NOW),
    ])
    db.commit()
    assert mark_interrupted_runs(db) == 1
    running, ok = db.scalars(select(SyncRun).order_by(SyncRun.id)).all()
    assert (running.status, running.error) == ("failed", "Interrupted (app restarted)")
    assert running.finished_at is not None
    assert (ok.status, ok.error) == ("success", None)
    assert mark_interrupted_runs(db) == 0


def test_startup_marks_interrupted_runs_before_scheduler_starts(db, monkeypatch):
    from fastapi.testclient import TestClient

    from app import main

    db.add(SyncRun(started_at=NOW, status="running"))
    db.commit()
    order = []

    async def fake_loop():
        order.append(db.scalar(select(SyncRun.status)))

    class Sessions:  # hands the lifespan the test session without closing it
        def __enter__(self): return db
        def __exit__(self, *a): return False

    monkeypatch.setattr(main, "SessionLocal", Sessions)
    monkeypatch.setattr(main.scheduler, "loop", fake_loop)
    with TestClient(main.app):
        pass
    assert order == ["failed"]
