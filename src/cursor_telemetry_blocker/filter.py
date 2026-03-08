from mitmproxy import http

from cursor_telemetry_blocker.config import (
    LOG_FILES,
    classify_passthrough,
    create_logger,
    is_blocked_domain,
    is_blocked_grpc_path,
    is_repo_tracking,
    is_sentry_envelope,
)


class CursorTelemetryFilter:
    def __init__(self):
        self.logger = create_logger("cursor_blocker", LOG_FILES["block"])
        self.blocked_count = 0
        self.passed_count = 0
        self.logger.info("Cursor Telemetry Filter started")

    def request(self, flow: http.HTTPFlow) -> None:
        host = flow.request.pretty_host
        path = flow.request.path
        full_url = f"{host}{path}"

        if is_blocked_domain(host):
            self._block_request(flow, f"blocked domain: {host}")
            return

        if is_blocked_grpc_path(path):
            self._block_request(flow, f"blocked gRPC path: {path}")
            return

        if is_repo_tracking(path):
            self._block_request(flow, f"blocked repo tracking: {path}")
            return

        if is_sentry_envelope(host, path):
            self._block_request(flow, f"blocked sentry envelope: {full_url}")
            return

        self.passed_count += 1
        classification = classify_passthrough(host, path)
        self.logger.info(f"[PASS:{classification}] {flow.request.method} {full_url}")

    def _block_request(self, flow: http.HTTPFlow, reason: str) -> None:
        self.blocked_count += 1

        content_type = flow.request.headers.get("content-type", "")
        is_grpc = "grpc" in content_type

        if is_grpc:
            flow.response = http.Response.make(
                200,
                b"",
                {
                    "content-type": "application/grpc",
                    "grpc-status": "0",
                    "grpc-message": "",
                },
            )
        else:
            flow.response = http.Response.make(
                200,
                b"{}",
                {"content-type": "application/json"},
            )

        self.logger.info(f"[BLOCKED #{self.blocked_count}] {reason}")


addons = [CursorTelemetryFilter()]
