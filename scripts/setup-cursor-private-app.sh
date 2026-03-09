#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
APP_NAME="CursorPrivate"
APP_PATH="/Applications/${APP_NAME}.app"
PROXY_PORT=18080
CA_CERT_REL=".cursor-telemetry-blocker/.mitmproxy/mitmproxy-ca-cert.pem"

if [ "$(uname -s)" != "Darwin" ]; then
    echo "This script is macOS only."
    exit 1
fi

ACTION="${1:-install}"

build_app() {
    echo "Building ${APP_NAME}.app..."

    mkdir -p "${APP_PATH}/Contents/MacOS"
    mkdir -p "${APP_PATH}/Contents/Resources"

    cat > "${APP_PATH}/Contents/MacOS/${APP_NAME}" <<'LAUNCHER_EOF'
#!/usr/bin/env bash
PROXY_PORT=__PROXY_PORT__
PROXY_URL="http://127.0.0.1:$PROXY_PORT"
CA_CERT="$HOME/__CA_CERT_REL__"

if pgrep -f "Cursor.app/Contents/MacOS/Cursor" > /dev/null 2>&1; then
    osascript -e 'tell application "Cursor" to quit' 2>/dev/null || true
    sleep 2
    if pgrep -f "Cursor.app/Contents/MacOS/Cursor" > /dev/null 2>&1; then
        pkill -f "Cursor.app/Contents/MacOS/Cursor" 2>/dev/null || true
        sleep 1
    fi
fi

export HTTP_PROXY="$PROXY_URL"
export HTTPS_PROXY="$PROXY_URL"
export NODE_EXTRA_CA_CERTS="$CA_CERT"
export NODE_USE_ENV_PROXY=1

exec /Applications/Cursor.app/Contents/MacOS/Cursor \
    --proxy-server="$PROXY_URL" \
    "$@" 2>/dev/null
LAUNCHER_EOF

    sed -i '' "s|__PROXY_PORT__|${PROXY_PORT}|g" "${APP_PATH}/Contents/MacOS/${APP_NAME}"
    sed -i '' "s|__CA_CERT_REL__|${CA_CERT_REL}|g" "${APP_PATH}/Contents/MacOS/${APP_NAME}"

    chmod +x "${APP_PATH}/Contents/MacOS/${APP_NAME}"

    cat > "${APP_PATH}/Contents/Info.plist" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>${APP_NAME}</string>
    <key>CFBundleIdentifier</key>
    <string>com.cursor-telemetry-blocker.launcher</string>
    <key>CFBundleName</key>
    <string>Cursor Private</string>
    <key>CFBundleDisplayName</key>
    <string>Cursor Private</string>
    <key>CFBundleVersion</key>
    <string>1.0</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0</string>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>LSMinimumSystemVersion</key>
    <string>12.0</string>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>LSUIElement</key>
    <false/>
</dict>
</plist>
PLIST_EOF

    local cursor_icon="/Applications/Cursor.app/Contents/Resources/Cursor.icns"
    if [ -f "$cursor_icon" ]; then
        cp "$cursor_icon" "${APP_PATH}/Contents/Resources/AppIcon.icns"
    fi

    /System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "${APP_PATH}" 2>/dev/null || true

    echo ""
    echo "${APP_NAME}.app installed at ${APP_PATH}"
    echo ""
    echo "  Open via Spotlight: Cmd+Space > 'Cursor Private'"
    echo "  Or drag to Dock for quick access."
    echo ""
    echo "  This app will:"
    echo "    1. Quit any running Cursor instance"
    echo "    2. Relaunch Cursor with telemetry proxy on port ${PROXY_PORT}"
    echo ""
    echo "  Requires: proxy service running (make service-install-deep)"
}

remove_app() {
    if [ -d "${APP_PATH}" ]; then
        rm -rf "${APP_PATH}"
        echo "${APP_NAME}.app removed."
    else
        echo "${APP_NAME}.app not found at ${APP_PATH}"
    fi
}

case "$ACTION" in
    install)  build_app ;;
    uninstall) remove_app ;;
    *)
        echo "Usage: $0 {install|uninstall}"
        exit 1
        ;;
esac
