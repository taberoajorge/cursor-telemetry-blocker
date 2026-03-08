cursor-telemetry-blocker is a local mitmproxy-based proxy that blocks Cursor IDE telemetry while preserving AI functionality.

Stack: Python 3.12+, mitmproxy, protobuf, uv, bash.
Structure: src/cursor_telemetry_blocker/ (Python package), scripts/ (shell), config/ (TOML), proto/ (gRPC schema).

Three proxy modes:
  block (filter.py): Blocks telemetry domains and gRPC paths, passes AI/auth traffic.
  deep (deep_filter.py): Same as block + strips repository info from gRPC protobuf payloads.
  observe (observer.py): Logs all traffic without blocking.

All block lists live in src/cursor_telemetry_blocker/config.py (single source of truth).
Protobuf encode/decode utilities are in protobuf.py.

To add a new blocked domain: add it to BLOCKED_DOMAINS in config.py and config/default.toml.
To add a new blocked gRPC path: add it to BLOCKED_GRPC_PATHS in config.py and config/default.toml.
To add a new stripped protobuf field: update REPO_STRING_FIELDS in protobuf.py.

Key commands:
  make install         Install dependencies
  make run             Block mode
  make run-deep        Deep mode
  make observe         Observe mode
  make ca-cert         Install CA cert
  make hosts           Block domains via /etc/hosts
  make lint            Run ruff linter

Coding conventions:
  No single-character variables.
  No comments or JSDoc.
  No eslint-disable.
  Imports from config.py for all shared constants.
  Ruff for linting (E, F, W, I rules).
  Line length 100.
