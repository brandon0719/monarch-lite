import io
import json
import sqlite3
import zipfile

from app import config
from app.services.export import TABLES
from tests.conftest import make_account, make_txn


def test_export_contains_every_table(client, db):
    make_txn(db, make_account(db), -999)
    resp = client.get("/api/export")
    assert resp.status_code == 200 and resp.headers["content-type"] == "application/zip"
    archive = zipfile.ZipFile(io.BytesIO(resp.content))
    assert {f"{t}.csv" for t in TABLES} | {"export.json"} == set(archive.namelist())
    data = json.loads(archive.read("export.json"))
    assert len(data["transactions"]) == 1 and len(data["categories"]) > 0


def test_backup_endpoint(client, tmp_path, monkeypatch):
    live = tmp_path / "live.db"
    sqlite3.connect(live).close()
    monkeypatch.setattr(config, "DB_PATH", live)
    monkeypatch.setattr(config, "BACKUP_DIR", tmp_path / "backups")
    path = client.post("/api/backups").json()["path"]
    assert path.startswith(str(tmp_path / "backups"))
