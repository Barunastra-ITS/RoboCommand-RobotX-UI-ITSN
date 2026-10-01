#!/usr/bin/env bash
# Start a local Mosquitto broker for UI development against Team Village-style testing.
# Usage: ./scripts/dev_broker.sh [start|stop]
set -euo pipefail

CONF="$(mktemp -t mosquitto_ui_XXXXXX.conf)"
PORT="${MQTT_PORT:-1883}"

cleanup() { rm -f "$CONF"; }
trap cleanup EXIT

cat > "$CONF" <<EOF
listener $PORT 127.0.0.1
allow_anonymous true
persistence false
EOF

case "${1:-start}" in
  start)
    if ss -ltn 2>/dev/null | grep -q ":$PORT "; then
      echo "Port $PORT already in use."
      exit 1
    fi
    mosquitto -c "$CONF" -d
    sleep 1
    if ss -ltn 2>/dev/null | grep -q ":$PORT "; then
      echo "Mosquitto listening on 127.0.0.1:$PORT (anonymous, no persistence)"
    else
      echo "Failed to start Mosquitto on port $PORT"
      exit 1
    fi
    ;;
  stop)
    pkill -f "mosquitto.*mosquitto_ui_" || echo "No dev broker running."
    ;;
  *)
    echo "Usage: $0 [start|stop]"
    exit 1
    ;;
esac