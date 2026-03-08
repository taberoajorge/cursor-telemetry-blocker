import logging
from mitmproxy import http, ctx

BLOCKED_DOMAINS = {
    "metrics.cursor.sh",
    "mobile.events.data.microsoft.com",
    "default.exp-tas.com",
    "cursor-user-debugging-data.s3.us-east-1.amazonaws.com",
}

BLOCKED_GRPC_PATHS = [
    "ClientLoggerService",
    "AnalyticsService/Batch",
    "AnalyticsService/BootstrapStatsig",
    "AiService/ReportClientNumericMetrics",
    "AiService/ReportCommitAiAnalytics",
    "AiService/UpdateVscodeProfile",
    "InAppAdService",
    "/tev1/",
    "/rgstr",
]

REPO_TRACKING_MARKERS = [
    "/repository/",
    "/repository.v1.",
    "RepositoryService",
    "DashboardService/GetTeamRepos",
]

AI_PASSTHROUGH_MARKERS = [
    "ChatService",
    "AiService/GetDefaultModelNudgeData",
    "AiService/AvailableDocs",
    "AiService/ServerTime",
    "AiService/StreamChat",
    "AiService/GetChat",
]

AUTH_PASSTHROUGH_MARKERS = [
    "/auth/",
    "stripe",
    "authenticate.cursor.sh",
    "authenticator.cursor.sh",
]

LOG_FILE = "cursor_blocker.log"


class CursorTelemetryFilter:
    def __init__(self):
        self.logger = logging.getLogger("cursor_blocker")
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
        self.passed_count = 0
        self.logger.info("Cursor Telemetry Filter started")

    def request(self, flow: http.HTTPFlow) -> None:
        host = flow.request.pretty_host
        path = flow.request.path
        full_url = f"{host}{path}"

        if self._should_block_domain(host):
            self._block_request(flow, f"blocked domain: {host}")
            return

        if self._should_block_grpc_path(path):
            self._block_request(flow, f"blocked gRPC path: {path}")
            return

        if self._is_repo_tracking(path):
            self._block_request(flow, f"blocked repo tracking: {path}")
            return

        if self._is_sentry_envelope(host, path):
            self._block_request(flow, f"blocked sentry envelope: {full_url}")
            return

        self.passed_count += 1
        classification = self._classify_passthrough(host, path)
        self.logger.info(
            f"[PASS:{classification}] {flow.request.method} {full_url}"
        )

    def _should_block_domain(self, host: str) -> bool:
        return host in BLOCKED_DOMAINS

    def _should_block_grpc_path(self, path: str) -> bool:
        return any(marker in path for marker in BLOCKED_GRPC_PATHS)

    def _is_repo_tracking(self, path: str) -> bool:
        return any(marker in path for marker in REPO_TRACKING_MARKERS)

    def _is_sentry_envelope(self, host: str, path: str) -> bool:
        return "envelope" in path and "cursor" in host

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

        self.logger.info(
            f"[BLOCKED #{self.blocked_count}] {reason}"
        )

    def _classify_passthrough(self, host: str, path: str) -> str:
        if any(marker in path for marker in AI_PASSTHROUGH_MARKERS):
            return "AI"

        if any(marker in path or marker in host for marker in AUTH_PASSTHROUGH_MARKERS):
            return "AUTH"

        if "marketplace" in host:
            return "MARKETPLACE"

        if "cursor" in host:
            return "CURSOR"

        return "OTHER"


addons = [CursorTelemetryFilter()]
