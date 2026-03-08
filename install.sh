#!/usr/bin/env bash
set -euo pipefail

readonly INSTALLER_VERSION="1.0.0"
readonly REPO_URL="https://github.com/taberoajorge/cursor-telemetry-blocker.git"
readonly INSTALL_DIR="${CURSOR_TELEMETRY_HOME:-$HOME/.cursor-telemetry-blocker}"

readonly GREEN='\033[0;32m'
readonly YELLOW='\033[1;33m'
readonly RED='\033[0;31m'
readonly BLUE='\033[0;34m'
readonly BOLD='\033[1m'
readonly NC='\033[0m'

info()    { printf "${BLUE}[INFO]${NC} %s\n" "$*"; }
warn()    { printf "${YELLOW}[WARN]${NC} %s\n" "$*" >&2; }
error()   { printf "${RED}[ERROR]${NC} %s\n" "$*" >&2; }
success() { printf "${GREEN}  [ok]${NC} %s\n" "$*"; }
step()    { printf "\n${BOLD}==> %s${NC}\n" "$*"; }

show_banner() {
    printf "\n${BOLD}"
    echo "  Cursor Telemetry Blocker"
    echo "  v${INSTALLER_VERSION}"
    printf "${NC}"
    echo "  Block Cursor IDE telemetry while preserving AI features"
    echo ""
}

show_help() {
    echo "Usage: install.sh [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --mode MODE     Default proxy mode: block, deep, observe (default: block)"
    echo "  --no-hosts      Skip /etc/hosts configuration"
    echo "  --no-cert       Skip CA certificate installation"
    echo "  --no-alias      Skip shell alias creation"
    echo "  --no-service    Skip auto-start service setup"
    echo "  --dry-run       Preview what will be installed"
    echo "  --version       Show version"
    echo "  --help          Show this help"
}

command_exists() {
    command -v "$1" > /dev/null 2>&1
}

detect_os() {
    case "$(uname -s)" in
        Darwin) echo "macos" ;;
        Linux)  echo "linux" ;;
        *)      echo "unknown" ;;
    esac
}

detect_shell() {
    basename "${SHELL:-/bin/bash}"
}

get_shell_rc() {
    case "$(detect_shell)" in
        zsh)  echo "$HOME/.zshrc" ;;
        fish) echo "$HOME/.config/fish/config.fish" ;;
        *)    echo "$HOME/.bashrc" ;;
    esac
}

install_uv() {
    if command_exists uv; then
        success "uv already installed ($(uv --version))"
        return 0
    fi

    info "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"

    if command_exists uv; then
        success "uv installed ($(uv --version))"
    else
        error "Failed to install uv"
        exit 1
    fi
}

clone_or_update() {
    if [ -d "$INSTALL_DIR/.git" ]; then
        info "Updating existing installation..."
        cd "$INSTALL_DIR"
        git pull --quiet origin main
        success "Updated to latest version"
    else
        info "Cloning repository..."
        git clone --quiet "$REPO_URL" "$INSTALL_DIR"
        success "Cloned to $INSTALL_DIR"
    fi
}

setup_dependencies() {
    cd "$INSTALL_DIR"
    info "Installing Python dependencies..."
    uv sync --quiet
    success "Dependencies installed"
}

setup_ca_cert() {
    cd "$INSTALL_DIR"

    if [ ! -d "$INSTALL_DIR/.mitmproxy" ]; then
        info "Generating mitmproxy CA certificate (first run)..."
        uv run mitmdump --listen-port 0 --set confdir="$INSTALL_DIR/.mitmproxy" --quiet &
        TEMP_PID=$!
        sleep 3
        kill "$TEMP_PID" 2>/dev/null || true
        wait "$TEMP_PID" 2>/dev/null || true
    fi

    if [ -f "$INSTALL_DIR/.mitmproxy/mitmproxy-ca-cert.pem" ]; then
        echo ""
        read -p "Install CA cert into system trust store? (requires sudo) [Y/n] " CERT_REPLY
        if [[ ! "${CERT_REPLY:-Y}" =~ ^[Nn]$ ]]; then
            bash scripts/setup-ca-cert.sh
            success "CA certificate installed"
        else
            warn "Skipped CA cert installation. TLS interception will not work."
        fi
    else
        warn "Could not generate CA cert. Run 'make ca-cert' later."
    fi
}

setup_hosts() {
    echo ""
    read -p "Block telemetry domains in /etc/hosts? (requires sudo) [Y/n] " HOSTS_REPLY
    if [[ ! "${HOSTS_REPLY:-Y}" =~ ^[Nn]$ ]]; then
        bash "$INSTALL_DIR/scripts/setup-hosts.sh"
        success "Hosts file updated"
    else
        info "Skipped hosts file. Run 'make hosts' later."
    fi
}

setup_alias() {
    local rc_file
    rc_file="$(get_shell_rc)"
    local alias_line="alias cursor-private='bash $INSTALL_DIR/scripts/cursor-private.sh'"

    echo ""
    read -p "Create 'cursor-private' shell alias? [Y/n] " ALIAS_REPLY
    if [[ ! "${ALIAS_REPLY:-Y}" =~ ^[Nn]$ ]]; then
        if [ -f "$rc_file" ] && grep -qF "cursor-private" "$rc_file" 2>/dev/null; then
            success "Alias already exists in $rc_file"
        else
            echo "" >> "$rc_file"
            echo "$alias_line" >> "$rc_file"
            success "Alias added to $rc_file"
        fi
    fi
}

setup_autostart() {
    local os_name
    os_name="$(detect_os)"

    if [ "$os_name" != "macos" ]; then
        info "Auto-start service is currently macOS only (LaunchAgent)."
        info "On Linux, you can create a systemd user service manually."
        return 0
    fi

    echo ""
    echo "  Auto-start makes the telemetry blocker run automatically"
    echo "  whenever you log in. Cursor traffic is intercepted transparently"
    echo "  without needing to launch Cursor from the terminal."
    echo ""

    local has_brew_mitmproxy=false
    if [ -x "/opt/homebrew/bin/mitmdump" ] || [ -x "/usr/local/bin/mitmdump" ]; then
        has_brew_mitmproxy=true
    fi

    if [ "$has_brew_mitmproxy" = true ]; then
        echo "  Homebrew mitmproxy detected: transparent interception available."
        echo "  This uses --mode local:Cursor (macOS Network Extension)."
        echo "  No proxy env vars needed. Just open Cursor normally."
    else
        echo "  Note: Homebrew mitmproxy not found. The service will use"
        echo "  explicit proxy mode (port 18080). For transparent interception,"
        echo "  install mitmproxy via Homebrew: brew install mitmproxy"
    fi
    echo ""

    read -p "Install auto-start service? [Y/n] " SERVICE_REPLY
    if [[ ! "${SERVICE_REPLY:-Y}" =~ ^[Nn]$ ]]; then
        echo ""
        echo "  1) block   Block telemetry, pass AI requests (recommended)"
        echo "  2) deep    Block + strip repo names from AI requests"
        echo "  3) observe Log only, no blocking"
        echo ""
        read -p "Select mode for auto-start [1]: " MODE_CHOICE
        local service_mode="block"
        case "${MODE_CHOICE:-1}" in
            2) service_mode="deep" ;;
            3) service_mode="observe" ;;
            *) service_mode="block" ;;
        esac

        bash "$INSTALL_DIR/scripts/cursor-blocker-service.sh" install "$service_mode"
        success "Auto-start service installed (mode: $service_mode)"
    else
        info "Skipped auto-start. Run 'make service-install' later."
    fi
}

show_summary() {
    local os_name
    os_name="$(detect_os)"
    local plist_path="$HOME/Library/LaunchAgents/com.cursor-telemetry-blocker.plist"

    echo ""
    printf "${GREEN}${BOLD}Installation complete!${NC}\n"
    echo ""

    if [ "$os_name" = "macos" ] && [ -f "$plist_path" ]; then
        echo "Auto-start is enabled. Just open Cursor normally."
        echo "The telemetry blocker runs in the background automatically."
        echo ""
        echo "Service management:"
        echo "  make service-status     Check if the service is running"
        echo "  make service-uninstall  Disable auto-start"
        echo ""
    fi

    echo "Manual launch:"
    echo "  cd $INSTALL_DIR"
    echo "  make run            Block mode (recommended)"
    echo "  make run-deep       Block + strip repo info from AI requests"
    echo "  make observe        Log only, no blocking"
    echo ""
    echo "Or use the alias:"
    echo "  cursor-private          Block mode"
    echo "  cursor-private deep     Deep mode"
    echo ""
    echo "Docs: https://github.com/taberoajorge/cursor-telemetry-blocker"
}

main() {
    local skip_hosts=false
    local skip_cert=false
    local skip_alias=false
    local skip_service=false
    local dry_run=false

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --no-hosts)   skip_hosts=true; shift ;;
            --no-cert)    skip_cert=true; shift ;;
            --no-alias)   skip_alias=true; shift ;;
            --no-service) skip_service=true; shift ;;
            --dry-run)    dry_run=true; shift ;;
            --version)    echo "cursor-telemetry-blocker installer v${INSTALLER_VERSION}"; exit 0 ;;
            --help)       show_help; exit 0 ;;
            --mode)       shift; shift ;;
            *)            error "Unknown option: $1"; show_help; exit 1 ;;
        esac
    done

    show_banner

    local os_name
    os_name="$(detect_os)"
    if [ "$os_name" = "unknown" ]; then
        error "Unsupported operating system: $(uname -s)"
        exit 1
    fi

    step "Detecting environment"
    success "OS: $os_name ($(uname -m))"
    success "Shell: $(detect_shell)"

    if [ "$dry_run" = true ]; then
        echo ""
        info "[DRY RUN] Would install to: $INSTALL_DIR"
        info "[DRY RUN] Would install uv (if missing)"
        info "[DRY RUN] Would clone/update repository"
        info "[DRY RUN] Would install Python dependencies"
        [ "$skip_cert" = false ] && info "[DRY RUN] Would install CA cert"
        [ "$skip_hosts" = false ] && info "[DRY RUN] Would update /etc/hosts"
        [ "$skip_alias" = false ] && info "[DRY RUN] Would create shell alias"
        [ "$skip_service" = false ] && info "[DRY RUN] Would install auto-start service"
        exit 0
    fi

    step "Installing uv"
    install_uv

    step "Setting up repository"
    clone_or_update

    step "Installing dependencies"
    setup_dependencies

    if [ "$skip_cert" = false ]; then
        step "CA Certificate"
        setup_ca_cert
    fi

    if [ "$skip_hosts" = false ]; then
        step "Hosts file"
        setup_hosts
    fi

    if [ "$skip_alias" = false ]; then
        step "Shell alias"
        setup_alias
    fi

    if [ "$skip_service" = false ]; then
        step "Auto-start service"
        setup_autostart
    fi

    show_summary
}

main "$@"
