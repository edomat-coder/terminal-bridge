#!/usr/bin/env bash
# install_bridge.sh — Idempotentes Setup einer tmux-WebSocket-Terminal-Bridge
# Verwendung: auf dem Ziel-Host als regulärer User ausführen. Erwartet:
#   - terminal_bridge.py neben diesem Skript (Deploy-Verzeichnis)
#   - TERMINAL_BRIDGE_TOKEN (env) ODER/.env-Dateivorlage
# Anpassbar über Umgebungsvariablen (Default = Beispielwerte):
#   BRIDGE_APP_DIR, BRIDGE_BIND_IP, BRIDGE_BIND_PORT, BRIDGE_SERVICE, BRIDGE_USER
set -euo pipefail

APP_DIR=${BRIDGE_APP_DIR:-/opt/terminal-bridge}
BIND_IP=${BRIDGE_BIND_IP:-127.0.0.1}
BIND_PORT=${BRIDGE_BIND_PORT:-5233}
SERVICE=${BRIDGE_SERVICE:-terminal-bridge}
RUN_USER=${BRIDGE_USER:-$(id -un)}
VENV=$APP_DIR/.venv
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> Setup $APP_DIR"
mkdir -p "$APP_DIR"
# Nur kopieren, wenn Quelle != Ziel (idempotent; Aufruf aus einem anderen Ordner erlaubt)
if [ -f "$SRC_DIR/terminal_bridge.py" ] && [ "$SRC_DIR/terminal_bridge.py" != "$APP_DIR/terminal_bridge.py" ]; then
  cp -v "$SRC_DIR/terminal_bridge.py" "$APP_DIR/terminal_bridge.py"
fi

echo "==> venv + deps"
if [ ! -x "$VENV/bin/python" ]; then
  python3 -m venv "$VENV"
fi
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet fastapi 'uvicorn[standard]'

echo "==> .env (Token)"
if [ ! -f "$APP_DIR/.env" ]; then
  if [ -z "${TERMINAL_BRIDGE_TOKEN:-}" ]; then
    echo "FEHLER: TERMINAL_BRIDGE_TOKEN env oder bereits existierende .env nötig." >&2
    exit 1
  fi
  cat > "$APP_DIR/.env" <<EOF
TERMINAL_BRIDGE_TOKEN=$TERMINAL_BRIDGE_TOKEN
TERMINAL_HOST=$BIND_IP
TERMINAL_PORT=$BIND_PORT
EOF
fi
chmod 600 "$APP_DIR/.env"

echo "==> targets.json (Registry-Vorlage)"
if [ ! -f "$APP_DIR/targets.json" ]; then
  cat > "$APP_DIR/targets.json" <<'EOF'
[
  {"id": "all", "name": "Default-Session", "mode": "local", "session": "main"},
  {"id": "second", "name": "Zweite Session", "mode": "local", "session": "work"}
]
EOF
fi
chmod 600 "$APP_DIR/targets.json"

echo "==> systemd-Unit"
cat > /etc/systemd/system/$SERVICE.service <<EOF
[Unit]
Description=Generic terminal-bridge (tmux over WebSocket)
After=network.target

[Service]
Type=simple
User=$RUN_USER
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
ExecStart=$VENV/bin/python $APP_DIR/terminal_bridge.py
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=$APP_DIR

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now $SERVICE

echo "==> Status"
systemctl --no-pager status $SERVICE | head -12
echo "==> Bind-Check:"
ss -tlnp | grep ":$BIND_PORT" || true
echo "DONE"
