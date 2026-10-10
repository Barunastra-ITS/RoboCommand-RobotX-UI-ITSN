#!/usr/bin/env bash
# Install and run Mosquitto on this machine as the course RoboCommand broker,
# so team GCSs on the course network can report to it over TCP 1883.
#
# Usage:  sudo ./scripts/setup_host_broker.sh            # Course Alpha network
#         sudo COURSE_NET=192.168.66.0/24 ./scripts/setup_host_broker.sh
#         sudo ./scripts/setup_host_broker.sh remove     # undo
set -euo pipefail

CONF=/etc/mosquitto/conf.d/robocommand.conf
COURSE_NET="${COURSE_NET:-192.168.65.0/24}"
PORT=1883

if [ "$(id -u)" -ne 0 ]; then
    echo "Run with sudo: sudo $0 ${1:-}" >&2
    exit 1
fi

if [ "${1:-}" = "remove" ]; then
    rm -f "$CONF"
    if command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then
        ufw delete allow from "$COURSE_NET" to any port "$PORT" proto tcp || true
    fi
    systemctl restart mosquitto 2>/dev/null || true
    echo "Removed $CONF (mosquitto back to its default localhost-only config)."
    exit 0
fi

if ! command -v mosquitto >/dev/null; then
    apt-get update
    apt-get install -y mosquitto mosquitto-clients
fi

# Handbook §3.4: plain MQTT over TCP 1883, no auth on the course network.
cat > "$CONF" <<EOF
# RoboCommand course broker (written by setup_host_broker.sh)
listener $PORT 0.0.0.0
allow_anonymous true
EOF

systemctl enable mosquitto
systemctl restart mosquitto

# If the firewall is on, admit only the course network (localhost is always allowed).
if command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then
    ufw allow from "$COURSE_NET" to any port "$PORT" proto tcp
fi

sleep 1
if ss -ltn | grep -q ":$PORT "; then
    echo "Mosquitto is listening on 0.0.0.0:$PORT."
    ip -4 -o addr show | awk '{print "  reachable at " $4 " (" $2 ")"}'
else
    echo "Mosquitto did not start; see: journalctl -u mosquitto -n 30" >&2
    exit 1
fi
