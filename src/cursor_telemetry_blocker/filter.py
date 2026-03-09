from collections import Counter

from mitmproxy import http

from cursor_telemetry_blocker.config import (
    EVENTS_FILE,
    LOG_FILES,
    classify_passthrough,
    create_logger,
    is_blocked_domain,
    is_blocked_grpc_path,
    is_repo_tracking,
    is_sentry_envelope,
)
from cursor_telemetry_blocker.events import EventWriter, ProxyEvent


class CursorTelemetryFilter:
    def __init__(self):
        self.logger = create_logger("cursor_blocker", LOG_FILES["block"])
        self.events = EventWriter(EVENTS_FILE)
        self.blocked_count = 0
        self.passed_count = 0
        self.blocked_categories: Counter = Counter()
        self.passed_categories: Counter = Counter()
        self.logger.info("Cursor Telemetry Filter started")

    def request(self, flow: http.HTTPFlow) -> None:
        host = flow.request.pretty_host
        path = flow.request.path
        full_url = f"{host}{path}"

        if is_blocked_domain(host):
            self._block_request(flow, f"blocked domain: {host}", "telemetry")
            return

        if is_blocked_grpc_path(path):
            self._block_request(flow, f"blocked gRPC path: {path}", "telemetry")
            return

        if is_repo_tracking(path, host):
            self._block_request(flow, f"blocked repo tracking: {path}", "repo")
            return

        if is_sentry_envelope(host, path):
            self._block_request(flow, f"blocked sentry envelope: {full_url}", "sentry")
            return

        self.passed_count += 1
        classification = classify_passthrough(host, path)
        self.passed_categories[classification] += 1
        self.logger.info(f"[PASS:{classification}] {flow.request.method} {full_url}")

        request_size = len(flow.request.content) if flow.request.content else 0
        self.events.emit(ProxyEvent(
            event_type="passed",
            category=classification.lower(),
            host=host,
            path=path,
            method=flow.request.method,
            size=request_size,
            detail=f"pass:{classification}",
        ))

    def done(self):
        self.logger.info("=" * 60)
        self.logger.info("SESSION SUMMARY")
        self.logger.info("=" * 60)

        blocked_detail = ", ".join(
            f"{cat}: {count}" for cat, count in self.blocked_categories.most_common()
        )
        self.logger.info(f"  Blocked: {self.blocked_count} ({blocked_detail})")

        passed_detail = ", ".join(
            f"{cat}: {count}" for cat, count in self.passed_categories.most_common()
        )
        self.logger.info(f"  Passed:  {self.passed_count} ({passed_detail})")
        self.logger.info("=" * 60)
        self.events.close()

    def _block_request(self, flow: http.HTTPFlow, reason: str, category: str) -> None:
        self.blocked_count += 1
        self.blocked_categories[category] += 1

        host = flow.request.pretty_host
        path = flow.request.path
        content_type = flow.request.headers.get("content-type", "")
        is_grpc = "grpc" in content_type
        request_size = len(flow.request.content) if flow.request.content else 0

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
        self.events.emit(ProxyEvent(
            event_type="blocked",
            category=category,
            host=host,
            path=path,
            method=flow.request.method,
            size=request_size,
            detail=reason,
        ))


addons = [CursorTelemetryFilter()]
