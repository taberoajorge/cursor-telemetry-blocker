#!/usr/bin/env bash
set -euo pipefail

HOSTS_FILE="/etc/hosts"
MARKER="# Cursor Telemetry Blocker"

if grep -q "$MARKER" "$HOSTS_FILE" 2>/dev/null; then
    echo "Telemetry blocks already present in $HOSTS_FILE"
    exit 0
fi

echo "Adding telemetry blocks to $HOSTS_FILE (requires sudo)..."

sudo tee -a "$HOSTS_FILE" > /dev/null <<'HOSTS_BLOCK'

# Cursor Telemetry Blocker
127.0.0.1 metrics.cursor.sh
127.0.0.1 mobile.events.data.microsoft.com
127.0.0.1 default.exp-tas.com
127.0.0.1 cursor-user-debugging-data.s3.us-east-1.amazonaws.com
127.0.0.1 repo42.cursor.sh
127.0.0.1 api.turbopuffer.com
127.0.0.1 statsig.cursor.sh
HOSTS_BLOCK

echo "Flushing DNS cache..."
OS_TYPE="$(uname -s)"
case "$OS_TYPE" in
    Darwin)
        sudo dscacheutil -flushcache
        sudo killall -HUP mDNSResponder 2>/dev/null || true
        ;;
    Linux)
        if command -v systemd-resolve > /dev/null 2>&1; then
            sudo systemd-resolve --flush-caches
        elif command -v resolvectl > /dev/null 2>&1; then
            sudo resolvectl flush-caches
        fi
        ;;
esac

echo "Done. Telemetry domains are now blocked."
