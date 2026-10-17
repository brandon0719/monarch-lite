# monarch-lite

A private, self-hosted, single-user personal finance app: a Monarch Money–style clone tailored to one person's finances. Features: SimpleFIN sync, rules-based categorization, transfer detection, a 50/30/20 budget, per-category budgets, cash flow, spending breakdown, and daily backups. The requirements and design docs are kept locally and not published.

Runs always-on at **http://127.0.0.1:8000**. It syncs SimpleFIN daily and backs up daily to `~/monarch-lite-backups`.

## One-time setup

1. `.env` in the repo root (never committed):
   ```
   SIMPLEFIN_TOKEN=<your SimpleFIN access URL>
   FINNHUB_API_KEY=<your Finnhub key>   # used from M4
   # BACKUP_DIR=~/monarch-lite-backups   (optional)
   ```
2. Backend:
   ```bash
   python3.13 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt
   cd backend && ../.venv/bin/alembic upgrade head && cd ..
   ```
3. Frontend: `cd frontend && npm install && npm run build && cd ..` (if `npm install` is blocked in your environment, run it yourself in a terminal)
4. Start at login:
   ```bash
   mkdir -p ~/Library/Logs/monarch-lite
   mkdir -p ~/Library/LaunchAgents
   sed "s|__REPO__|$PWD|g; s|__HOME__|$HOME|g" ops/com.monarch-lite.plist > ~/Library/LaunchAgents/com.monarch-lite.plist
   launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.monarch-lite.plist
   ```

## How syncing works

- It syncs daily and on **Sync now**. Only posted transactions are synced; pending ones are skipped.
- Each sync re-reads from 7 days before the account that has gone longest without a good sync. A brand-new account gets up to 365 days of history.
- An account SimpleFIN stops returning, or one that stays stale, keeps the window wide. That costs about 10 SimpleFIN requests per sync. Close (not just hide) accounts you no longer use: hiding only removes them from views; closing stops them from widening the sync window.
- Failed syncs retry hourly.

## Accounts and categories

- To add an institution, connect it at bridge.simplefin.org. The next sync picks it up with a 365-day backfill.
- **Transfer** and **Credit Card Payment** are used by transfer detection, so they can't be renamed or deleted. Changing their group or bucket is fine.

## After pulling changes

```bash
.venv/bin/pip install -q -r backend/requirements.txt
cd backend && ../.venv/bin/alembic upgrade head && cd ../frontend && npm run build && cd ..
launchctl kickstart -k gui/$(id -u)/com.monarch-lite
```

## Development

Stop the background server first, since it holds port 8000: `launchctl bootout gui/$(id -u)/com.monarch-lite`

```bash
cd backend && ../.venv/bin/uvicorn app.main:app --reload --host 127.0.0.1 --port 8000   # terminal 1
cd frontend && npm run dev                                                             # terminal 2 → http://localhost:5173
cd backend && ../.venv/bin/pytest                                                      # tests (never touch the network)
```

The frontend uses hash routes, so pages live at paths like `http://127.0.0.1:8000/#/rules`.

Start it again afterwards with the `launchctl bootstrap …` line from setup.

## Restore a backup

```bash
launchctl bootout gui/$(id -u)/com.monarch-lite
cd backend && ../.venv/bin/python -m app.restore ~/monarch-lite-backups/monarch-lite-YYYYMMDD-HHMMSS.db
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.monarch-lite.plist
```
The previous database is kept as `backend/monarch-lite.db.pre-restore-YYYYMMDD-HHMMSS`, a timestamped copy made with SQLite's backup API. Restore refuses an empty or table-less backup file.

## Logs

`~/Library/Logs/monarch-lite/server.log`
