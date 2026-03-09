from collections import Counter

from mitmproxy import http

from cursor_telemetry_blocker.config import (
    EVENTS_FILE,
    LOG_FILES,
    create_logger,
    is_blocked_domain,
    is_blocked_grpc_path,
    is_repo_tracking,
    is_sentry_envelope,
    should_strip_repo,
)
from cursor_telemetry_blocker.events import EventWriter, ProxyEvent
from cursor_telemetry_blocker.protobuf import (
    decode_grpc_frames,
    encode_grpc_frames,
    strip_repo_info_from_protobuf,
)


class CursorDeepTelemetryFilter:
    def __init__(self):
        self.logger = create_logger("cursor_deep_blocker", LOG_FILES["deep"])
        self.events = EventWriter(EVENTS_FILE)
        self.blocked_count = 0
        self.stripped_count = 0
        self.passed_count = 0
        self.blocked_categories: Counter = Counter()
        self.passed_categories: Counter = Counter()
        self.logger.info("Cursor Deep Telemetry Filter started (with protobuf stripping)")

    def responseheaders(self, flow: http.HTTPFlow) -> None:
        flow.response.stream = True

    def request(self, flow: http.HTTPFlow) -> None:
        host = flow.request.pretty_host
        path = flow.request.path
        content_type = flow.request.headers.get("content-type", "")
        is_grpc = "grpc" in content_type

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
            self._block_request(flow, f"blocked sentry: {host}{path}", "sentry")
            return

        if is_grpc and should_strip_repo(path) and flow.request.content:
            self._strip_repo_from_grpc(flow)
            return

        self.passed_count += 1
        self.passed_categories["other"] += 1
        self.logger.info(f"[PASS] {flow.request.method} {host}{path}")

        request_size = len(flow.request.content) if flow.request.content else 0
        self.events.emit(ProxyEvent(
            event_type="passed",
            category="other",
            host=host,
            path=path,
            method=flow.request.method,
            size=request_size,
            detail="pass",
        ))

    def done(self):
        self.logger.info("=" * 60)
        self.logger.info("SESSION SUMMARY")
        self.logger.info("=" * 60)

        blocked_detail = ", ".join(
            f"{cat}: {count}" for cat, count in self.blocked_categories.most_common()
        )
        self.logger.info(f"  Blocked:  {self.blocked_count} ({blocked_detail})")
        self.logger.info(f"  Stripped: {self.stripped_count} repo info payloads")

        passed_detail = ", ".join(
            f"{cat}: {count}" for cat, count in self.passed_categories.most_common()
        )
        self.logger.info(f"  Passed:   {self.passed_count} ({passed_detail})")
        self.logger.info("=" * 60)
        self.events.close()

    def _strip_repo_from_grpc(self, flow: http.HTTPFlow) -> None:
        host = flow.request.pretty_host
        path = flow.request.path
        try:
            original_body = flow.request.content
            if not original_body or len(original_body) < 5:
                return

            frames = decode_grpc_frames(original_body)
            modified_frames = []
            any_modified = False
            total_stripped = 0

            for compressed, frame_data in frames:
                if compressed:
                    modified_frames.append((compressed, frame_data))
                    continue

                original_len = len(frame_data)
                stripped_data = strip_repo_info_from_protobuf(frame_data)
                modified_len = len(stripped_data)

                if modified_len != original_len:
                    any_modified = True
                    bytes_removed = original_len - modified_len
                    total_stripped += bytes_removed
                    self.logger.info(
                        f"[STRIP] Removed {bytes_removed}B repo data from {path}"
                    )

                modified_frames.append((False, stripped_data))

            if any_modified:
                flow.request.content = encode_grpc_frames(modified_frames)
                self.stripped_count += 1

            self.passed_count += 1
            tag = "STRIP+PASS" if any_modified else "PASS"
            category = "stripped" if any_modified else "ai"
            self.passed_categories[category] += 1
            self.logger.info(f"[{tag}] {flow.request.method} {host}{path}")

            event_type = "stripped" if any_modified else "passed"
            request_size = len(flow.request.content) if flow.request.content else 0
            self.events.emit(ProxyEvent(
                event_type=event_type,
                category=category,
                host=host,
                path=path,
                method=flow.request.method,
                size=request_size,
                detail=tag,
                stripped_bytes=total_stripped,
            ))

        except Exception as error:
            self.logger.warning(
                f"[STRIP_ERROR] Failed to strip repo data: {error}, passing through"
            )
            self.passed_count += 1

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


addons = [CursorDeepTelemetryFilter()]
