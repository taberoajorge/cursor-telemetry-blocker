Project: cursor-telemetry-blocker
Purpose: Block Cursor IDE telemetry via local mitmproxy while keeping AI features working.

Quick reference:
  make run          Start proxy in block mode
  make run-deep     Start proxy in deep mode (strips repo info from AI requests)
  make observe      Log traffic without blocking
  make lint         Run ruff check src/
  make install      uv sync

Source layout:
  src/cursor_telemetry_blocker/config.py      Block lists, logger factory, classification
  src/cursor_telemetry_blocker/filter.py      Block mode addon (mitmproxy)
  src/cursor_telemetry_blocker/deep_filter.py Deep mode addon (protobuf stripping)
  src/cursor_telemetry_blocker/observer.py    Observe mode addon
  src/cursor_telemetry_blocker/protobuf.py    Varint/gRPC frame encode/decode
  scripts/cursor-private.sh                   Main launcher (macOS + Linux)
  scripts/setup-ca-cert.sh                    CA certificate installer
  scripts/setup-hosts.sh                      Hosts file blocker
  config/default.toml                         Default block list configuration
  proto/aiserver_v1.proto                     Cursor AI gRPC schema reference

Adding new telemetry to block:
  1. Add domain to BLOCKED_DOMAINS in config.py
  2. Or add gRPC path to BLOCKED_GRPC_PATHS in config.py
  3. Mirror the change in config/default.toml
  4. If DNS-level blocking needed, add to scripts/setup-hosts.sh

Testing changes:
  Run in observe mode first to see traffic: make observe
  Check cursor_traffic.log for new endpoints
  Then update block lists and run in block mode: make run
