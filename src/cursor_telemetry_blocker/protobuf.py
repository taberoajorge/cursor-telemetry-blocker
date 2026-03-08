import io
import struct

WIRE_TYPE_VARINT = 0
WIRE_TYPE_64BIT = 1
WIRE_TYPE_LENGTH_DELIMITED = 2
WIRE_TYPE_32BIT = 5

REPO_STRING_FIELDS = (2, 3, 4, 5, 11)
REPO_TRACKED_FIELD = 6

REQUEST_WORKSPACE_PATH_FIELD = 5
REQUEST_REPO_FIELD = 3


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
    raise ValueError("Truncated varint")


def encode_varint(value: int) -> bytes:
    parts = []
    while value > 0x7F:
        parts.append((value & 0x7F) | 0x80)
        value >>= 7
    parts.append(value & 0x7F)
    return bytes(parts)


def strip_repo_info_from_protobuf(data: bytes) -> bytes:
    output = io.BytesIO()
    offset = 0

    while offset < len(data):
        try:
            tag, new_offset = decode_varint(data, offset)
        except ValueError:
            output.write(data[offset:])
            break

        field_number = tag >> 3
        wire_type = tag & 0x07

        if wire_type == WIRE_TYPE_VARINT:
            _, end_offset = decode_varint(data, new_offset)
            output.write(data[offset:end_offset])
            offset = end_offset

        elif wire_type == WIRE_TYPE_64BIT:
            end_offset = new_offset + 8
            output.write(data[offset:end_offset])
            offset = end_offset

        elif wire_type == WIRE_TYPE_32BIT:
            end_offset = new_offset + 4
            output.write(data[offset:end_offset])
            offset = end_offset

        elif wire_type == WIRE_TYPE_LENGTH_DELIMITED:
            try:
                length, content_offset = decode_varint(data, new_offset)
            except ValueError:
                output.write(data[offset:])
                break

            field_end = content_offset + length

            if field_number == REQUEST_WORKSPACE_PATH_FIELD and length < 500:
                offset = field_end
                continue

            if field_number == REQUEST_REPO_FIELD and length > 10:
                cleaned_submessage = redact_repository_info(data[content_offset:field_end])
                output.write(encode_varint(tag))
                output.write(encode_varint(len(cleaned_submessage)))
                output.write(cleaned_submessage)
            else:
                output.write(data[offset:field_end])

            offset = field_end
        else:
            output.write(data[offset:])
            break

    return output.getvalue()


def redact_repository_info(data: bytes) -> bytes:
    output = io.BytesIO()
    offset = 0

    while offset < len(data):
        try:
            tag, new_offset = decode_varint(data, offset)
        except ValueError:
            output.write(data[offset:])
            break

        field_number = tag >> 3
        wire_type = tag & 0x07

        if wire_type == WIRE_TYPE_LENGTH_DELIMITED:
            try:
                length, content_offset = decode_varint(data, new_offset)
            except ValueError:
                output.write(data[offset:])
                break

            field_end = content_offset + length

            if field_number in REPO_STRING_FIELDS:
                offset = field_end
                continue

            output.write(data[offset:field_end])
            offset = field_end

        elif wire_type == WIRE_TYPE_VARINT:
            _, end_offset = decode_varint(data, new_offset)

            if field_number == REPO_TRACKED_FIELD:
                output.write(encode_varint((REPO_TRACKED_FIELD << 3) | WIRE_TYPE_VARINT))
                output.write(encode_varint(0))
            else:
                output.write(data[offset:end_offset])

            offset = end_offset

        elif wire_type == WIRE_TYPE_64BIT:
            end_offset = new_offset + 8
            output.write(data[offset:end_offset])
            offset = end_offset

        elif wire_type == WIRE_TYPE_32BIT:
            end_offset = new_offset + 4
            output.write(data[offset:end_offset])
            offset = end_offset

        else:
            output.write(data[offset:])
            break

    return output.getvalue()


def decode_grpc_frames(body: bytes) -> list[tuple[bool, bytes]]:
    frames = []
    offset = 0
    while offset + 5 <= len(body):
        compressed = body[offset]
        frame_length = struct.unpack(">I", body[offset + 1 : offset + 5])[0]
        frame_data = body[offset + 5 : offset + 5 + frame_length]
        frames.append((bool(compressed), frame_data))
        offset += 5 + frame_length
    return frames


def encode_grpc_frames(frames: list[tuple[bool, bytes]]) -> bytes:
    output = io.BytesIO()
    for compressed, frame_data in frames:
        output.write(bytes([1 if compressed else 0]))
        output.write(struct.pack(">I", len(frame_data)))
        output.write(frame_data)
    return output.getvalue()
