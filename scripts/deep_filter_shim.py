"""Shim for loading the deep filter addon with Homebrew's standalone mitmdump.

Homebrew's mitmdump bundles its own Python environment that cannot import
packages from this project. This shim adds the project's ``src/`` directory
to ``sys.path`` so that ``cursor_telemetry_blocker`` becomes importable,
then exposes the addon via the ``addons`` list that mitmproxy expects.

Used by the LaunchAgent service when running in transparent mode
(``--mode local:Cursor``), where ``uv run`` is not available.
"""

import sys
from pathlib import Path

PROJECT_SRC = str(Path(__file__).resolve().parent.parent / "src")
if PROJECT_SRC not in sys.path:
    sys.path.insert(0, PROJECT_SRC)

from cursor_telemetry_blocker.deep_filter import CursorDeepTelemetryFilter  # noqa: E402

addons = [CursorDeepTelemetryFilter()]
