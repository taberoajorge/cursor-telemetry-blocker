import json
import logging
from datetime import datetime, timezone

from mitmproxy import http, ctx

TELEMETRY_DOMAINS = {
    "metrics.cursor.sh",
    "mobile.events.data.microsoft.com",
    "default.exp-tas.com",
    "cursor-user-debugging-data.s3.us-east-1.amazonaws.com",
}

TELEMETRY_GRPC_PATHS = {
    "ClientLoggerService",
}

CURSOR_DOMAINS = {
    "api2.cursor.sh",
    "api3.cursor.sh",
    "marketplace.cursorapi.com",
    "authenticate.cursor.sh",
    "authenticator.cursor.sh",
}

LOG_FILE = "cursor_traffic.log"


class CursorObserver:
    def __init__(self):
        self.file_logger = logging.getLogger("cursor_observer")
        self.file_logger.setLevel(logging.DEBUG)

        file_handler = logging.FileHandler(LOG_FILE, mode="a")
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s | %(message)s", datefmt="%H:%M:%S")
        )
        self.file_logger.addHandler(file_handler)

        self.file_logger.info("Cursor Observer started")

    def request(self, flow: http.HTTPFlow) -> None:
        host = flow.request.pretty_host
        path = flow.request.path
        method = flow.request.method
        content_type = flow.request.headers.get("content-type", "")

        is_grpc = "grpc" in content_type or "application/grpc" in content_type
        is_telemetry_domain = host in TELEMETRY_DOMAINS
        is_telemetry_path = any(
            marker in path for marker in TELEMETRY_GRPC_PATHS
        )

        classification = self._classify(host, path, is_telemetry_domain, is_telemetry_path)

        request_size = len(flow.request.content) if flow.request.content else 0

        log_entry = {
            "host": host,
            "path": path,
            "method": method,
            "content_type": content_type,
            "grpc": is_grpc,
            "classification": classification,
            "request_bytes": request_size,
        }

        tag = f"[{classification}]"
        self.file_logger.info(f"{tag:20s} {method:6s} {host}{path} ({request_size}B)")

        if is_grpc:
            self.file_logger.debug(f"  gRPC headers: {dict(flow.request.headers)}")

    def response(self, flow: http.HTTPFlow) -> None:
        if flow.response is None:
            return

        host = flow.request.pretty_host
        path = flow.request.path
        status = flow.response.status_code
        response_size = len(flow.response.content) if flow.response.content else 0

        self.file_logger.info(
            f"  <- {status} {host}{path} ({response_size}B)"
        )

    def _classify(self, host, path, is_telemetry_domain, is_telemetry_path):
        if is_telemetry_domain:
            return "TELEMETRY"

        if is_telemetry_path:
            return "TELEMETRY_RPC"

        if "sentry" in path.lower() or "envelope" in path.lower():
            return "SENTRY"

        if host in CURSOR_DOMAINS:
            if "ChatService" in path:
                return "AI_CHAT"
            if "AiService" in path:
                return "AI_SERVICE"
            if "auth" in path.lower() or "stripe" in path.lower():
                return "AUTH"
            if "repository" in path.lower():
                return "REPO_TRACKING"
            if "marketplace" in host:
                return "MARKETPLACE"
            return "CURSOR_OTHER"

        return "EXTERNAL"


addons = [CursorObserver()]
