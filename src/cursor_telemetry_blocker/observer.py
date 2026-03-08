from mitmproxy import http

from cursor_telemetry_blocker.config import EVENTS_FILE, LOG_FILES, classify_traffic, create_logger
from cursor_telemetry_blocker.events import EventWriter, ProxyEvent


class CursorObserver:
    def __init__(self):
        self.file_logger = create_logger("cursor_observer", LOG_FILES["observe"])
        self.events = EventWriter(EVENTS_FILE)
        self.file_logger.info("Cursor Observer started")

    def request(self, flow: http.HTTPFlow) -> None:
        host = flow.request.pretty_host
        path = flow.request.path
        method = flow.request.method

        classification = classify_traffic(host, path)
        request_size = len(flow.request.content) if flow.request.content else 0

        tag = f"[{classification}]"
        self.file_logger.info(f"{tag:20s} {method:6s} {host}{path} ({request_size}B)")

        content_type = flow.request.headers.get("content-type", "")
        is_grpc = "grpc" in content_type or "application/grpc" in content_type
        if is_grpc:
            self.file_logger.debug(f"  gRPC headers: {dict(flow.request.headers)}")

        self.events.emit(ProxyEvent(
            event_type="observed",
            category=classification.lower(),
            host=host,
            path=path,
            method=method,
            size=request_size,
            detail=classification,
        ))

    def response(self, flow: http.HTTPFlow) -> None:
        if flow.response is None:
            return

        host = flow.request.pretty_host
        path = flow.request.path
        status = flow.response.status_code
        response_size = len(flow.response.content) if flow.response.content else 0

        self.file_logger.info(f"  <- {status} {host}{path} ({response_size}B)")

    def done(self):
        self.events.close()


addons = [CursorObserver()]
