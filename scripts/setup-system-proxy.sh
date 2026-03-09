#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PAC_FILE="$PROJECT_DIR/config/proxy.pac"
PAC_URL="file://$PAC_FILE"

if [ "$(uname -s)" != "Darwin" ]; then
    echo "This script is macOS only."
    exit 1
fi

if [ ! -f "$PAC_FILE" ]; then
    echo "Error: PAC file not found at $PAC_FILE"
    exit 1
fi

ACTION="${1:-install}"

get_active_services() {
    local services=""
    while IFS= read -r service; do
        [[ "$service" == *"*"* ]] && continue
        [[ -z "$service" ]] && continue
        local device
        device=$(networksetup -listallhardwareports 2>/dev/null | grep -A1 "Hardware Port: $service" | grep "Device:" | awk '{print $2}' || echo "")
        if [ -n "$device" ]; then
            local status
            status=$(ifconfig "$device" 2>/dev/null | grep "status: active" || echo "")
            if [ -n "$status" ]; then
                services="$services|$service"
            fi
        fi
    done < <(networksetup -listallnetworkservices 2>/dev/null | tail -n +2)
    echo "${services#|}"
}

case "$ACTION" in
    install)
        echo "Configuring macOS system proxy with PAC file..."
        echo "  PAC: $PAC_URL"
        echo ""

        ACTIVE_SERVICES="$(get_active_services)"
        if [ -z "$ACTIVE_SERVICES" ]; then
            echo "No active network services found. Trying Wi-Fi and Ethernet..."
            ACTIVE_SERVICES="Wi-Fi|Ethernet"
        fi

        IFS='|' read -ra SERVICES <<< "$ACTIVE_SERVICES"
        for service in "${SERVICES[@]}"; do
            echo "  Setting auto-proxy on: $service"
            networksetup -setautoproxyurl "$service" "$PAC_URL" 2>/dev/null || {
                echo "    (skipped: not available)"
                continue
            }
            networksetup -setautoproxystate "$service" on 2>/dev/null || true
        done

        echo ""
        echo "System proxy configured. Only *.cursor.sh routes through proxy."
        echo "All other traffic goes DIRECT."
        echo ""
        echo "To verify: System Settings > Network > (your service) > Proxies"
        ;;

    uninstall)
        echo "Removing system proxy PAC configuration..."

        for service in "Wi-Fi" "Ethernet" "Thunderbolt Ethernet Slot 0" "AX88179A" "AX88179B"; do
            networksetup -setautoproxystate "$service" off 2>/dev/null || true
        done

        echo "System proxy removed."
        ;;

    status)
        for service in "Wi-Fi" "Ethernet"; do
            echo "=== $service ==="
            networksetup -getautoproxyurl "$service" 2>/dev/null || echo "  (not available)"
            echo ""
        done
        ;;

    *)
        echo "Usage: $0 {install|uninstall|status}"
        exit 1
        ;;
esac
