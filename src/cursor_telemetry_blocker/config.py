import logging
from pathlib import Path

BLOCKED_DOMAINS = {
    "metrics.cursor.sh",
    "mobile.events.data.microsoft.com",
    "default.exp-tas.com",
    "cursor-user-debugging-data.s3.us-east-1.amazonaws.com",
    "repo42.cursor.sh",
    "api.turbopuffer.com",
    "statsig.cursor.sh",
    "dc.services.visualstudio.com",
    "snowplowprd.trx.gitlab.net",
    "new-sentry.gitlab.net",
    "otel.gitkraken.com",
    "xp.atlassian.com",
    "as.atlassian.com",
    "api.agnost.ai",
}

BLOCKED_DOMAIN_PATTERNS = [
    ".turbopuffer.com",
    ".ingest.sentry.io",
    ".ingest.us.sentry.io",
]

BLOCKED_GRPC_PATHS = [
    "ClientLoggerService",
    "AnalyticsService/Batch",
    "AnalyticsService/BootstrapStatsig",
    "AnalyticsService/Track",
    "AnalyticsService/SubmitLogs",
    "MetricsService/ReportGauge",
    "MetricsService/ReportDistribution",
    "MetricsService/ReportIncrement",
    "AiService/ReportClientNumericMetrics",
    "AiService/ReportCommitAiAnalytics",
    "AiService/ReportAiCodeChangeMetrics",
    "AiService/UpdateVscodeProfile",
    "AiService/ReportUsageEvent",
    "AiService/RecordTelemetry",
    "InAppAdService",
    "IndexerService",
    "CppService/RecordCppFate",
    "/tev1/",
    "/rgstr",
]

REPO_TRACKING_MARKERS = [
    "/repository/",
    "/repository.v1.",
    "RepositoryService",
    "DashboardService/GetTeamRepos",
    "DashboardService",
]

REPO_TRACKING_ALLOWLIST = [
    "DashboardService/GetTeamPrivacyModeForced",
    "DashboardService/GetUsageLimitStatusAndActiveGrants",
    "DashboardService/GetTeamAdminSettingsOrEmptyIfNotInTeam",
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

GRPC_PATHS_TO_STRIP_REPO = [
    "ChatService",
    "AiService",
    "StreamChat",
    "GetChat",
    "GetPromptDryRun",
]

CURSOR_DOMAINS = {
    "api2.cursor.sh",
    "api3.cursor.sh",
    "marketplace.cursorapi.com",
    "authenticate.cursor.sh",
    "authenticator.cursor.sh",
}

LOG_FILES = {
    "block": "cursor_blocker.log",
    "deep": "cursor_blocker_deep.log",
    "observe": "cursor_traffic.log",
}

EVENTS_FILE = "cursor_events.jsonl"


def create_logger(name: str, log_file: str) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    if logger.handlers:
        return logger

    formatter = logging.Formatter("%(asctime)s | %(message)s", datefmt="%H:%M:%S")

    file_handler = logging.FileHandler(log_file, mode="a")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger


def is_blocked_domain(host: str) -> bool:
    if host in BLOCKED_DOMAINS:
        return True
    return any(host.endswith(pattern) for pattern in BLOCKED_DOMAIN_PATTERNS)


def is_blocked_grpc_path(path: str) -> bool:
    return any(marker in path for marker in BLOCKED_GRPC_PATHS)


def is_repo_tracking(path: str) -> bool:
    if any(marker in path for marker in REPO_TRACKING_ALLOWLIST):
        return False
    return any(marker in path for marker in REPO_TRACKING_MARKERS)


def is_sentry_envelope(host: str, path: str) -> bool:
    if "sentry.io" in host:
        return True
    return "envelope" in path and "cursor" in host


def should_strip_repo(path: str) -> bool:
    return any(marker in path for marker in GRPC_PATHS_TO_STRIP_REPO)


def classify_passthrough(host: str, path: str) -> str:
    if any(marker in path for marker in AI_PASSTHROUGH_MARKERS):
        return "AI"

    if any(marker in path or marker in host for marker in AUTH_PASSTHROUGH_MARKERS):
        return "AUTH"

    if "marketplace" in host:
        return "MARKETPLACE"

    if "cursor" in host:
        return "CURSOR"

    return "OTHER"


def classify_traffic(host: str, path: str) -> str:
    if host in BLOCKED_DOMAINS:
        return "TELEMETRY"

    if any(marker in path for marker in BLOCKED_GRPC_PATHS):
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
