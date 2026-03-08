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

    install_mitmproxy_if_missing

    local mitmdump_bin
    mitmdump_bin="$(detect_mitmdump)"

    if [ -z "$mitmdump_bin" ]; then
        echo "Error: mitmdump not found after installation attempt."
        exit 1
    fi

    local has_local_mode=false
    if "$mitmdump_bin" --help 2>&1 | grep -q "local"; then
        has_local_mode=true
    fi

    mkdir -p "$HOME/Library/LaunchAgents"

    if [ "$has_local_mode" = true ]; then
        cat > "$PLIST_PATH" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${mitmdump_bin}</string>
        <string>--mode</string>
        <string>local:Cursor</string>
        <string>--set</string>
        <string>confdir=${CONFDIR}</string>
        <string>--scripts</string>
        <string>${ADDON_SCRIPT}</string>
        <string>--quiet</string>
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
        echo "Installed LaunchAgent with transparent local mode (--mode local:Cursor)"
        echo "Cursor traffic will be intercepted automatically when you open it."
    else
        cat > "$PLIST_PATH" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${mitmdump_bin}</string>
        <string>--listen-port</string>
        <string>18080</string>
        <string>--set</string>
        <string>confdir=${CONFDIR}</string>
        <string>--set</string>
        <string>console_eventlog_verbosity=warn</string>
        <string>--scripts</string>
        <string>${ADDON_SCRIPT}</string>
        <string>--quiet</string>
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
        echo "Installed LaunchAgent with explicit proxy mode (port 18080)"
        echo ""
        echo "For transparent interception (no proxy config needed), install"
        echo "mitmproxy via Homebrew: brew install mitmproxy"
        echo "Then re-run: make service-install"
    fi

    launchctl load "$PLIST_PATH" 2>/dev/null || true
    echo ""
    echo "Service installed and started."
    echo "  Status:    launchctl list | grep cursor-telemetry"
    echo "  Logs:      tail -f $PROJECT_DIR/cursor_blocker_service.log"
    echo "  Uninstall: make service-uninstall"
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

        if grep -q "local:Cursor" "$PLIST_PATH" 2>/dev/null; then
            echo "  Mode: transparent (--mode local:Cursor)"
        else
            echo "  Mode: explicit proxy (port 18080)"
        fi
    else
        echo "LaunchAgent: not installed"
        echo "  Run: make service-install"
    fi
}

case "${1:-status}" in
    install)   install_launchagent ;;
    uninstall) uninstall_launchagent ;;
    status)    show_status ;;
    *)
        echo "Usage: $0 {install|uninstall|status} [block|deep|observe]"
        exit 1
        ;;
esac
