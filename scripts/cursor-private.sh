#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SRC_DIR="$PROJECT_DIR/src/cursor_telemetry_blocker"
PROXY_PORT=18080
CONFDIR="$PROJECT_DIR/.mitmproxy"
CA_CERT="$CONFDIR/mitmproxy-ca-cert.pem"
MITM_PID_FILE="$PROJECT_DIR/.mitm.pid"
CURSOR_BIN="/Applications/Cursor.app/Contents/MacOS/Cursor"

MODE="${1:-block}"

case "$MODE" in
    observe)
        ADDON_SCRIPT="$SRC_DIR/observer.py"
        echo "=== OBSERVE mode (logging only, no blocking) ==="
        ;;
    block)
        ADDON_SCRIPT="$SRC_DIR/filter.py"
        echo "=== BLOCK mode (telemetry blocked, AI passes through) ==="
        ;;
    deep)
        ADDON_SCRIPT="$SRC_DIR/deep_filter.py"
        echo "=== DEEP mode (block + strip repo names from gRPC protobuf) ==="
        ;;
    *)
        echo "Usage: $0 [observe|block|deep]"
        echo "  observe  Log all traffic without blocking (for analysis)"
        echo "  block    Block telemetry, pass AI requests (default)"
        echo "  deep     Block telemetry + strip repo names from AI requests"
        exit 1
        ;;
esac

if [ ! -f "$CA_CERT" ]; then
    echo "Error: CA cert not found at $CA_CERT"
    echo "Run setup-ca-cert.sh first to install it in macOS Keychain."
    exit 1
fi

if [ ! -x "$CURSOR_BIN" ]; then
    echo "Error: Cursor binary not found at $CURSOR_BIN"
    exit 1
fi

security find-certificate -c mitmproxy /Library/Keychains/System.keychain > /dev/null 2>&1 || {
    echo ""
    echo "WARNING: mitmproxy CA cert is NOT in the macOS System Keychain."
    echo "Cursor will fail TLS handshakes through the proxy without it."
    echo ""
    echo "Run first:  bash setup-ca-cert.sh"
    echo ""
    read -p "Continue anyway? [y/N] " REPLY
    if [[ ! "$REPLY" =~ ^[Yy]$ ]]; then
        exit 1
    fi
}

cleanup() {
    echo ""
    echo "Shutting down..."
    if [ -f "$MITM_PID_FILE" ]; then
        STORED_PID=$(cat "$MITM_PID_FILE")
        kill "$STORED_PID" 2>/dev/null || true
        rm -f "$MITM_PID_FILE"
    fi
    echo "Cleanup complete."
}

trap cleanup EXIT INT TERM

EXISTING_CURSOR_PIDS=$(pgrep -f "Cursor.app/Contents/MacOS/Cursor" 2>/dev/null || true)
if [ -n "$EXISTING_CURSOR_PIDS" ]; then
    echo ""
    echo "Cursor is already running (without proxy)."
    echo "It must be restarted to route traffic through the proxy."
    echo ""
    read -p "Close existing Cursor and relaunch with proxy? [Y/n] " REPLY
    if [[ "$REPLY" =~ ^[Nn]$ ]]; then
        echo "Aborted. Close Cursor manually and re-run this script."
        exit 0
    fi

    echo "Closing Cursor..."
    osascript -e 'tell application "Cursor" to quit' 2>/dev/null || true
    sleep 2

    REMAINING=$(pgrep -f "Cursor.app/Contents/MacOS/Cursor" 2>/dev/null || true)
    if [ -n "$REMAINING" ]; then
        echo "Force-killing remaining Cursor processes..."
        pkill -f "Cursor.app/Contents" 2>/dev/null || true
        sleep 2
    fi
    echo "Cursor closed."
fi

if [ -f "$MITM_PID_FILE" ]; then
    OLD_PID=$(cat "$MITM_PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "Stopping previous proxy (PID $OLD_PID)..."
        kill "$OLD_PID" 2>/dev/null || true
        sleep 1
    fi
    rm -f "$MITM_PID_FILE"
fi

echo "Starting mitmproxy on port $PROXY_PORT..."
cd "$PROJECT_DIR"
uv run mitmdump \
    --listen-port "$PROXY_PORT" \
    --set confdir="$CONFDIR" \
    --set console_eventlog_verbosity=warn \
    --scripts "$ADDON_SCRIPT" \
    --quiet \
    &
MITM_PID=$!
echo "$MITM_PID" > "$MITM_PID_FILE"

sleep 2
if ! kill -0 "$MITM_PID" 2>/dev/null; then
    echo "Error: mitmproxy failed to start. Check port $PROXY_PORT."
    exit 1
fi
echo "Proxy running (PID $MITM_PID)"

echo "Launching Cursor with proxy..."

HTTP_PROXY="http://127.0.0.1:$PROXY_PORT" \
HTTPS_PROXY="http://127.0.0.1:$PROXY_PORT" \
NODE_EXTRA_CA_CERTS="$CA_CERT" \
NODE_USE_ENV_PROXY=1 \
    "$CURSOR_BIN" \
    --proxy-server="http://127.0.0.1:$PROXY_PORT" \
    2>/dev/null &
CURSOR_PID=$!

sleep 3

if ! kill -0 "$CURSOR_PID" 2>/dev/null; then
    echo ""
    echo "Cursor process exited early. This can happen if another instance"
    echo "took over. Checking if Cursor is now running..."
    RUNNING=$(pgrep -f "Cursor.app/Contents/MacOS/Cursor" 2>/dev/null || true)
    if [ -n "$RUNNING" ]; then
        echo "Cursor is running but may not be using the proxy."
        echo "The proxy remains active on port $PROXY_PORT."
        echo ""
        echo "To force proxy usage, also set in Cursor Settings (JSON):"
        echo '  "http.proxy": "http://127.0.0.1:18080"'
        echo ""
        echo "Press Ctrl+C to stop the proxy when done."
        wait "$MITM_PID" 2>/dev/null || true
    else
        echo "Cursor failed to start."
        exit 1
    fi
else
    echo ""
    echo "Cursor running (PID $CURSOR_PID) through telemetry proxy."
    echo ""
    echo "  Proxy:  http://127.0.0.1:$PROXY_PORT"
    echo "  Addon:  $(basename "$ADDON_SCRIPT")"
    echo "  Logs:   tail -f $SCRIPT_DIR/cursor_blocker_deep.log"
    echo ""
    echo "Press Ctrl+C to stop the proxy. Cursor will continue without it."
    echo ""

    wait "$CURSOR_PID" 2>/dev/null || true
    echo "Cursor exited."
fi
