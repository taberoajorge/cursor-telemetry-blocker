import io
import logging
import struct
from mitmproxy import http

BLOCKED_DOMAINS = {
    "metrics.cursor.sh",
    "mobile.events.data.microsoft.com",
    "default.exp-tas.com",
    "cursor-user-debugging-data.s3.us-east-1.amazonaws.com",
    "dc.services.visualstudio.com",
    "o55978.ingest.us.sentry.io",
    "snowplowprd.trx.gitlab.net",
    "new-sentry.gitlab.net",
    "otel.gitkraken.com",
    "xp.atlassian.com",
    "as.atlassian.com",
    "api.agnost.ai",
}

BLOCKED_GRPC_PATHS = [
    "ClientLoggerService",
    "AnalyticsService/Batch",
    "AnalyticsService/BootstrapStatsig",
    "AiService/ReportClientNumericMetrics",
    "AiService/ReportCommitAiAnalytics",
    "AiService/ReportAiCodeChangeMetrics",
    "AiService/UpdateVscodeProfile",
    "InAppAdService",
    "CppService/RecordCppFate",
    "/tev1/",
    "/rgstr",
]

REPO_TRACKING_MARKERS = [
    "/repository/",
    "/repository.v1.",
    "RepositoryService",
    "DashboardService/GetTeamRepos",
]

GRPC_PATHS_TO_STRIP_REPO = [
    "ChatService",
    "AiService",
    "StreamChat",
    "GetChat",
    "GetPromptDryRun",
]

WIRE_TYPE_VARINT = 0
WIRE_TYPE_64BIT = 1
WIRE_TYPE_LENGTH_DELIMITED = 2
WIRE_TYPE_32BIT = 5

LOG_FILE = "cursor_blocker_deep.log"


def decode_varint(data: bytes, offset: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while offset < len(data):
        byte_val = data[offset]
        result |= (byte_val & 0x7F) << shift
        offset += 1
        if (byte_val & 0x80) == 0:
            return result, offset
        shift += 7
    raise ValueError("Truncated varint")


def encode_varint(value: int) -> bytes:
    parts = []
    while value > 0x7F:
        parts.append((value & 0x7F) | 0x80)
        value >>= 7
    parts.append(value & 0x7F)
    return bytes(parts)


def strip_repo_info_from_protobuf(data: bytes) -> bytes:
    output = io.BytesIO()
    offset = 0

    while offset < len(data):
        try:
            tag, new_offset = decode_varint(data, offset)
        except ValueError:
            output.write(data[offset:])
            break

        field_number = tag >> 3
        wire_type = tag & 0x07

        if wire_type == WIRE_TYPE_VARINT:
            _, end_offset = decode_varint(data, new_offset)
            output.write(data[offset:end_offset])
            offset = end_offset

        elif wire_type == WIRE_TYPE_64BIT:
            end_offset = new_offset + 8
            output.write(data[offset:end_offset])
            offset = end_offset

        elif wire_type == WIRE_TYPE_32BIT:
            end_offset = new_offset + 4
            output.write(data[offset:end_offset])
            offset = end_offset

        elif wire_type == WIRE_TYPE_LENGTH_DELIMITED:
            try:
                length, content_offset = decode_varint(data, new_offset)
            except ValueError:
                output.write(data[offset:])
                break

            field_end = content_offset + length

            if field_number == 3 and length > 10:
                cleaned_submessage = redact_repository_info(
                    data[content_offset:field_end]
                )
                output.write(encode_varint(tag))
                output.write(encode_varint(len(cleaned_submessage)))
                output.write(cleaned_submessage)
            else:
                output.write(data[offset:field_end])

            offset = field_end
        else:
            output.write(data[offset:])
            break

    return output.getvalue()


def redact_repository_info(data: bytes) -> bytes:
    output = io.BytesIO()
    offset = 0

    while offset < len(data):
        try:
            tag, new_offset = decode_varint(data, offset)
        except ValueError:
            output.write(data[offset:])
            break

        field_number = tag >> 3
        wire_type = tag & 0x07

        if wire_type == WIRE_TYPE_LENGTH_DELIMITED:
            try:
                length, content_offset = decode_varint(data, new_offset)
            except ValueError:
                output.write(data[offset:])
                break

            field_end = content_offset + length

            if field_number in (2, 3, 4, 5, 11):
                offset = field_end
                continue

            output.write(data[offset:field_end])
            offset = field_end

        elif wire_type == WIRE_TYPE_VARINT:
            _, end_offset = decode_varint(data, new_offset)

            if field_number == 6:
                output.write(encode_varint((6 << 3) | WIRE_TYPE_VARINT))
                output.write(encode_varint(0))
            else:
                output.write(data[offset:end_offset])

            offset = end_offset

        elif wire_type == WIRE_TYPE_64BIT:
            end_offset = new_offset + 8
            output.write(data[offset:end_offset])
            offset = end_offset

        elif wire_type == WIRE_TYPE_32BIT:
            end_offset = new_offset + 4
            output.write(data[offset:end_offset])
            offset = end_offset

        else:
            output.write(data[offset:])
            break

    return output.getvalue()


def decode_grpc_frames(body: bytes) -> list[tuple[bool, bytes]]:
    frames = []
    offset = 0
    while offset + 5 <= len(body):
        compressed = body[offset]
        frame_length = struct.unpack(">I", body[offset + 1 : offset + 5])[0]
        frame_data = body[offset + 5 : offset + 5 + frame_length]
        frames.append((bool(compressed), frame_data))
        offset += 5 + frame_length
    return frames


def encode_grpc_frames(frames: list[tuple[bool, bytes]]) -> bytes:
    output = io.BytesIO()
    for compressed, frame_data in frames:
        output.write(bytes([1 if compressed else 0]))
        output.write(struct.pack(">I", len(frame_data)))
        output.write(frame_data)
    return output.getvalue()


class CursorDeepTelemetryFilter:
    def __init__(self):
        self.logger = logging.getLogger("cursor_deep_blocker")
        self.logger.setLevel(logging.DEBUG)

        file_handler = logging.FileHandler(LOG_FILE, mode="a")
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s | %(message)s", datefmt="%H:%M:%S")
        )
        self.logger.addHandler(file_handler)

        console_handler = logging.StreamHandler()
        console_handler.setFormatter(
            logging.Formatter("%(asctime)s | %(message)s", datefmt="%H:%M:%S")
        )
        self.logger.addHandler(console_handler)

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

        if is_grpc and self._should_strip_repo(path) and flow.request.content:
            self._strip_repo_from_grpc(flow)
            return

        self.passed_count += 1
        self.logger.info(f"[PASS] {flow.request.method} {host}{path}")

    def _should_strip_repo(self, path: str) -> bool:
        return any(marker in path for marker in GRPC_PATHS_TO_STRIP_REPO)

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
                f"[{tag}] {flow.request.method} {flow.request.pretty_host}{flow.request.path}"
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
