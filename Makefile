.PHONY: install setup run run-deep observe dashboard hosts ca-cert lint clean help
.PHONY: service-install service-install-deep service-uninstall service-status
.PHONY: doctor doctor-fix repair upgrade sniff
.PHONY: setup-app setup-proxy remove-app remove-proxy

help:
	@echo "cursor-telemetry-blocker"
	@echo ""
	@echo "Quick Start:"
	@echo "  make setup              Full setup wizard (deps + cert + service + app)"
	@echo ""
	@echo "Usage:"
	@echo "  make install            Install dependencies with uv"
	@echo "  make run                Run in block mode (manual launch)"
	@echo "  make run-deep           Run in deep mode (manual launch)"
	@echo "  make observe            Run in observe mode (log only)"
	@echo "  make dashboard          Open interactive TUI dashboard"
	@echo "  make dashboard-demo     Dashboard with simulated events (preview)"
	@echo "  make ca-cert            Install mitmproxy CA cert"
	@echo "  make hosts              Block telemetry domains via /etc/hosts"
	@echo "  make lint               Run ruff linter"
	@echo "  make clean              Remove logs and pid files"
	@echo ""
	@echo "Service (macOS LaunchAgent):"
	@echo "  make service-install       Install auto-start service (block mode)"
	@echo "  make service-install-deep  Install auto-start service (deep mode)"
	@echo "  make service-uninstall     Remove auto-start service"
	@echo "  make service-status        Show service status"
	@echo ""
	@echo "Cursor Private App (macOS):"
	@echo "  make setup-app          Build CursorPrivate.app in /Applications"
	@echo "  make remove-app         Remove CursorPrivate.app"
	@echo "  make setup-proxy        Configure macOS system proxy (PAC file)"
	@echo "  make remove-proxy       Remove macOS system proxy config"
	@echo ""
	@echo "Maintenance:"
	@echo "  make doctor             Health check (validates everything)"
	@echo "  make doctor-fix         Health check + auto-repair"
	@echo "  make repair             Regenerate launcher from config and restart"
	@echo "  make upgrade            Pull latest code + repair + doctor"
	@echo ""
	@echo "Debug:"
	@echo "  make sniff              Block + log decoded payloads of blocked requests"

install:
	uv sync

setup:
	@echo "=== Cursor Telemetry Blocker Setup ==="
	@echo ""
	@echo "Step 1/4: Installing dependencies..."
	uv sync
	@echo ""
	@echo "Step 2/4: Installing CA certificate..."
	bash scripts/setup-ca-cert.sh
	@echo ""
	@echo "Step 3/4: Installing proxy service (deep mode)..."
	bash scripts/cursor-blocker-service.sh install deep
	@echo ""
	@echo "Step 4/4: Building CursorPrivate.app..."
	bash scripts/setup-cursor-private-app.sh install
	@echo ""
	@echo "=== Setup complete ==="
	@echo ""
	@echo "How to use:"
	@echo "  1. Open 'Cursor Private' from Spotlight (Cmd+Space)"
	@echo "  2. It will close any running Cursor and relaunch with proxy"
	@echo "  3. All telemetry is blocked; AI works normally"
	@echo ""
	@echo "Optional: block telemetry domains in /etc/hosts"
	@echo "  sudo bash scripts/setup-hosts.sh"

run:
	bash scripts/cursor-private.sh block

run-deep:
	bash scripts/cursor-private.sh deep

observe:
	bash scripts/cursor-private.sh observe

dashboard:
	uv run python -m cursor_telemetry_blocker

dashboard-demo:
	uv run python -m cursor_telemetry_blocker --demo

ca-cert:
	bash scripts/setup-ca-cert.sh

hosts:
	bash scripts/setup-hosts.sh

service-install:
	bash scripts/cursor-blocker-service.sh install block

service-install-deep:
	bash scripts/cursor-blocker-service.sh install deep

service-uninstall:
	bash scripts/cursor-blocker-service.sh uninstall

service-status:
	bash scripts/cursor-blocker-service.sh status

doctor:
	bash scripts/cursor-doctor.sh

doctor-fix:
	bash scripts/cursor-doctor.sh fix

repair:
	bash scripts/cursor-blocker-service.sh repair

upgrade:
	bash scripts/cursor-blocker-service.sh upgrade

sniff:
	uv run mitmdump --listen-port 18080 --scripts scripts/sniff-payload.py

setup-app:
	bash scripts/setup-cursor-private-app.sh install

remove-app:
	bash scripts/setup-cursor-private-app.sh uninstall

setup-proxy:
	bash scripts/setup-system-proxy.sh install

remove-proxy:
	bash scripts/setup-system-proxy.sh uninstall

lint:
	uv run ruff check src/

clean:
	rm -f *.log *.jsonl .mitm.pid
