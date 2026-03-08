import sys
from pathlib import Path

PROJECT_SRC = str(Path(__file__).resolve().parent.parent / "src")
if PROJECT_SRC not in sys.path:
    sys.path.insert(0, PROJECT_SRC)

from cursor_telemetry_blocker.deep_filter import CursorDeepTelemetryFilter

addons = [CursorDeepTelemetryFilter()]
