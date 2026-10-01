#!/usr/bin/env bash
# RoboCommand RobotX 2026 Qt UI launcher.
# Brings up a Mosquitto broker on 127.0.0.1:1883 (best-effort), then opens the UI.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== RoboCommand RobotX 2026 Qt UI Launcher ==="

# --- 1) Python dependencies (best-effort) --------------------------------
if ! python3 -c "import PyQt5, paho.mqtt, google.protobuf" 2>/dev/null; then
    echo "Installing Python dependencies (PyQt5, paho-mqtt, protobuf)..."
    pip3 install -r requirements.txt || \
        echo "WARNING: pip install failed (offline?). Continuing if deps already exist."
fi

# --- 2) Broker on 127.0.0.1:1883 (best-effort) ---------------------------
port_listening() {
    python3 - <<'PY'
import socket, sys
s = socket.socket(); s.settimeout(1)
ok = s.connect_ex(("127.0.0.1", 1883)) == 0
s.close()
sys.exit(0 if ok else 1)
PY
}

start_broker() {
    # Prefer a local mosquitto: instant and works fully offline.
    if command -v mosquitto >/dev/null 2>&1; then
        echo "Starting a local Mosquitto broker on 127.0.0.1:1883..."
        bash scripts/dev_broker.sh start
        return 0
    fi
    # Otherwise use the Docker broker — the pre-built eclipse-mosquitto image
    # needs NO build (and therefore no network). The rc-test service is skipped
    # on purpose: its Python image requires network to pip-install.
    if command -v docker >/dev/null 2>&1 && [ -f robocommand/RobotX_2026/docker-compose.yml ]; then
        echo "Starting the Docker Mosquitto broker (broker only, no build)..."
        docker compose -f robocommand/RobotX_2026/docker-compose.yml up -d broker
        return 0
    fi
    return 1
}

if port_listening; then
    echo "Broker already listening on 127.0.0.1:1883."
else
    start_broker || true
    sleep 1
    if port_listening; then
        echo "Broker ready on 127.0.0.1:1883."
    else
        echo ""
        echo "WARNING: no broker running on 127.0.0.1:1883."
        echo "The UI will still open. Start a broker with one of:"
        echo "    ./scripts/dev_broker.sh start"
        echo "    docker compose -f robocommand/RobotX_2026/docker-compose.yml up -d broker"
        echo "...then press Connect in the UI."
    fi
fi

echo ""
echo "Launching RoboCommand Qt UI..."
exec python3 run_ui.py
