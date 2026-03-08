import asyncio
import json
import os
import random
import sys
import time
from pathlib import Path

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Footer, Header, RichLog, Static, TabbedContent, TabPane

from cursor_telemetry_blocker.events import EVENTS_FILE, EventReader, ProxyEvent

EVENT_COLORS = {
    "blocked": "red",
    "passed": "green",
    "stripped": "yellow",
    "observed": "cyan",
}

EVENT_LABELS = {
    "blocked": "BLOCKED ",
    "passed": "PASSED  ",
    "stripped": "STRIPPED",
    "observed": "OBSERVED",
}

DEMO_BLOCKED_HOSTS = [
    ("metrics.cursor.sh", "/v1/track"),
    ("mobile.events.data.microsoft.com", "/collect"),
    ("default.exp-tas.com", "/tas/v2/"),
    ("statsig.cursor.sh", "/v1/log_event"),
    ("repo42.cursor.sh", "/upload"),
    ("o428532.ingest.sentry.io", "/api/123/envelope/"),
    ("api.turbopuffer.com", "/v1/vectors"),
]

DEMO_PASSED_HOSTS = [
    ("api2.cursor.sh", "/aiserver.v1.AiService/StreamChat"),
    ("api2.cursor.sh", "/aiserver.v1.ChatService/GetChat"),
    ("api2.cursor.sh", "/aiserver.v1.AiService/ServerTime"),
    ("authenticate.cursor.sh", "/auth/session"),
    ("marketplace.cursorapi.com", "/api/extensions"),
]

DEMO_CATEGORIES = {
    "blocked": ["telemetry", "telemetry", "telemetry", "sentry", "repo", "telemetry"],
    "passed": ["ai", "ai", "ai", "auth", "marketplace"],
    "stripped": ["stripped"],
}


class StatsBar(Static):
    blocked_total = reactive(0)
    passed_total = reactive(0)
    stripped_total = reactive(0)
    events_total = reactive(0)

    def render(self) -> Text:
        line = Text()
        line.append("  BLOCKED ", style="bold")
        line.append(f" {self.blocked_total} ", style="bold reverse red")
        line.append("   PASSED ", style="bold")
        line.append(f" {self.passed_total} ", style="bold reverse green")
        line.append("   STRIPPED ", style="bold")
        line.append(f" {self.stripped_total} ", style="bold reverse yellow")
        line.append("   TOTAL ", style="bold")
        line.append(f" {self.events_total} ", style="bold reverse cyan")
        return line


class NewEvent(Message):
    def __init__(self, event: ProxyEvent) -> None:
        self.event = event
        super().__init__()


class TelemetryDashboard(App):
    CSS_PATH = "dashboard.tcss"
    TITLE = "Cursor Telemetry Blocker"

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("p", "toggle_pause", "Pause/Resume"),
        Binding("c", "clear_logs", "Clear"),
        Binding("t", "toggle_dark", "Theme"),
        Binding("1", "tab('all')", "All", show=False),
        Binding("2", "tab('blocked')", "Blocked", show=False),
        Binding("3", "tab('passed')", "Passed", show=False),
        Binding("4", "tab('stripped')", "Stripped", show=False),
    ]

    paused = reactive(False)
    demo_mode: bool = False

    def __init__(self, demo: bool = False):
        super().__init__()
        self.demo_mode = demo
        self.start_time = time.time()

    def compose(self) -> ComposeResult:
        yield Header()
        yield StatsBar(id="stats_bar")
        with TabbedContent(initial="all"):
            with TabPane("All", id="all"):
                yield RichLog(
                    id="log_all", highlight=True, markup=True, max_lines=5000, wrap=True
                )
            with TabPane("Blocked", id="blocked"):
                yield RichLog(
                    id="log_blocked", highlight=True, markup=True, max_lines=5000, wrap=True
                )
            with TabPane("Passed", id="passed"):
                yield RichLog(
                    id="log_passed", highlight=True, markup=True, max_lines=5000, wrap=True
                )
            with TabPane("Stripped", id="stripped"):
                yield RichLog(
                    id="log_stripped", highlight=True, markup=True, max_lines=5000, wrap=True
                )
        yield Footer()

    def on_mount(self) -> None:
        self.set_interval(1.0, self._update_subtitle)

        if self.demo_mode:
            self._write_welcome("Running in DEMO mode with simulated events")
            self.set_interval(0.4, self._generate_demo_event)
        else:
            events_path = Path(EVENTS_FILE)
            if events_path.exists():
                existing = EventReader(EVENTS_FILE).read_existing()
                for event in existing:
                    self._process_event(event)
                self._write_welcome(f"Loaded {len(existing)} existing events")
            else:
                self._write_welcome("Waiting for events... Start the proxy with: make run")
            self._poll_position = self._get_file_end_position()
            self.set_interval(0.2, self._poll_events_file)

    def _write_welcome(self, message: str) -> None:
        welcome = Text()
        welcome.append(f"  {message}", style="bold italic dim")
        self.query_one("#log_all", RichLog).write(welcome)

    def _get_file_end_position(self) -> int:
        events_path = Path(EVENTS_FILE)
        if events_path.exists():
            return events_path.stat().st_size
        return 0

    def _poll_events_file(self) -> None:
        if self.paused:
            return

        events_path = Path(EVENTS_FILE)
        if not events_path.exists():
            return

        current_size = events_path.stat().st_size
        if current_size <= self._poll_position:
            return

        try:
            with open(events_path, "r") as handle:
                handle.seek(self._poll_position)
                new_data = handle.read()
                self._poll_position = handle.tell()

            for raw_line in new_data.splitlines():
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    data = json.loads(raw_line)
                    event = ProxyEvent(**data)
                    self._process_event(event)
                except (json.JSONDecodeError, TypeError, KeyError):
                    pass
        except OSError:
            pass

    def _generate_demo_event(self) -> None:
        roll = random.random()
        if roll < 0.55:
            event_type = "blocked"
            host, path = random.choice(DEMO_BLOCKED_HOSTS)
            category = random.choice(DEMO_CATEGORIES["blocked"])
        elif roll < 0.85:
            event_type = "passed"
            host, path = random.choice(DEMO_PASSED_HOSTS)
            category = random.choice(DEMO_CATEGORIES["passed"])
        else:
            event_type = "stripped"
            host, path = random.choice(DEMO_PASSED_HOSTS[:2])
            category = "stripped"

        event = ProxyEvent(
            event_type=event_type,
            category=category,
            host=host,
            path=path,
            method=random.choice(["POST", "GET"]),
            size=random.randint(64, 8192),
            detail=f"demo {event_type}",
            timestamp=time.time(),
            stripped_bytes=random.randint(32, 512) if event_type == "stripped" else 0,
        )
        self._process_event(event)

    def _process_event(self, event: ProxyEvent) -> None:
        stats = self.query_one(StatsBar)
        stats.events_total += 1

        if event.event_type == "blocked":
            stats.blocked_total += 1
        elif event.event_type == "stripped":
            stats.stripped_total += 1
            stats.passed_total += 1
        elif event.event_type in ("passed", "observed"):
            stats.passed_total += 1

        formatted = self._format_event(event)

        log_all = self.query_one("#log_all", RichLog)
        log_all.write(formatted)

        target_map = {
            "blocked": "#log_blocked",
            "stripped": "#log_stripped",
            "passed": "#log_passed",
            "observed": "#log_passed",
        }
        target_selector = target_map.get(event.event_type)
        if target_selector:
            self.query_one(target_selector, RichLog).write(formatted)

    def _format_event(self, event: ProxyEvent) -> Text:
        color = EVENT_COLORS.get(event.event_type, "white")
        label = EVENT_LABELS.get(event.event_type, "UNKNOWN ")
        ts_str = time.strftime("%H:%M:%S", time.localtime(event.timestamp))

        line = Text()
        line.append(f" {ts_str} ", style="bold dim")
        line.append(f" {label} ", style=f"reverse bold {color}")
        line.append(" ", style="")

        category_display = event.category.upper()
        if category_display and category_display != label.strip():
            line.append(f"{category_display:>10s} ", style="italic")

        line.append(f"{event.method:>4s} ", style="bold")
        line.append(event.host, style=f"underline {color}")

        display_path = event.path
        if len(display_path) > 45:
            display_path = display_path[:42] + "..."
        line.append(display_path, style="dim")

        if event.size > 0:
            line.append(f"  {self._fmt_bytes(event.size)}", style="dim italic")

        if event.stripped_bytes > 0:
            line.append(f"  stripped {self._fmt_bytes(event.stripped_bytes)}", style="bold yellow")

        return line

    @staticmethod
    def _fmt_bytes(num_bytes: int) -> str:
        if num_bytes < 1024:
            return f"{num_bytes}B"
        if num_bytes < 1024 * 1024:
            return f"{num_bytes / 1024:.1f}KB"
        return f"{num_bytes / (1024 * 1024):.1f}MB"

    def _update_subtitle(self) -> None:
        elapsed = int(time.time() - self.start_time)
        hours = elapsed // 3600
        minutes = (elapsed % 3600) // 60
        seconds = elapsed % 60
        uptime = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

        stats = self.query_one(StatsBar)
        badge = "DEMO" if self.demo_mode else ("PAUSED" if self.paused else "LIVE")
        self.sub_title = f"[{badge}]  {uptime}  |  {stats.events_total} events"

    def action_toggle_pause(self) -> None:
        self.paused = not self.paused
        state = "paused" if self.paused else "resumed"
        self.notify(f"Stream {state}", timeout=2)

    def action_clear_logs(self) -> None:
        for selector in ("#log_all", "#log_blocked", "#log_passed", "#log_stripped"):
            self.query_one(selector, RichLog).clear()
        stats = self.query_one(StatsBar)
        stats.blocked_total = 0
        stats.passed_total = 0
        stats.stripped_total = 0
        stats.events_total = 0
        self.notify("Cleared", timeout=2)

    def action_tab(self, tab_id: str) -> None:
        self.query_one(TabbedContent).active = tab_id

    def action_toggle_dark(self) -> None:
        self.theme = "textual-dark" if self.theme == "textual-light" else "textual-light"


def main():
    demo = "--demo" in sys.argv
    app = TelemetryDashboard(demo=demo)
    app.run()


if __name__ == "__main__":
    main()
