"""Sniff ALL traffic addon for mitmproxy.

Captures and decodes every request passing through the proxy — not just
blocked ones.  Writes decoded payloads to a JSONL file for later analysis
and prints a live summary to stdout.

Usage:
    uv run mitmdump --listen-port 18080 -s scripts/sniff-all.py
"""

import json
import struct
import sys
import time
from pathlib import Path

PROJECT_SRC = str(Path(__file__).resolve().parent.parent / "src")
if PROJECT_SRC not in sys.path:
    sys.path.insert(0, PROJECT_SRC)

from mitmproxy import http  # noqa: E402
from cursor_telemetry_blocker.config import (  # noqa: E402
    is_blocked_domain,
    is_blocked_grpc_path,
    is_repo_tracking,
    is_sentry_envelope,
    should_strip_repo,
)

WIRE_TYPE_VARINT = 0
WIRE_TYPE_64BIT = 1
WIRE_TYPE_LENGTH_DELIMITED = 2
WIRE_TYPE_32BIT = 5

OUTPUT_FILE = Path(__file__).resolve().parent.parent / "sniff_capture.jsonl"


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
    return result, offset


def extract_fields(data: bytes, max_depth: int = 6) -> list[dict]:
    fields_found: list[dict] = []
    offset = 0
    if max_depth <= 0:
        return fields_found
    while offset < len(data):
        try:
            tag, new_offset = decode_varint(data, offset)
        except (IndexError, ValueError):
            break
        if tag == 0:
            break

        wire_type = tag & 0x07
        field_number = tag >> 3

        if field_number == 0 or field_number > 10000:
            break

        if wire_type == WIRE_TYPE_VARINT:
            value, offset = decode_varint(data, new_offset)
            fields_found.append({"f": field_number, "t": "int", "v": value})

        elif wire_type == WIRE_TYPE_LENGTH_DELIMITED:
            try:
                length, content_offset = decode_varint(data, new_offset)
            except (IndexError, ValueError):
                break
            if length > len(data) or length < 0:
                break
            field_end = content_offset + length
            if field_end > len(data):
                break
            raw = data[content_offset:field_end]
            try:
                text = raw.decode("utf-8", errors="strict")
                if text.isprintable() and len(text) > 0:
                    fields_found.append({"f": field_number, "t": "str", "v": text})
                else:
                    nested = extract_fields(raw, max_depth=max_depth - 1)
                    if nested:
                        fields_found.append({"f": field_number, "t": "msg", "c": nested})
                    else:
                        fields_found.append({"f": field_number, "t": "bytes", "len": len(raw)})
            except UnicodeDecodeError:
                nested = extract_fields(raw, max_depth=max_depth - 1)
                if nested:
                    fields_found.append({"f": field_number, "t": "msg", "c": nested})
                else:
                    if len(raw) <= 64:
                        fields_found.append({"f": field_number, "t": "hex", "v": raw.hex()})
                    else:
                        fields_found.append({"f": field_number, "t": "bytes", "len": len(raw)})
            offset = field_end

        elif wire_type == WIRE_TYPE_64BIT:
            if new_offset + 8 > len(data):
                break
            raw_bytes = data[new_offset:new_offset + 8]
            float_val = struct.unpack("<d", raw_bytes)[0]
            fields_found.append({"f": field_number, "t": "f64", "v": round(float_val, 4)})
            offset = new_offset + 8

        elif wire_type == WIRE_TYPE_32BIT:
            if new_offset + 4 > len(data):
                break
            raw_bytes = data[new_offset:new_offset + 4]
            float_val = struct.unpack("<f", raw_bytes)[0]
            fields_found.append({"f": field_number, "t": "f32", "v": round(float_val, 4)})
            offset = new_offset + 4

        else:
            break

    return fields_found


def decode_grpc_frames(body: bytes) -> list[tuple[bool, bytes]]:
    frames: list[tuple[bool, bytes]] = []
    offset = 0
    while offset + 5 <= len(body):
        compressed = body[offset]
        frame_length = struct.unpack(">I", body[offset + 1:offset + 5])[0]
        if offset + 5 + frame_length > len(body):
            break
        frame_data = body[offset + 5:offset + 5 + frame_length]
        frames.append((bool(compressed), frame_data))
        offset += 5 + frame_length
    return frames


def flatten_strings(fields: list[dict], prefix: str = "") -> list[str]:
    strings: list[str] = []
    for field in fields:
        path = f"{prefix}{field['f']}"
        if field["t"] == "str":
            strings.append(f"  {path}: \"{field['v']}\"")
        elif field["t"] == "int":
            strings.append(f"  {path}: {field['v']}")
        elif field["t"] in ("f64", "f32"):
            strings.append(f"  {path}: {field['v']}")
        elif field["t"] == "msg" and "c" in field:
            strings.extend(flatten_strings(field["c"], prefix=f"{path}."))
        elif field["t"] == "hex":
            strings.append(f"  {path}: 0x{field['v']}")
        elif field["t"] == "bytes":
            strings.append(f"  {path}: <{field['len']}B>")
    return strings


def fields_to_dict(fields: list[dict]) -> dict:
    """Convert protobuf fields to a JSON-serializable dict."""
    result = {}
    for field in fields:
        key = str(field["f"])
        if field["t"] == "str":
            result[key] = field["v"]
        elif field["t"] == "int":
            result[key] = field["v"]
        elif field["t"] in ("f64", "f32"):
            result[key] = field["v"]
        elif field["t"] == "msg" and "c" in field:
            result[key] = fields_to_dict(field["c"])
        elif field["t"] == "hex":
            result[key] = f"0x{field['v']}"
        elif field["t"] == "bytes":
            result[key] = f"<{field['len']}B>"
    return result


class SniffAll:
    def __init__(self):
        self.seq = 0
        self.out = open(OUTPUT_FILE, "a")
        print(f"=== SNIFF ALL MODE: capturing ALL traffic to {OUTPUT_FILE} ===", flush=True)
        print(f"=== Press Ctrl+C to stop ===\n", flush=True)

    def request(self, flow: http.HTTPFlow) -> None:
        host = flow.request.pretty_host
        path = flow.request.path
        content_type = flow.request.headers.get("content-type", "")
        is_proto = "grpc" in content_type or "proto" in content_type
        body = flow.request.content

        # Classify the request
        if is_blocked_domain(host):
            action = "BLOCK"
            reason = f"blocked domain: {host}"
        elif is_blocked_grpc_path(path):
            action = "BLOCK"
            reason = f"blocked gRPC: {path}"
        elif is_repo_tracking(path, host):
            action = "BLOCK"
            reason = f"repo tracking: {path}"
        elif is_sentry_envelope(host, path):
            action = "BLOCK"
            reason = f"sentry: {host}{path}"
        elif should_strip_repo(path):
            action = "STRIP"
            reason = f"strip target: {path}"
        else:
            action = "PASS"
            reason = "not matched by any rule"

        self.seq += 1
        size = len(body) if body else 0
        ts = time.strftime("%H:%M:%S")

        # Build capture record
        record = {
            "seq": self.seq,
            "ts": ts,
            "action": action,
            "method": flow.request.method,
            "host": host,
            "path": path,
            "content_type": content_type,
            "size": size,
            "reason": reason,
        }

        # Decode payload
        decoded_fields = None
        body_text = None

        if body and is_proto and size > 0:
            try:
                frames = decode_grpc_frames(body)
                if frames:
                    all_frame_fields = []
                    for _idx, (compressed, frame_data) in enumerate(frames):
                        if not compressed and frame_data:
                            fields = extract_fields(frame_data)
                            all_frame_fields.append(fields_to_dict(fields))
                    decoded_fields = all_frame_fields
                else:
                    fields = extract_fields(body)
                    decoded_fields = [fields_to_dict(fields)]
            except Exception as err:
                record["decode_error"] = str(err)
        elif body and size > 0 and size < 10000:
            try:
                body_text = body.decode("utf-8", errors="replace")
            except Exception:
                pass

        if decoded_fields:
            record["payload"] = decoded_fields
        if body_text:
            record["body"] = body_text

        # Write to JSONL file
        self.out.write(json.dumps(record) + "\n")
        self.out.flush()

        # Print live summary
        icon = {"BLOCK": "X", "STRIP": "~", "PASS": ">"}[action]
        short_path = path[:80] + "..." if len(path) > 80 else path
        print(f"[{ts}] [{icon}] {action:5s} {flow.request.method:4s} {host}{short_path}  ({size}B)", flush=True)

        # For interesting requests (PASS on cursor domains), print decoded fields
        if action == "PASS" and "cursor" in host and decoded_fields:
            for frame_dict in decoded_fields:
                self._print_interesting_fields(frame_dict, indent=2)

        # Still block the ones that should be blocked
        if action == "BLOCK":
            if is_proto:
                flow.response = http.Response.make(
                    200, b"",
                    {"content-type": "application/grpc", "grpc-status": "0", "grpc-message": ""},
                )
            else:
                flow.response = http.Response.make(
                    200, b"{}",
                    {"content-type": "application/json"},
                )

    def _print_interesting_fields(self, d: dict, indent: int = 0) -> None:
        """Print decoded protobuf fields, highlighting repo/path-like strings."""
        prefix = " " * indent
        for key, value in d.items():
            if isinstance(value, str) and len(value) > 2:
                # Highlight strings that look like repo names, paths, or URLs
                is_interesting = any(marker in value.lower() for marker in [
                    "/", ".git", "repo", "github", "gitlab", "bitbucket",
                    "workspace", "project", "cursor", ".com", ".sh",
                ])
                marker = " <<<" if is_interesting else ""
                print(f"{prefix}  f{key}: \"{value}\"{marker}", flush=True)
            elif isinstance(value, dict):
                print(f"{prefix}  f{key}: {{", flush=True)
                self._print_interesting_fields(value, indent + 4)
                print(f"{prefix}  }}", flush=True)
            elif isinstance(value, int) and value > 1000000000:
                # Likely a timestamp
                print(f"{prefix}  f{key}: {value} (timestamp?)", flush=True)

    def done(self):
        self.out.close()
        print(f"\n=== Capture saved to {OUTPUT_FILE} ({self.seq} requests) ===", flush=True)


addons = [SniffAll()]
