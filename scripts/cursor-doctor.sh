#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LOCAL_ENV="$PROJECT_DIR/config/local.env"
CONFDIR="$PROJECT_DIR/.mitmproxy"
CERT_PATH="$CONFDIR/mitmproxy-ca-cert.pem"
LABEL="com.cursor-telemetry-blocker"
PLIST_PATH="$HOME/Library/LaunchAgents/${LABEL}.plist"
LAUNCHER="$PROJECT_DIR/scripts/.service-launcher.sh"
SHIM="$PROJECT_DIR/scripts/deep_filter_shim.py"
HOSTS_MARKER="# Cursor Telemetry Blocker"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

pass_count=0
warn_count=0
fail_count=0
fixes_applied=0

pass_check()  { printf "  ${GREEN}ok${NC}  %s\n" "$1"; pass_count=$((pass_count + 1)); }
warn_check()  { printf "  ${YELLOW}!!${NC}  %s\n" "$1"; warn_count=$((warn_count + 1)); }
fail_check()  { printf "  ${RED}xx${NC}  %s\n" "$1"; fail_count=$((fail_count + 1)); }
section()     { printf "\n${BOLD}%s${NC}\n" "$1"; }

AUTO_FIX="${1:-}"

load_local_env() {
    PROXY_MODE="local"
    FILTER_LEVEL="deep"
    if [ -f "$LOCAL_ENV" ]; then
        # shellcheck disable=SC1090
        source "$LOCAL_ENV"
    fi
}

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

check_local_env() {
    section "Configuration"
    if [ -f "$LOCAL_ENV" ]; then
        pass_check "Local config exists ($LOCAL_ENV)"
        printf "         PROXY_MODE=%s  FILTER_LEVEL=%s\n" "$PROXY_MODE" "$FILTER_LEVEL"
    else
        warn_check "No local config found. Creating with defaults..."
        mkdir -p "$(dirname "$LOCAL_ENV")"
        cat > "$LOCAL_ENV" <<'EOF'
PROXY_MODE=local
FILTER_LEVEL=deep
EOF
        fixes_applied=$((fixes_applied + 1))
        pass_check "Created $LOCAL_ENV (PROXY_MODE=local, FILTER_LEVEL=deep)"
    fi
}

check_dependencies() {
    section "Dependencies"

    local mitmdump_bin
    mitmdump_bin="$(detect_mitmdump)"
    if [ -n "$mitmdump_bin" ]; then
        local version
        version=$("$mitmdump_bin" --version 2>/dev/null | head -1 || echo "unknown")
        pass_check "mitmdump found: $mitmdump_bin ($version)"

        if { "$mitmdump_bin" --help 2>&1 || true; } | grep -q "local"; then
            pass_check "Transparent mode (--mode local) supported"
        else
            if [ "$PROXY_MODE" = "local" ]; then
                fail_check "Transparent mode not supported by this mitmdump. Install via Homebrew: brew install mitmproxy"
            else
                warn_check "Transparent mode not available (using explicit proxy)"
            fi
        fi
    else
        fail_check "mitmdump not found. Run: brew install mitmproxy"
    fi

    local uv_bin
    uv_bin="$(detect_uv)"
    if [ -n "$uv_bin" ]; then
        pass_check "uv found: $uv_bin"
    else
        fail_check "uv not found. Run: curl -LsSf https://astral.sh/uv/install.sh | sh"
    fi
}

check_ca_cert() {
    section "CA Certificate"

    if [ -f "$CERT_PATH" ]; then
        pass_check "CA cert exists: $CERT_PATH"
    else
        fail_check "CA cert missing. Run: make ca-cert"
        return
    fi

    if security find-certificate -a -c mitmproxy /Library/Keychains/System.keychain > /dev/null 2>&1; then
        pass_check "CA cert trusted in macOS System Keychain"
    else
        fail_check "CA cert NOT in System Keychain. Run: make ca-cert"
    fi
}

check_network_extension() {
    section "Network Extension (macOS)"

    if [ "$(uname -s)" != "Darwin" ]; then
        warn_check "Not macOS, skipping network extension check"
        return
    fi

    local ext_status
    ext_status=$(systemextensionsctl list 2>/dev/null | grep "mitmproxy" || true)

    if [ -z "$ext_status" ]; then
        if [ "$PROXY_MODE" = "local" ]; then
            fail_check "mitmproxy network extension not installed. Run mitmdump once with --mode local"
        else
            warn_check "Network extension not installed (not required for explicit proxy mode)"
        fi
        return
    fi

    if echo "$ext_status" | grep -q "activated enabled"; then
        pass_check "Network extension: activated and enabled"
    elif echo "$ext_status" | grep -q "waiting for user"; then
        fail_check "Network extension waiting for approval. Go to: System Settings > General > Login Items & Extensions > Network Extensions"
    else
        warn_check "Network extension status: $ext_status"
    fi
}

check_hosts_file() {
    section "/etc/hosts"

    if grep -q "$HOSTS_MARKER" /etc/hosts 2>/dev/null; then
        local blocked_count
        blocked_count=$(grep -c "^127.0.0.1" /etc/hosts | tr -d ' ')
        pass_check "Telemetry domains blocked in /etc/hosts ($blocked_count entries)"
    else
        warn_check "No telemetry blocks in /etc/hosts. Run: make hosts"
    fi
}

check_service() {
    section "LaunchAgent Service"

    if [ ! -f "$PLIST_PATH" ]; then
        fail_check "LaunchAgent not installed. Run: make service-install"
        return
    fi
    pass_check "Plist installed: $PLIST_PATH"

    local running
    running=$(launchctl list 2>/dev/null | grep "$LABEL" || true)
    if [ -n "$running" ]; then
        pass_check "Service is running"
    else
        fail_check "Service not running. Run: make repair"
        return
    fi

    local mitmdump_pid
    mitmdump_pid=$(pgrep -f "mitmdump.*cursor.telemetry" 2>/dev/null | head -1 || true)
    if [ -n "$mitmdump_pid" ]; then
        local mitmdump_cmd
        mitmdump_cmd=$(ps -p "$mitmdump_pid" -o args= 2>/dev/null || true)

        if echo "$mitmdump_cmd" | grep -q "mode local:Cursor"; then
            pass_check "Running in transparent mode (--mode local:Cursor)"
            if [ "$PROXY_MODE" != "local" ]; then
                warn_check "Config says PROXY_MODE=$PROXY_MODE but running in local mode"
            fi
        elif echo "$mitmdump_cmd" | grep -q "listen-port"; then
            pass_check "Running in explicit proxy mode"
            if [ "$PROXY_MODE" = "local" ]; then
                fail_check "Config says PROXY_MODE=local but running in explicit mode. Run: make repair"
            fi
        fi

        if echo "$mitmdump_cmd" | grep -q "deep_filter"; then
            pass_check "Using deep filter (block + strip repo data)"
        elif echo "$mitmdump_cmd" | grep -q "filter.py"; then
            if [ "$FILTER_LEVEL" = "deep" ]; then
                fail_check "Config says FILTER_LEVEL=deep but running filter.py. Run: make repair"
            else
                pass_check "Using block filter"
            fi
        elif echo "$mitmdump_cmd" | grep -q "observer"; then
            warn_check "Running in observe mode (logging only, not blocking)"
        fi
    else
        fail_check "No mitmdump process found for this project"
    fi
}

check_launcher_integrity() {
    section "Launcher Integrity"

    if [ ! -f "$LAUNCHER" ]; then
        fail_check "Launcher script missing: $LAUNCHER"
        if [ "$AUTO_FIX" = "fix" ]; then
            printf "         Regenerating launcher...\n"
            bash "$SCRIPT_DIR/cursor-blocker-service.sh" install "$FILTER_LEVEL" 2>/dev/null
            fixes_applied=$((fixes_applied + 1))
            pass_check "Launcher regenerated"
        fi
        return
    fi

    pass_check "Launcher exists: $LAUNCHER"

    local expected_mode_flag=""
    if [ "$PROXY_MODE" = "local" ]; then
        expected_mode_flag="mode local:Cursor"
    else
        expected_mode_flag="listen-port"
    fi

    if grep -q "$expected_mode_flag" "$LAUNCHER" 2>/dev/null; then
        pass_check "Launcher matches PROXY_MODE=$PROXY_MODE"
    else
        fail_check "Launcher does NOT match PROXY_MODE=$PROXY_MODE"
        if [ "$AUTO_FIX" = "fix" ]; then
            printf "         Regenerating launcher from config...\n"
            bash "$PROJECT_DIR/scripts/generate-launcher.sh"
            fixes_applied=$((fixes_applied + 1))
            pass_check "Launcher regenerated to match config"
        else
            printf "         Run: make repair\n"
        fi
    fi

    if [ "$FILTER_LEVEL" = "deep" ]; then
        if grep -q "deep_filter" "$LAUNCHER" 2>/dev/null; then
            pass_check "Launcher uses deep filter"
        else
            fail_check "Launcher does not use deep filter (FILTER_LEVEL=deep)"
            if [ "$AUTO_FIX" = "fix" ]; then
                bash "$PROJECT_DIR/scripts/generate-launcher.sh"
                fixes_applied=$((fixes_applied + 1))
            fi
        fi
    fi
}

check_recent_leaks() {
    section "Recent Telemetry Leaks"

    local log_files=()
    if [ -f "$PROJECT_DIR/cursor_blocker_deep.log" ]; then
        log_files+=("$PROJECT_DIR/cursor_blocker_deep.log")
    fi
    if [ -f "$PROJECT_DIR/cursor_blocker.log" ]; then
        log_files+=("$PROJECT_DIR/cursor_blocker.log")
    fi

    local log_file=""
    if [ ${#log_files[@]} -gt 0 ]; then
        log_file="${log_files[0]}"
    fi

    if [ -z "$log_file" ]; then
        warn_check "No proxy logs found (service may not have intercepted traffic yet)"
        return
    fi

    local sentry_leaks
    sentry_leaks=$({ grep "PASS.*sentry\.io" "$log_file" 2>/dev/null || true; } | wc -l | tr -d ' ')
    if [ "$sentry_leaks" -gt 0 ]; then
        fail_check "Sentry telemetry leaked $sentry_leaks time(s) in recent session"
    else
        pass_check "No Sentry leaks detected"
    fi

    local commit_leaks
    commit_leaks=$({ grep "PASS.*ReportCommitAiAnalytics" "$log_file" 2>/dev/null || true; } | wc -l | tr -d ' ')
    if [ "$commit_leaks" -gt 0 ]; then
        fail_check "Commit analytics leaked $commit_leaks time(s)"
    else
        pass_check "No commit analytics leaks"
    fi

    local analytics_leaks
    analytics_leaks=$({ grep "PASS.*AnalyticsService" "$log_file" 2>/dev/null || true; } | wc -l | tr -d ' ')
    if [ "$analytics_leaks" -gt 0 ]; then
        fail_check "AnalyticsService leaked $analytics_leaks time(s)"
    else
        pass_check "No AnalyticsService leaks"
    fi

    local repo_leaks
    repo_leaks=$({ grep "PASS.*GetTeamRepos" "$log_file" 2>/dev/null || true; } | wc -l | tr -d ' ')
    if [ "$repo_leaks" -gt 0 ]; then
        fail_check "GetTeamRepos leaked $repo_leaks time(s)"
    else
        pass_check "No repo listing leaks"
    fi

    local total_blocked
    total_blocked=$({ grep "\[BLOCKED" "$log_file" 2>/dev/null || true; } | wc -l | tr -d ' ')
    local total_passed
    total_passed=$({ grep "\[PASS" "$log_file" 2>/dev/null || true; } | wc -l | tr -d ' ')
    printf "         Session stats: %s blocked, %s passed\n" "$total_blocked" "$total_passed"
}

main() {
    printf "\n${BOLD}Cursor Telemetry Blocker${NC} ${GREEN}doctor${NC}\n"

    load_local_env
    check_local_env
    check_dependencies
    check_ca_cert
    check_network_extension
    check_hosts_file
    check_service
    check_launcher_integrity
    check_recent_leaks

    printf "\n${BOLD}Summary${NC}\n"
    printf "  ${GREEN}%d passed${NC}  " "$pass_count"
    if [ "$warn_count" -gt 0 ]; then
        printf "${YELLOW}%d warnings${NC}  " "$warn_count"
    fi
    if [ "$fail_count" -gt 0 ]; then
        printf "${RED}%d failed${NC}  " "$fail_count"
    fi
    if [ "$fixes_applied" -gt 0 ]; then
        printf "(${GREEN}%d auto-fixed${NC})" "$fixes_applied"
    fi
    printf "\n"

    if [ "$fail_count" -gt 0 ] && [ "$AUTO_FIX" != "fix" ]; then
        printf "\n  Run ${BOLD}make doctor-fix${NC} to auto-repair what can be fixed.\n"
    fi

    if [ "$fail_count" -gt 0 ]; then
        exit 1
    fi
}

main
