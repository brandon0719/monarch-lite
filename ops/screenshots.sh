#!/usr/bin/env bash
# Usage: ops/screenshots.sh OUT_DIR
# Screenshots every page (light, dark, phone) from a throwaway server on :8001 that runs on a
# backup-API copy of the real DB with an empty SimpleFIN token (no network). Phone shots go through a
# static iframe wrapper served on :8002 from its own folder (never the folder holding the DB copy).
# The real app on :8000 is untouched.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:?usage: ops/screenshots.sh OUT_DIR}"
PORT=8001
WRAP_PORT=8002
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
TMP="$(mktemp -d)"
SERVER=""
WRAP=""
cleanup() {
  for pid in "$SERVER" "$WRAP"; do if [ -n "$pid" ]; then kill "$pid" 2>/dev/null || true; wait "$pid" 2>/dev/null || true; fi; done
  rm -rf "$TMP"
}
trap cleanup EXIT
for p in "$PORT" "$WRAP_PORT"; do
  if curl -sf "127.0.0.1:$p/" >/dev/null 2>&1; then
    echo "error: something is already answering on 127.0.0.1:$p; stop it first" >&2
    exit 1
  fi
done
mkdir -p "$OUT"
"$ROOT/.venv/bin/python" -c 'import sqlite3, sys; s = sqlite3.connect(sys.argv[1]); d = sqlite3.connect(sys.argv[2]); s.backup(d); d.close(); s.close()' \
  "$ROOT/backend/monarch-lite.db" "$TMP/shots.db"
# Bring the copy up to the current schema so pages for newer migrations render (the real DB is untouched).
(cd "$ROOT/backend" && DB_PATH="$TMP/shots.db" ../.venv/bin/alembic upgrade head >"$TMP/migrate.log" 2>&1) || { cat "$TMP/migrate.log" >&2; exit 1; }
(cd "$ROOT/backend" && exec env SIMPLEFIN_TOKEN= DB_PATH="$TMP/shots.db" BACKUP_DIR="$TMP/backups" \
  ../.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "$PORT" >"$TMP/server.log" 2>&1) &
SERVER=$!
READY=""
for _ in $(seq 1 30); do
  if curl -sf "127.0.0.1:$PORT/api/health" >/dev/null; then READY=1; break; fi
  sleep 1
done
if [ -z "$READY" ]; then echo "error: server did not become healthy within 30s; log:" >&2; cat "$TMP/server.log" >&2; exit 1; fi
shoot() {
  "$CHROME" --headless=new --disable-gpu --hide-scrollbars --user-data-dir="$TMP/profile" \
    --virtual-time-budget=5000 --window-size="$2" --screenshot="$OUT/$1.png" "$3" >/dev/null 2>&1
}
# Headless Chrome lays a page out at a minimum of ~500px wide and crops, so phone shots instead
# screenshot a 500px-wide page holding a 390x844 iframe, which gets a true 390px viewport. The wrapper
# is served over http (a file:// parent makes the iframe cross-process, which headless virtual time
# does not wait for, so the shot raced the page load).
# Only "$TMP/wrap" is served: "$TMP" itself holds shots.db, a copy of the real ledger.
mkdir -p "$TMP/wrap"
"$ROOT/.venv/bin/python" -m http.server "$WRAP_PORT" --bind 127.0.0.1 --directory "$TMP/wrap" >"$TMP/wrap.log" 2>&1 &
WRAP=$!
WRAP_READY=""
for _ in $(seq 1 75); do
  if curl -sf "127.0.0.1:$WRAP_PORT/" >/dev/null 2>&1; then WRAP_READY=1; break; fi
  sleep 0.2
done
if [ -z "$WRAP_READY" ]; then echo "error: wrapper server on :$WRAP_PORT not ready within 15s; log:" >&2; cat "$TMP/wrap.log" >&2; exit 1; fi
shoot_phone() {
  printf '<!doctype html><html><body style="margin:0;background:#888"><iframe src="%s" style="border:0;display:block;width:390px;height:844px;background:#fff"></iframe></body></html>' "$2" > "$TMP/wrap/$1.html"
  shoot "$1" 500,844 "http://127.0.0.1:$WRAP_PORT/$1.html"
}
for page in overview transactions spending accounts rules categories settings; do
  shoot "$page-light" 1440,1000 "http://127.0.0.1:$PORT/?theme=light#/$page"
  shoot "$page-dark" 1440,1000 "http://127.0.0.1:$PORT/?theme=dark#/$page"
  shoot_phone "$page-phone" "http://127.0.0.1:$PORT/?theme=light#/$page"
done
echo "screenshots written to $OUT"
