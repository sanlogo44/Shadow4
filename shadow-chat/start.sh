#!/usr/bin/env bash
# Shadow Chat — Start-Skript (Server + Web-UI)
#
#   ./start.sh              -> baut den Server (falls nötig) und startet Server + Web-UI
#   ./start.sh --prebuilt   -> nutzt die fertige Linux-Binary aus prebuilt/ (kein Rust nötig)
#
# Server:  http://127.0.0.1:8787   (API)
# Web-UI:  http://127.0.0.1:8080   (Browser)
set -euo pipefail
cd "$(dirname "$0")"

PORT="${SHADOW_PORT:-8787}"
UI_PORT="${SHADOW_UI_PORT:-8080}"
DATA_DIR="${SHADOW_DATA_DIR:-./shadow-data}"
export SHADOW_PASSWORD="${SHADOW_PASSWORD:-dev-only-not-secure}"

BIN="./target/release/shadow"
if [ "${1:-}" = "--prebuilt" ]; then
  BIN="./prebuilt/linux-x64/server/shadow"
  chmod +x "$BIN"
elif [ ! -x "$BIN" ]; then
  echo "==> Baue Rust-Server (cargo build --release)"
  cargo build --release
fi

mkdir -p "$DATA_DIR"
echo "==> Starte Server auf http://127.0.0.1:$PORT"
"$BIN" server --host 127.0.0.1 --port "$PORT" --data-dir "$DATA_DIR" &
SERVER_PID=$!
trap 'kill $SERVER_PID 2>/dev/null || true' EXIT

for _ in $(seq 1 40); do
  curl -sf "http://127.0.0.1:$PORT/api/auth/status" >/dev/null 2>&1 && break
  sleep 0.5
done

echo "==> Web-UI auf http://127.0.0.1:$UI_PORT (Strg+C beendet alles)"
( cd prebuilt/web-ui/web && python3 -m http.server "$UI_PORT" >/dev/null 2>&1 ) &
UI_PID=$!
trap 'kill $SERVER_PID $UI_PID 2>/dev/null || true' EXIT

echo
echo "Erster Login: Admin / 1234 (danach wird ein neuer Admin erzwungen)"
wait $SERVER_PID
