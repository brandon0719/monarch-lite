import datetime as dt
import shutil
import sqlite3
from pathlib import Path

import pytest

from app.restore import RestoreError, restore
from app.services.backup import backup, newest_backup_age

T0 = dt.datetime(2026, 10, 1, 0, 0, 0)


def make_db(path, rows):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE IF NOT EXISTS t (x INTEGER)")
    conn.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(rows)])
    conn.commit()
    conn.close()


def rows(path):
    conn = sqlite3.connect(path)
    n = conn.execute("SELECT count(*) FROM t").fetchone()[0]
    conn.close()
    return n


def test_backup_copies_and_keeps_newest_30(tmp_path):
    live, out = tmp_path / "live.db", tmp_path / "backups"
    make_db(live, 2)
    for i in range(32):
        backup(live, out, now=T0 + dt.timedelta(minutes=i))
    files = sorted(out.glob("monarch-lite-*.db"))
    assert len(files) == 30
    assert files[0].name == "monarch-lite-20261001-000200.db"
    assert rows(files[-1]) == 2


def test_newest_backup_age(tmp_path):
    out = tmp_path / "backups"
    assert newest_backup_age(out, now=T0) is None
    live = tmp_path / "live.db"
    make_db(live, 1)
    backup(live, out, now=T0)
    assert newest_backup_age(out, now=T0 + dt.timedelta(hours=2)) == dt.timedelta(hours=2)


def test_newest_backup_age_ignores_foreign_names(tmp_path):
    out = tmp_path / "backups"
    live = tmp_path / "live.db"
    make_db(live, 1)
    backup(live, out, now=T0)
    (out / "monarch-lite-old.db").write_bytes(b"hand copy")
    assert newest_backup_age(out, now=T0 + dt.timedelta(hours=2)) == dt.timedelta(hours=2)


def test_pruning_ignores_foreign_names(tmp_path):
    out = tmp_path / "backups"
    live = tmp_path / "live.db"
    make_db(live, 1)
    out.mkdir(parents=True, exist_ok=True)
    (out / "monarch-lite-old.db").write_bytes(b"hand copy")
    for i in range(3):
        backup(live, out, now=T0 + dt.timedelta(minutes=i), keep=2)
    assert (out / "monarch-lite-old.db").exists()
    assert len(list(out.glob("monarch-lite-2*.db"))) == 2


def test_backup_refuses_missing_source(tmp_path):
    out = tmp_path / "backups"
    with pytest.raises(sqlite3.OperationalError):
        backup(tmp_path / "nope.db", out, now=T0)
    assert not (tmp_path / "nope.db").exists()
    assert list(out.glob("monarch-lite-*")) == []


def test_failed_backup_leaves_no_partial_file(tmp_path, monkeypatch):
    live, out = tmp_path / "live.db", tmp_path / "backups"
    make_db(live, 2)
    real_connect = sqlite3.connect

    class Exploding:
        def __init__(self, conn):
            self._conn = conn

        def backup(self, *_args, **_kwargs):
            raise OSError("disk full")

        def close(self):
            self._conn.close()

    monkeypatch.setattr(sqlite3, "connect", lambda *a, **kw: Exploding(real_connect(*a, **kw)))
    with pytest.raises(OSError):
        backup(live, out, now=T0)
    assert list(out.glob("monarch-lite-*.db")) == []
    assert list(out.glob("monarch-lite-*.tmp")) == []


def test_restore_round_trip_keeps_a_safety_copy(tmp_path):
    live, out = tmp_path / "live.db", tmp_path / "backups"
    make_db(live, 2)
    snapshot = backup(live, out, now=T0)
    make_db(live, 1)  # live now has 3 rows
    safety = restore(snapshot, live)
    assert rows(live) == 2
    assert list(tmp_path.glob("live.db.pre-restore-*")) == [safety]
    assert rows(safety) == 3


def test_safety_copy_includes_uncheckpointed_wal(tmp_path):
    live = tmp_path / "live.db"
    backup_file = tmp_path / "backup.db"
    make_db(backup_file, 1)
    conn = sqlite3.connect(live)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA wal_autocheckpoint=0")
        conn.execute("CREATE TABLE t (x INTEGER)")
        conn.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(5)])
        conn.commit()  # WAL holds the rows; the main file does not
        safety = restore(backup_file, live)
        assert rows(safety) == 5
    finally:
        conn.close()


def test_restore_rejects_a_non_database(tmp_path):
    bad = tmp_path / "bad.db"
    bad.write_bytes(b"definitely not sqlite" * 100)
    with pytest.raises(RestoreError):
        restore(bad, tmp_path / "live.db")


def test_restore_rejects_empty_file(tmp_path):
    live = tmp_path / "live.db"
    make_db(live, 2)
    empty = tmp_path / "empty.db"
    empty.write_bytes(b"")
    with pytest.raises(RestoreError):
        restore(empty, live)
    assert rows(live) == 2
    assert list(tmp_path.glob("live.db.pre-restore-*")) == []


def test_restore_rejects_a_database_with_no_tables(tmp_path):
    live = tmp_path / "live.db"
    make_db(live, 2)
    hollow = tmp_path / "hollow.db"
    conn = sqlite3.connect(hollow)
    conn.execute("CREATE TABLE gone (x INTEGER)")
    conn.execute("DROP TABLE gone")
    conn.commit()
    conn.close()
    with pytest.raises(RestoreError, match="contains no tables"):
        restore(hollow, live)
    assert rows(live) == 2


def test_restore_replaces_live_db_atomically(tmp_path, monkeypatch):
    live, backup_file = tmp_path / "live.db", tmp_path / "backup.db"
    make_db(live, 3)
    make_db(backup_file, 1)

    def dying_copy(src, dst, **kw):  # simulates a crash halfway through the copy
        Path(dst).write_bytes(b"half a database")
        raise OSError("disk full")

    monkeypatch.setattr(shutil, "copy2", dying_copy)
    with pytest.raises(OSError):
        restore(backup_file, live)
    assert rows(live) == 3  # the live DB was never touched
