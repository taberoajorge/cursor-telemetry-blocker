#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SRC_DIR="$PROJECT_DIR/src/cursor_telemetry_blocker"
CONFDIR="$PROJECT_DIR/.mitmproxy"
LABEL="com.cursor-telemetry-blocker"
PLIST_PATH="$HOME/Library/LaunchAgents/${LABEL}.plist"
OS_TYPE="$(uname -s)"

MODE="${2:-block}"

resolve_addon_script() {
    case "$MODE" in
        observe) echo "$SRC_DIR/observer.py" ;;
        deep)    echo "$SRC_DIR/deep_filter.py" ;;
        *)       echo "$SRC_DIR/filter.py" ;;
    esac
}

ADDON_SCRIPT="$(resolve_addon_script)"

detect_mitmdump() {
    for candidate in \
        "/opt/homebrew/bin/mitmdump" \
        "/usr/local/bin/mitmdump"; do
        if [ -x "$candidate" ]; then
            echo "$candidate"
            return
        fi
    done

    if command -v mitmdump > /dev/null 2>&1; then
        command -v mitmdump
        return
    fi

    echo ""
}

detect_uv() {
    for candidate in \
        "$HOME/.local/bin/uv" \
        "/opt/homebrew/bin/uv" \
        "/usr/local/bin/uv"; do
        if [ -x "$candidate" ]; then
            echo "$candidate"
            return
        fi
    done

    if command -v uv > /dev/null 2>&1; then
        command -v uv
        return
    fi

    echo ""
}

install_mitmproxy_if_missing() {
    local existing
    existing="$(detect_mitmdump)"
    if [ -n "$existing" ]; then
        return 0
    fi

    echo "mitmproxy not found. Installing via Homebrew..."

    if ! command -v brew > /dev/null 2>&1; then
        echo "Homebrew not found. Installing Homebrew first..."
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        if [ -x "/opt/homebrew/bin/brew" ]; then
            eval "$(/opt/homebrew/bin/brew shellenv)"
        elif [ -x "/usr/local/bin/brew" ]; then
            eval "$(/usr/local/bin/brew shellenv)"
        fi
    fi

    if ! command -v brew > /dev/null 2>&1; then
        echo "Error: Homebrew installation failed."
        exit 1
    fi

    # Fix Homebrew directory permissions (common issue on Intel Macs)
    local unwritable
    unwritable="$(brew doctor 2>&1 | grep -A1 'not writable' | grep '^ ' | xargs 2>/dev/null || true)"
    if [ -n "$unwritable" ]; then
        echo "Fixing Homebrew directory permissions..."
        for dir in $unwritable; do
            if [ -d "$dir" ]; then
                sudo chown -R "$(whoami)" "$dir"
                chmod u+w "$dir"
            fi
        done
    fi

    brew install mitmproxy

    existing="$(detect_mitmdump)"
    if [ -z "$existing" ]; then
        echo "Error: mitmproxy installation failed."
        exit 1
    fi

    echo "mitmproxy installed successfully."
}

install_launchagent() {
    if [ "$OS_TYPE" != "Darwin" ]; then
        echo "LaunchAgent is macOS only. On Linux, use systemd instead."
        exit 1
    fi

    local uv_bin
    uv_bin="$(detect_uv)"

    if [ -z "$uv_bin" ]; then
        echo "Error: uv not found. Install it first: curl -LsSf https://astral.sh/uv/install.sh | bash"
        exit 1
    fi

    (cd "$PROJECT_DIR" && "$uv_bin" sync --quiet 2>/dev/null || true)

    install_mitmproxy_if_missing

    local local_env="$PROJECT_DIR/config/local.env"
    if [ ! -f "$local_env" ]; then
        local mitmdump_bin
        mitmdump_bin="$(detect_mitmdump)"
        local detected_mode="explicit"
        if [ -n "$mitmdump_bin" ] && { "$mitmdump_bin" --help 2>&1 || true; } | grep -q "local"; then
            detected_mode="local"
        fi
        mkdir -p "$PROJECT_DIR/config"
        cat > "$local_env" <<LOCAL_EOF
PROXY_MODE=${detected_mode}
FILTER_LEVEL=${MODE}
LOCAL_EOF
        echo "Created config/local.env (PROXY_MODE=${detected_mode}, FILTER_LEVEL=${MODE})"
    fi

    bash "$SCRIPT_DIR/generate-launcher.sh"

    local launcher="${PROJECT_DIR}/scripts/.service-launcher.sh"
    mkdir -p "$HOME/Library/LaunchAgents"

    cat > "$PLIST_PATH" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>${launcher}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>${PROJECT_DIR}/cursor_blocker_service.log</string>
    <key>StandardErrorPath</key>
    <string>${PROJECT_DIR}/cursor_blocker_service.log</string>
</dict>
</plist>
PLIST_EOF

    launchctl load "$PLIST_PATH" 2>/dev/null || true
    echo ""
    echo "Service installed and started."
    echo "  Status:  make service-status"
    echo "  Doctor:  make doctor"
    echo "  Logs:    tail -f $PROJECT_DIR/cursor_blocker_service.log"
}

uninstall_launchagent() {
    if [ -f "$PLIST_PATH" ]; then
        launchctl unload "$PLIST_PATH" 2>/dev/null || true
        rm -f "$PLIST_PATH"
        echo "LaunchAgent removed. Telemetry blocker will no longer auto-start."
    else
        echo "No LaunchAgent found at $PLIST_PATH"
    fi
}

show_status() {
    if [ -f "$PLIST_PATH" ]; then
        echo "LaunchAgent: installed"
        echo "  Plist: $PLIST_PATH"
        local running
        running=$(launchctl list 2>/dev/null | grep "$LABEL" || true)
        if [ -n "$running" ]; then
            echo "  Status: running"
            echo "  $running"
        else
            echo "  Status: not running"
        fi

        local launcher="${PROJECT_DIR}/scripts/.service-launcher.sh"
        if [ -f "$launcher" ] && grep -q "local:Cursor" "$launcher" 2>/dev/null; then
            echo "  Mode: transparent (--mode local:Cursor)"
        else
            echo "  Mode: explicit proxy (port 18080)"
        fi
    else
        echo "LaunchAgent: not installed"
        echo "  Run: make service-install"
    fi
}

repair_service() {
    echo "Repairing service from config/local.env..."

    bash "$SCRIPT_DIR/generate-launcher.sh"

    if [ -f "$PLIST_PATH" ]; then
        launchctl unload "$PLIST_PATH" 2>/dev/null || true
        sleep 1
        launchctl load "$PLIST_PATH" 2>/dev/null || true
        echo "Service restarted with updated launcher."
    else
        echo "No plist found. Run: make service-install"
        exit 1
    fi

    echo ""
    echo "Running doctor..."
    bash "$SCRIPT_DIR/cursor-doctor.sh" || true
}

upgrade_service() {
    echo "Upgrading cursor-telemetry-blocker..."

    local uv_bin
    uv_bin="$(detect_uv)"
    if [ -z "$uv_bin" ]; then
        echo "Error: uv not found. Install it first: curl -LsSf https://astral.sh/uv/install.sh | bash"
        exit 1
    fi

    cd "$PROJECT_DIR"

    local current_branch
    current_branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "main")

    echo "Pulling latest from origin/${current_branch}..."
    if ! git pull --quiet origin "$current_branch"; then
        echo "Error: git pull failed. Fix conflicts or network issues and retry."
        exit 1
    fi

    echo "Syncing dependencies..."
    (cd "$PROJECT_DIR" && "$uv_bin" sync --quiet) || {
        echo "Warning: uv sync failed. Dependencies may be outdated."
    }

    echo "Regenerating launcher from config/local.env..."
    repair_service
}

case "${1:-status}" in
    install)   install_launchagent ;;
    uninstall) uninstall_launchagent ;;
    status)    show_status ;;
    repair)    repair_service ;;
    upgrade)   upgrade_service ;;
    *)
        echo "Usage: $0 {install|uninstall|status|repair|upgrade} [block|deep|observe]"
        exit 1
        ;;
esac
