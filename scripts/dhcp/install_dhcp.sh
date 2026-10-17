#!/usr/bin/env bash
# Serve DHCP to team GCSs on whichever course network this host is on.
#
# Installs scripts/dhcp/dhcpd.conf (Course Alpha/Bravo/Charlie/Delta + Demo
# subnets), points isc-dhcp-server at the course interface and adds a
# NetworkManager hook that restarts dhcpd when that interface comes up.
# Afterwards, changing course is only: set the wired IP to the course host
# address (192.168.65.2 / .66.2 / .67.2 / .68.2 / .70.2) and reconnect.
#
# Usage:  sudo ./scripts/dhcp/install_dhcp.sh            # interface enp12s0
#         sudo IFACE=eth0 ./scripts/dhcp/install_dhcp.sh
#         sudo ./scripts/dhcp/install_dhcp.sh remove      # restore the backup
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
IFACE="${IFACE:-enp12s0}"
CONF=/etc/dhcp/dhcpd.conf
DEFAULTS=/etc/default/isc-dhcp-server
HOOK=/etc/NetworkManager/dispatcher.d/90-robocommand-dhcpd
BACKUP="$CONF.before-robocommand"

if [ "$(id -u)" -ne 0 ]; then
    echo "Run with sudo: sudo $0 ${1:-}" >&2
    exit 1
fi

if [ "${1:-}" = "remove" ]; then
    rm -f "$HOOK"
    if [ -f "$BACKUP" ]; then mv "$BACKUP" "$CONF"; fi
    systemctl restart isc-dhcp-server || true
    echo "Removed $HOOK and restored $CONF."
    exit 0
fi

if ! command -v dhcpd >/dev/null; then
    apt-get update
    # The package tries to start dhcpd before it has an interface; that failure is expected
    apt-get install -y isc-dhcp-server || dpkg --configure -a || true
fi

[ -f "$BACKUP" ] || cp "$CONF" "$BACKUP"
install -m 644 "$HERE/dhcpd.conf" "$CONF"
if ! dhcpd -t -q -cf "$CONF"; then                      # syntax check before restarting
    cp "$BACKUP" "$CONF"
    echo "dhcpd rejected the new config; $CONF restored." >&2
    exit 1
fi

sed -i "s/^INTERFACESv4=.*/INTERFACESv4=\"$IFACE\"/" "$DEFAULTS"
sed "s/__IFACE__/$IFACE/" "$HERE/90-robocommand-dhcpd" > "$HOOK"
chmod 755 "$HOOK"

if ip -4 addr show dev "$IFACE" 2>/dev/null | grep -q "inet "; then
    addr="$(ip -4 -br addr show dev "$IFACE" | awk '{print $3}')"
    if systemctl restart isc-dhcp-server; then
        echo "dhcpd restarted on $IFACE ($addr)."
    else
        echo "WARN: dhcpd not started: $IFACE ($addr) is not on a course subnet (192.168.65-68.2, 192.168.70.2)." >&2
    fi
else
    echo "$IFACE has no IPv4 address yet; dhcpd starts when it comes up."
fi
echo "Installed $CONF (backup: $BACKUP), INTERFACESv4=$IFACE, hook $HOOK."
