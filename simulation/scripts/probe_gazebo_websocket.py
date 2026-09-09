#!/usr/bin/env python3
"""Minimal dependency-free probe for Gazebo's WebSocket scene protocol."""

from __future__ import annotations

import argparse
import base64
import hashlib
import os
import socket
import struct


def _read_exact(connection: socket.socket, length: int) -> bytes:
    data = bytearray()
    while len(data) < length:
        chunk = connection.recv(length - len(data))
        if not chunk:
            raise ConnectionError("WebSocket closed while receiving a frame")
        data.extend(chunk)
    return bytes(data)


def _send_text(connection: socket.socket, text: str) -> None:
    payload = text.encode()
    mask = os.urandom(4)
    header = bytearray([0x81])
    length = len(payload)
    if length < 126:
        header.append(0x80 | length)
    elif length <= 0xFFFF:
        header.append(0x80 | 126)
        header.extend(struct.pack("!H", length))
    else:
        header.append(0x80 | 127)
        header.extend(struct.pack("!Q", length))
    masked = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
    connection.sendall(header + mask + masked)


def _receive_frame(connection: socket.socket) -> tuple[int, bytes]:
    first, second = _read_exact(connection, 2)
    opcode = first & 0x0F
    length = second & 0x7F
    if length == 126:
        length = struct.unpack("!H", _read_exact(connection, 2))[0]
    elif length == 127:
        length = struct.unpack("!Q", _read_exact(connection, 8))[0]
    mask = _read_exact(connection, 4) if second & 0x80 else b""
    payload = _read_exact(connection, length)
    if mask:
        payload = bytes(value ^ mask[index % 4] for index, value in enumerate(payload))
    return opcode, payload


def probe(host: str, port: int, requests: tuple[str, ...]) -> list[bytes]:
    key = base64.b64encode(os.urandom(16)).decode()
    with socket.create_connection((host, port), timeout=5) as connection:
        connection.settimeout(10)
        connection.sendall(
            (
                "GET / HTTP/1.1\r\n"
                f"Host: {host}:{port}\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {key}\r\n"
                "Sec-WebSocket-Version: 13\r\n\r\n"
            ).encode()
        )
        response = bytearray()
        while b"\r\n\r\n" not in response:
            response.extend(connection.recv(4096))
        header, buffered = bytes(response).split(b"\r\n\r\n", 1)
        if b" 101 " not in header:
            raise ConnectionError(header.decode(errors="replace"))
        expected = base64.b64encode(
            hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()
        )
        if b"Sec-WebSocket-Accept: " + expected not in header:
            raise ConnectionError("Invalid WebSocket accept key")
        if buffered:
            raise ConnectionError("Unexpected data buffered after HTTP upgrade")
        responses = []
        for request in requests:
            _send_text(connection, request)
            opcode, payload = _receive_frame(connection)
            if opcode not in (1, 2):
                raise ConnectionError(
                    f"Unexpected WebSocket opcode {opcode}: {payload!r}"
                )
            responses.append(payload)
        return responses


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "requests",
        nargs="*",
        default=("worlds,,,", "scene,,,swarmroute_warehouse"),
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9002)
    arguments = parser.parse_args()
    responses = probe(arguments.host, arguments.port, tuple(arguments.requests))
    for response in responses:
        operation, topic, message_type, payload = response.split(b",", 3)
        markers = [
            marker.decode()
            for marker in (b"swarmroute_warehouse", b"warehouse_floor", b"robot_01", b"robot_12")
            if marker in payload
        ]
        print(
            f"{operation.decode()} {topic.decode()} {message_type.decode()} "
            f"payload_bytes={len(payload)} markers={','.join(markers) or '-'}"
        )


if __name__ == "__main__":
    main()
