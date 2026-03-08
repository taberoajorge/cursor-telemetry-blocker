.PHONY: install run run-deep observe dashboard hosts ca-cert lint clean help
.PHONY: service-install service-uninstall service-status
.PHONY: doctor doctor-fix repair upgrade

help:
	@echo "cursor-telemetry-blocker"
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
	@echo "  make service-install    Install auto-start service"
	@echo "  make service-uninstall  Remove auto-start service"
	@echo "  make service-status     Show service status"
	@echo ""
	@echo "Maintenance:"
	@echo "  make doctor             Health check (validates everything)"
	@echo "  make doctor-fix         Health check + auto-repair"
	@echo "  make repair             Regenerate launcher from config and restart"
	@echo "  make upgrade            Pull latest code + repair + doctor"

install:
	uv sync

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

lint:
	uv run ruff check src/

clean:
	rm -f *.log *.jsonl .mitm.pid
