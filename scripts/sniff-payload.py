"""Sniff-and-block addon for mitmproxy.

Combines request blocking with detailed payload inspection. For each
blocked or strip-eligible request, it decodes gRPC/protobuf frames and
prints the extracted fields to stdout. Useful for discovering new
telemetry endpoints and understanding what data Cursor sends.

Usage:
    make sniff          # via Makefile (if target added)
    uv run mitmdump --scripts scripts/sniff-payload.py
"""

import sys
import struct
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


class TelemetrySniffAndBlock:
    def __init__(self):
        self.seq = 0
        print("=== SNIFF+BLOCK MODE: logging contents of blocked/interesting requests ===", flush=True)

    def request(self, flow: http.HTTPFlow) -> None:
        host = flow.request.pretty_host
        path = flow.request.path
        content_type = flow.request.headers.get("content-type", "")
        is_proto = "grpc" in content_type or "proto" in content_type
        body = flow.request.content

        action = "PASS"
        reason = ""

        if is_blocked_domain(host):
            action = "BLOCK"
            reason = f"blocked domain: {host}"
        elif is_blocked_grpc_path(path):
            action = "BLOCK"
            reason = f"blocked gRPC: {path}"
        elif is_repo_tracking(path):
            action = "BLOCK"
            reason = f"repo tracking: {path}"
        elif is_sentry_envelope(host, path):
            action = "BLOCK"
            reason = f"sentry: {host}{path}"
        elif should_strip_repo(path):
            action = "STRIP"
            reason = f"strip repo info: {path}"

        if action == "PASS":
            return

        self.seq += 1
        size = len(body) if body else 0

        separator = "=" * 70
        print(f"\n{separator}", flush=True)
        print(f"[{self.seq}] {action} | {flow.request.method} {host}{path}", flush=True)
        print(f"    reason: {reason}", flush=True)
        print(f"    content_type: {content_type}  size: {size}B", flush=True)

        if body and is_proto and size > 0:
            try:
                frames = decode_grpc_frames(body)
                if frames:
                    for frame_idx, (compressed, frame_data) in enumerate(frames):
                        print(f"    grpc_frame[{frame_idx}]: {len(frame_data)}B {'(compressed)' if compressed else ''}", flush=True)
                        if not compressed and frame_data:
                            fields = extract_fields(frame_data)
                            lines = flatten_strings(fields)
                            for line in lines:
                                print(f"      {line}", flush=True)
                else:
                    fields = extract_fields(body)
                    lines = flatten_strings(fields)
                    for line in lines:
                        print(f"      {line}", flush=True)
            except Exception as err:
                print(f"    decode_error: {err}", flush=True)

        elif body and size > 0:
            try:
                text = body.decode("utf-8", errors="replace")
                preview = text[:2000]
                if len(text) > 2000:
                    preview += "...(truncated)"
                print(f"    body: {preview}", flush=True)
            except Exception:
                print(f"    body_hex: {body[:200].hex()}", flush=True)

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
            print(f"    >>> REQUEST BLOCKED (fake 200 returned)", flush=True)

        elif action == "STRIP":
            print(f"    >>> REQUEST STRIPPED and forwarded (repo fields removed)", flush=True)

        print(separator, flush=True)
        sys.stdout.flush()


addons = [TelemetrySniffAndBlock()]
