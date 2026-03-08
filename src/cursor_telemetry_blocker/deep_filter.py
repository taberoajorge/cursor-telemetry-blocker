from mitmproxy import http

from cursor_telemetry_blocker.config import (
    BLOCKED_DOMAINS,
    BLOCKED_GRPC_PATHS,
    LOG_FILES,
    REPO_TRACKING_MARKERS,
    create_logger,
    should_strip_repo,
)
from cursor_telemetry_blocker.protobuf import (
    decode_grpc_frames,
    encode_grpc_frames,
    strip_repo_info_from_protobuf,
)


class CursorDeepTelemetryFilter:
    def __init__(self):
        self.logger = create_logger("cursor_deep_blocker", LOG_FILES["deep"])
        self.blocked_count = 0
        self.stripped_count = 0
        self.passed_count = 0
        self.logger.info("Cursor Deep Telemetry Filter started (with protobuf stripping)")

    def request(self, flow: http.HTTPFlow) -> None:
        host = flow.request.pretty_host
        path = flow.request.path
        content_type = flow.request.headers.get("content-type", "")
        is_grpc = "grpc" in content_type

        if host in BLOCKED_DOMAINS:
            self._block_request(flow, f"blocked domain: {host}")
            return

        if any(marker in path for marker in BLOCKED_GRPC_PATHS):
            self._block_request(flow, f"blocked gRPC path: {path}")
            return

        if any(marker in path for marker in REPO_TRACKING_MARKERS):
            self._block_request(flow, f"blocked repo tracking: {path}")
            return

        if "envelope" in path and "cursor" in host:
            self._block_request(flow, f"blocked sentry: {host}{path}")
            return

        if is_grpc and should_strip_repo(path) and flow.request.content:
            self._strip_repo_from_grpc(flow)
            return

        self.passed_count += 1
        self.logger.info(f"[PASS] {flow.request.method} {host}{path}")

    def _strip_repo_from_grpc(self, flow: http.HTTPFlow) -> None:
        try:
            original_body = flow.request.content
            if not original_body or len(original_body) < 5:
                return

            frames = decode_grpc_frames(original_body)
            modified_frames = []
            any_modified = False

            for compressed, frame_data in frames:
                if compressed:
                    modified_frames.append((compressed, frame_data))
                    continue

                original_len = len(frame_data)
                stripped_data = strip_repo_info_from_protobuf(frame_data)
                modified_len = len(stripped_data)

                if modified_len != original_len:
                    any_modified = True
                    self.logger.info(
                        f"[STRIP] Removed {original_len - modified_len}B repo data "
                        f"from {flow.request.path}"
                    )

                modified_frames.append((False, stripped_data))

            if any_modified:
                flow.request.content = encode_grpc_frames(modified_frames)
                self.stripped_count += 1

            self.passed_count += 1
            tag = "STRIP+PASS" if any_modified else "PASS"
            self.logger.info(
                f"[{tag}] {flow.request.method} "
                f"{flow.request.pretty_host}{flow.request.path}"
            )

        except Exception as error:
            self.logger.warning(
                f"[STRIP_ERROR] Failed to strip repo data: {error}, passing through"
            )
            self.passed_count += 1

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


addons = [CursorDeepTelemetryFilter()]
