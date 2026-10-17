"""Settings from the repo-root .env. Read as `config.X` at call time so tests can monkeypatch."""
import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent
load_dotenv(PROJECT_DIR / ".env")

SIMPLEFIN_TOKEN = os.getenv("SIMPLEFIN_TOKEN", "")
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "")  # used from M4
DB_PATH = Path(os.getenv("DB_PATH", str(BACKEND_DIR / "monarch-lite.db"))).expanduser()
BACKUP_DIR = Path(os.getenv("BACKUP_DIR", str(Path.home() / "monarch-lite-backups"))).expanduser()
FRONTEND_DIST = PROJECT_DIR / "frontend" / "dist"
