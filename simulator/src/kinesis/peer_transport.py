from __future__ import annotations

import socket
from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping, Protocol

from .protocol import MessageEnvelope, MessageRejected


@dataclass(frozen=True, slots=True)
class PeerEndpoint:
    host: str
    port: int

    def __post_init__(self) -> None:
        if not self.host:
            raise ValueError("peer host must not be empty")
        if isinstance(self.port, bool) or not isinstance(self.port, int):
            raise ValueError("peer port must be an integer")
        if not 1 <= self.port <= 65_535:
            raise ValueError("peer port must be in [1, 65535]")


class PeerTransport(Protocol):
    def send(
        self, message: MessageEnvelope, recipients: tuple[str, ...] | list[str]
    ) -> None: ...

    def receive(self, node_id: str) -> tuple[MessageEnvelope, ...]: ...

    def close(self) -> None: ...


class DatagramEventKind(StrEnum):
    SENT = "sent"
    RECEIVED = "received"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class DatagramEvent:
    kind: DatagramEventKind
    local_id: str
    peer: str
    detail: str


class UdpPeerTransport:
    """Direct robot-to-robot datagrams with no broker or discovery server.

    This transport is deliberately small and dependency-free so the distributed
    protocol can be exercised across real OS processes and hosts. HMAC,
    freshness, membership, and payload validation remain protocol concerns in
    ``DistributedRobotNode``. Production ROS deployment should map the same
    message contracts to DDS with SROS 2 rather than treating this test
    transport as a safety-certified network stack.
    """

    MAX_DATAGRAM_BYTES = 65_507

    def __init__(
        self,
        *,
        local_id: str,
        endpoints: Mapping[str, PeerEndpoint],
        receive_buffer_bytes: int = MAX_DATAGRAM_BYTES,
    ) -> None:
        if local_id not in endpoints:
            raise ValueError("local robot must have a configured endpoint")
        if len(endpoints) < 2:
            raise ValueError("distributed transport requires at least two peers")
        if not 1 <= receive_buffer_bytes <= self.MAX_DATAGRAM_BYTES:
            raise ValueError("receive buffer is outside UDP datagram limits")
        duplicate_endpoints = len({(item.host, item.port) for item in endpoints.values()})
        if duplicate_endpoints != len(endpoints):
            raise ValueError("peer endpoints must be unique")

        self.local_id = local_id
        self._endpoints = dict(endpoints)
        self._receive_buffer_bytes = receive_buffer_bytes
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        local = self._endpoints[local_id]
        self._socket.bind((local.host, local.port))
        self._socket.setblocking(False)
        self.events: list[DatagramEvent] = []
        self._closed = False

    def send(
        self, message: MessageEnvelope, recipients: tuple[str, ...] | list[str]
    ) -> None:
        self._ensure_open()
        if message.sender_id != self.local_id:
            raise ValueError("transport may send only the local robot's messages")
        encoded = message.to_bytes()
        if len(encoded) > self.MAX_DATAGRAM_BYTES:
            raise ValueError("message exceeds maximum UDP datagram size")
        for recipient in recipients:
            if recipient == self.local_id:
                continue
            endpoint = self._endpoints.get(recipient)
            if endpoint is None:
                raise ValueError(f"unknown peer: {recipient}")
            self._socket.sendto(encoded, (endpoint.host, endpoint.port))
            self.events.append(
                DatagramEvent(
                    DatagramEventKind.SENT,
                    self.local_id,
                    recipient,
                    message.message_id,
                )
            )

    def receive(self, node_id: str) -> tuple[MessageEnvelope, ...]:
        self._ensure_open()
        if node_id != self.local_id:
            raise ValueError("transport may receive only for its local robot")
        messages: list[MessageEnvelope] = []
        while True:
            try:
                raw, source = self._socket.recvfrom(self._receive_buffer_bytes + 1)
            except BlockingIOError:
                break
            source_label = f"{source[0]}:{source[1]}"
            if len(raw) > self._receive_buffer_bytes:
                self.events.append(
                    DatagramEvent(
                        DatagramEventKind.REJECTED,
                        self.local_id,
                        source_label,
                        "datagram exceeds configured receive limit",
                    )
                )
                continue
            try:
                message = MessageEnvelope.from_bytes(
                    raw, maximum_bytes=self._receive_buffer_bytes
                )
            except MessageRejected as error:
                self.events.append(
                    DatagramEvent(
                        DatagramEventKind.REJECTED,
                        self.local_id,
                        source_label,
                        str(error),
                    )
                )
                continue
            messages.append(message)
            self.events.append(
                DatagramEvent(
                    DatagramEventKind.RECEIVED,
                    self.local_id,
                    message.sender_id,
                    message.message_id,
                )
            )
        return tuple(messages)

    def close(self) -> None:
        if not self._closed:
            self._socket.close()
            self._closed = True

    def __enter__(self) -> "UdpPeerTransport":
        self._ensure_open()
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("transport is closed")
