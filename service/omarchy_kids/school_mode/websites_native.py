"""Unprivileged native messaging: only read rules and acknowledge a generation."""
import json
from pathlib import Path
import struct
import sys
from omarchy_kids.core import proto

MAX_FRAME = 64 * 1024
SOCKET = Path("/run/omarchy-kids-controls/sock")


def read_exact(stream, size):
    chunks = bytearray()
    while len(chunks) < size:
        part = stream.read(size - len(chunks))
        if not part:
            raise EOFError
        chunks.extend(part)
    return bytes(chunks)


def read_frame(stream):
    size = struct.unpack("=I", read_exact(stream, 4))[0]
    if not 0 < size <= MAX_FRAME:
        raise ValueError("invalid frame size")
    value = json.loads(read_exact(stream, size))
    if not isinstance(value, dict):
        raise ValueError("expected an object")
    return value


def write_frame(stream, value):
    data = json.dumps(value, separators=(",", ":")).encode()
    if len(data) > MAX_FRAME:
        raise ValueError("response too large")
    stream.write(struct.pack("=I", len(data)) + data)
    stream.flush()


def relay(value, request):
    if value.get("type") == "poll" and set(value) == {"type"}:
        return request({"scope": "school", "cmd": "websites.status"})
    if value.get("type") == "ack" and set(value) <= {"type", "generation", "instance", "error"}:
        return request({"scope": "school", "cmd": "websites.ack",
                        "generation": value.get("generation"), "instance": value.get("instance"), "error": value.get("error", "")})
    raise ValueError("unsupported request")


def main():
    # Fixed system socket. Environment variables cannot redirect this bridge to
    # a different service, and no browser message becomes an arbitrary command.
    def request(value):
        try:
            return proto.request([SOCKET], value, timeout=3)
        except (OSError, proto.ProtocolError):
            return {"ok": False, "error": "service_unavailable"}
    try:
        while True:
            value = read_frame(sys.stdin.buffer)
            write_frame(sys.stdout.buffer, relay(value, request))
    except EOFError:
        return 0
    except (OSError, ValueError, struct.error):
        return 1
