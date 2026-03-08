.PHONY: install run run-deep observe hosts ca-cert lint clean help

help:
	@echo "cursor-telemetry-blocker"
	@echo ""
	@echo "Usage:"
	@echo "  make install     Install dependencies with uv"
	@echo "  make run         Run in block mode (default)"
	@echo "  make run-deep    Run in deep mode (block + strip repo info)"
	@echo "  make observe     Run in observe mode (log only)"
	@echo "  make ca-cert     Install mitmproxy CA cert"
	@echo "  make hosts       Block telemetry domains via /etc/hosts"
	@echo "  make lint        Run ruff linter"
	@echo "  make clean       Remove logs and pid files"

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

lint:
	uv run ruff check src/

clean:
	rm -f *.log .mitm.pid
