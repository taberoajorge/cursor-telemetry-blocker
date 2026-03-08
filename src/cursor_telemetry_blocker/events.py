import asyncio
import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

EVENTS_FILE = "cursor_events.jsonl"


@dataclass
class ProxyEvent:
    event_type: str
    category: str
    host: str
    path: str
    method: str
    size: int = 0
    detail: str = ""
    timestamp: float = field(default_factory=time.time)
    stripped_bytes: int = 0


class EventWriter:
    def __init__(self, events_path: str = EVENTS_FILE):
        self.events_path = Path(events_path)
        self._file = open(self.events_path, "a", buffering=1)

    def emit(self, event: ProxyEvent) -> None:
        line = json.dumps(asdict(event), separators=(",", ":"))
        self._file.write(line + "\n")

    def close(self) -> None:
        self._file.close()


class EventReader:
    def __init__(self, events_path: str = EVENTS_FILE):
        self.events_path = Path(events_path)

    async def tail(self, callback, poll_interval: float = 0.15):
        if not self.events_path.exists():
            self.events_path.touch()

        with open(self.events_path, "r") as handle:
            handle.seek(0, os.SEEK_END)

            while True:
                line = handle.readline()
                if line:
                    line = line.strip()
                    if line:
                        try:
                            data = json.loads(line)
                            event = ProxyEvent(**data)
                            await callback(event)
                        except (json.JSONDecodeError, TypeError):
                            pass
                else:
                    await asyncio.sleep(poll_interval)

    def read_existing(self) -> list[ProxyEvent]:
        events = []
        if not self.events_path.exists():
            return events

        with open(self.events_path, "r") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    events.append(ProxyEvent(**data))
                except (json.JSONDecodeError, TypeError):
                    pass
        return events
