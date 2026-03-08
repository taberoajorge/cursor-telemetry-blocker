.PHONY: install run run-deep observe hosts ca-cert lint clean help
.PHONY: service-install service-uninstall service-status

help:
	@echo "cursor-telemetry-blocker"
	@echo ""
	@echo "Usage:"
	@echo "  make install            Install dependencies with uv"
	@echo "  make run                Run in block mode (manual launch)"
	@echo "  make run-deep           Run in deep mode (manual launch)"
	@echo "  make observe            Run in observe mode (log only)"
	@echo "  make ca-cert            Install mitmproxy CA cert"
	@echo "  make hosts              Block telemetry domains via /etc/hosts"
	@echo "  make lint               Run ruff linter"
	@echo "  make clean              Remove logs and pid files"
	@echo ""
	@echo "Auto-start (macOS LaunchAgent):"
	@echo "  make service-install    Install auto-start service (intercepts Cursor automatically)"
	@echo "  make service-uninstall  Remove auto-start service"
	@echo "  make service-status     Show service status"

install:
	uv sync

run:
	bash scripts/cursor-private.sh block

run-deep:
	bash scripts/cursor-private.sh deep

observe:
	bash scripts/cursor-private.sh observe

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

lint:
	uv run ruff check src/

clean:
	rm -f *.log .mitm.pid
