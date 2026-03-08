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
127.0.0.1 dc.services.visualstudio.com
127.0.0.1 o55978.ingest.us.sentry.io
127.0.0.1 snowplowprd.trx.gitlab.net
127.0.0.1 new-sentry.gitlab.net
127.0.0.1 otel.gitkraken.com
127.0.0.1 xp.atlassian.com
127.0.0.1 as.atlassian.com
127.0.0.1 api.agnost.ai
HOSTS_BLOCK

echo "Flushing DNS cache..."
sudo dscacheutil -flushcache
sudo killall -HUP mDNSResponder 2>/dev/null || true

echo "Done. Telemetry domains are now blocked."
echo "To verify: dscacheutil -q host -a name metrics.cursor.sh"
