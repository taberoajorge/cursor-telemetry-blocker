#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LOCAL_ENV="$PROJECT_DIR/config/local.env"
CONFDIR="$PROJECT_DIR/.mitmproxy"
LAUNCHER="$PROJECT_DIR/scripts/.service-launcher.sh"
SHIM="$PROJECT_DIR/scripts/deep_filter_shim.py"
SRC_DIR="$PROJECT_DIR/src/cursor_telemetry_blocker"

PROXY_MODE="local"
FILTER_LEVEL="deep"

if [ -f "$LOCAL_ENV" ]; then
    # shellcheck disable=SC1090
    source "$LOCAL_ENV"
fi

detect_mitmdump() {
    for candidate in "/opt/homebrew/bin/mitmdump" "/usr/local/bin/mitmdump"; do
        if [ -x "$candidate" ]; then
            echo "$candidate"
            return
        fi
    done
    command -v mitmdump 2>/dev/null || echo ""
}

detect_uv() {
    for candidate in "$HOME/.local/bin/uv" "/opt/homebrew/bin/uv" "/usr/local/bin/uv"; do
        if [ -x "$candidate" ]; then
            echo "$candidate"
            return
        fi
    done
    command -v uv 2>/dev/null || echo ""
}

resolve_addon() {
    case "$FILTER_LEVEL" in
        observe) echo "$SRC_DIR/observer.py" ;;
        deep)    echo "$SRC_DIR/deep_filter.py" ;;
        *)       echo "$SRC_DIR/filter.py" ;;
    esac
}

MITMDUMP_BIN="$(detect_mitmdump)"
UV_BIN="$(detect_uv)"
ADDON="$(resolve_addon)"

if [ "$PROXY_MODE" = "local" ] && [ -n "$MITMDUMP_BIN" ]; then
    has_local=$({ "$MITMDUMP_BIN" --help 2>&1 || true; } | grep -q "local" && echo "yes" || echo "no")

    if [ "$has_local" = "yes" ]; then
        cat > "$LAUNCHER" <<LAUNCHER_EOF
#!/usr/bin/env bash
cd "${PROJECT_DIR}"
exec ${MITMDUMP_BIN} \\
    --mode local:Cursor \\
    --set confdir="${CONFDIR}" \\
    --scripts "${SHIM}" \\
    --quiet
LAUNCHER_EOF
        echo "Generated launcher: transparent mode (--mode local:Cursor) + deep filter shim"
    else
        echo "Warning: mitmdump does not support --mode local. Falling back to explicit proxy."
        PROXY_MODE="explicit"
    fi
fi

if [ "$PROXY_MODE" != "local" ]; then
    if [ -z "$UV_BIN" ]; then
        echo "Error: uv not found for explicit proxy mode"
        exit 1
    fi

    cat > "$LAUNCHER" <<LAUNCHER_EOF
#!/usr/bin/env bash
cd "${PROJECT_DIR}"
exec ${UV_BIN} run mitmdump \\
    --listen-port 18080 \\
    --set confdir="${CONFDIR}" \\
    --set console_eventlog_verbosity=warn \\
    --scripts "${ADDON}" \\
    --quiet
LAUNCHER_EOF
    echo "Generated launcher: explicit proxy (port 18080) + ${FILTER_LEVEL} filter"
fi

chmod +x "$LAUNCHER"
