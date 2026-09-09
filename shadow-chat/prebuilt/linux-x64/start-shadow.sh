#!/usr/bin/env bash
# Startet den Shadow-Server und öffnet die Flutter-UI.
# Beendet beim Schließen auch den Server.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVER="$HERE/server/shadow"
UI="$HERE/ui/shadow_chat"
PORT="${SHADOW_PORT:-8787}"
DATA_DIR="$HERE/data"

mkdir -p "$DATA_DIR"

echo "» Starte Shadow-Server auf http://127.0.0.1:$PORT …"
"$SERVER" server --host 127.0.0.1 --port "$PORT" --data-dir "$DATA_DIR" &
SRV_PID=$!

# Auf Serverbereitschaft warten (max. ~15 s).
for _ in $(seq 1 60); do
  if curl -sf "http://127.0.0.1:$PORT/api/auth/status" >/dev/null 2>&1; then
    break
  fi
  sleep 0.25
done

cleanup() {
  echo ""
  echo "» Beende Shadow-Server (PID $SRV_PID) …"
  kill "$SRV_PID" 2>/dev/null || true
  wait "$SRV_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "» Öffne Shadow-UI …"
if [ -x "$UI" ]; then
  "$UI"
else
  echo "  UI-Binary nicht gefunden: $UI"
  echo "  Server läuft weiter unter http://127.0.0.1:$PORT — Web-UI als Alternative."
  wait "$SRV_PID"
fi
