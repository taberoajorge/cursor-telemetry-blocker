import asyncio
import time
from pathlib import Path

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widgets import Footer, Header, RichLog, Static, TabbedContent, TabPane

from cursor_telemetry_blocker.events import EVENTS_FILE, EventReader, ProxyEvent

EVENT_STYLES = {
    "blocked": ("red", "BLOCKED"),
    "passed": ("green", "PASSED"),
    "stripped": ("yellow", "STRIPPED"),
    "observed": ("cyan", "OBSERVED"),
}


class StatsBar(Static):
    blocked_count = reactive(0)
    passed_count = reactive(0)
    stripped_count = reactive(0)
    total_count = reactive(0)

    def render(self) -> Text:
        parts = Text()
        parts.append("  Blocked ", style="bold")
        parts.append(str(self.blocked_count), style="bold red")
        parts.append("    Passed ", style="bold")
        parts.append(str(self.passed_count), style="bold green")
        parts.append("    Stripped ", style="bold")
        parts.append(str(self.stripped_count), style="bold yellow")
        parts.append("    Total ", style="bold")
        parts.append(str(self.total_count), style="bold cyan")
        return parts


class TelemetryDashboard(App):
    CSS_PATH = "dashboard.tcss"
    TITLE = "Cursor Telemetry Blocker"

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("p", "toggle_pause", "Pause"),
        Binding("c", "clear_logs", "Clear"),
        Binding("t", "toggle_dark", "Theme"),
        Binding("1", "tab('all')", "All", show=False),
        Binding("2", "tab('blocked')", "Blocked", show=False),
        Binding("3", "tab('passed')", "Passed", show=False),
        Binding("4", "tab('stripped')", "Stripped", show=False),
    ]

    paused = reactive(False)
    start_time: float = 0.0

    def compose(self) -> ComposeResult:
        yield Header()
        yield StatsBar(id="stats_bar")
        with TabbedContent(initial="all"):
            with TabPane("All", id="all"):
                yield RichLog(id="log_all", highlight=True, markup=True, max_lines=2000)
            with TabPane("Blocked", id="blocked"):
                yield RichLog(
                    id="log_blocked", highlight=True, markup=True, max_lines=2000
                )
            with TabPane("Passed", id="passed"):
                yield RichLog(
                    id="log_passed", highlight=True, markup=True, max_lines=2000
                )
            with TabPane("Stripped", id="stripped"):
                yield RichLog(
                    id="log_stripped", highlight=True, markup=True, max_lines=2000
                )
        yield Footer()

    def on_mount(self) -> None:
        self.start_time = time.time()
        self.reader = EventReader(EVENTS_FILE)
        self._load_existing_events()
        self.run_worker(self._tail_events(), exclusive=True)
        self.set_interval(1.0, self._update_title)

    def _load_existing_events(self) -> None:
        existing = self.reader.read_existing()
        for event in existing:
            self._process_event(event)

    async def _tail_events(self) -> None:
        async def on_event(event: ProxyEvent) -> None:
            if not self.paused:
                self.call_from_thread(self._process_event, event)

        try:
            await self.reader.tail(on_event)
        except asyncio.CancelledError:
            pass

    def _process_event(self, event: ProxyEvent) -> None:
        stats = self.query_one(StatsBar)
        stats.total_count += 1

        if event.event_type == "blocked":
            stats.blocked_count += 1
        elif event.event_type == "stripped":
            stats.stripped_count += 1
            stats.passed_count += 1
        elif event.event_type in ("passed", "observed"):
            stats.passed_count += 1

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
            target_log = self.query_one(target_selector, RichLog)
            target_log.write(formatted)

    def _format_event(self, event: ProxyEvent) -> Text:
        color, label = EVENT_STYLES.get(event.event_type, ("white", "UNKNOWN"))
        ts_str = time.strftime("%H:%M:%S", time.localtime(event.timestamp))

        line = Text()
        line.append(f" {ts_str} ", style="dim")
        line.append(f" {label:8s} ", style=f"bold {color}")

        category_display = event.category.upper()
        if category_display and category_display != label:
            line.append(f" {category_display:12s}", style="dim italic")

        truncated_path = event.path
        if len(truncated_path) > 50:
            truncated_path = truncated_path[:47] + "..."

        line.append(f" {event.method:4s} ", style="bold")
        line.append(event.host, style="underline")
        line.append(truncated_path, style="dim")

        if event.size > 0:
            size_display = self._format_bytes(event.size)
            line.append(f"  ({size_display})", style="dim")

        if event.stripped_bytes > 0:
            stripped_display = self._format_bytes(event.stripped_bytes)
            line.append(f"  stripped {stripped_display}", style="yellow italic")

        return line

    @staticmethod
    def _format_bytes(num_bytes: int) -> str:
        if num_bytes < 1024:
            return f"{num_bytes}B"
        elif num_bytes < 1024 * 1024:
            return f"{num_bytes / 1024:.1f}KB"
        return f"{num_bytes / (1024 * 1024):.1f}MB"

    def _update_title(self) -> None:
        elapsed = int(time.time() - self.start_time)
        hours = elapsed // 3600
        minutes = (elapsed % 3600) // 60
        seconds = elapsed % 60
        uptime = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

        stats = self.query_one(StatsBar)
        status = "PAUSED" if self.paused else "LIVE"
        self.sub_title = f"{status}  {uptime}  |  {stats.total_count} events"

    def action_toggle_pause(self) -> None:
        self.paused = not self.paused
        state = "paused" if self.paused else "resumed"
        self.notify(f"Event stream {state}", timeout=2)

    def action_clear_logs(self) -> None:
        for log_id in ("#log_all", "#log_blocked", "#log_passed", "#log_stripped"):
            self.query_one(log_id, RichLog).clear()
        self.notify("Logs cleared", timeout=2)

    def action_tab(self, tab_id: str) -> None:
        self.query_one(TabbedContent).active = tab_id

    def action_toggle_dark(self) -> None:
        self.theme = "textual-dark" if self.theme == "textual-light" else "textual-light"


def main():
    app = TelemetryDashboard()
    app.run()


if __name__ == "__main__":
    main()
