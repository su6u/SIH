from __future__ import annotations

import heapq
import random
from dataclasses import dataclass
from enum import StrEnum

from .protocol import MessageEnvelope


class NetworkEventKind(StrEnum):
    SCHEDULED = "scheduled"
    DROPPED = "dropped"
    DUPLICATED = "duplicated"
    DELIVERED = "delivered"
    PARTITION_DROPPED = "partition_dropped"


@dataclass(frozen=True, slots=True)
class NetworkConfig:
    minimum_latency_ticks: int = 0
    maximum_latency_ticks: int = 0
    loss_rate: float = 0.0
    duplicate_rate: float = 0.0

    def __post_init__(self) -> None:
        if (
            self.minimum_latency_ticks < 0
            or self.maximum_latency_ticks < self.minimum_latency_ticks
        ):
            raise ValueError("invalid latency interval")
        if not 0 <= self.loss_rate <= 1 or not 0 <= self.duplicate_rate <= 1:
            raise ValueError("rates must be in [0, 1]")


@dataclass(frozen=True, slots=True)
class NetworkEvent:
    kind: NetworkEventKind
    tick: int
    sender_id: str
    receiver_id: str
    message_id: str


class DeterministicNetwork:
    def __init__(
        self, config: NetworkConfig = NetworkConfig(), *, seed: int = 0
    ) -> None:
        self._config = config
        self._random = random.Random(seed)
        self._nodes: set[str] = set()
        self._isolated: set[str] = set()
        self._queue: list[tuple[int, int, str, MessageEnvelope]] = []
        self._inboxes: dict[str, list[MessageEnvelope]] = {}
        self._counter = 0
        self.events: list[NetworkEvent] = []

    def register(self, node_id: str) -> None:
        if not node_id:
            raise ValueError("node_id must not be empty")
        self._nodes.add(node_id)
        self._inboxes.setdefault(node_id, [])

    def isolate(self, node_id: str, isolated: bool = True) -> None:
        if node_id not in self._nodes:
            raise ValueError(f"unknown node: {node_id}")
        if isolated:
            self._isolated.add(node_id)
        else:
            self._isolated.discard(node_id)

    def send(
        self, message: MessageEnvelope, recipients: tuple[str, ...] | list[str]
    ) -> None:
        if message.sender_id not in self._nodes:
            raise ValueError("sender is not registered")
        for receiver in recipients:
            if receiver not in self._nodes:
                raise ValueError(f"unknown receiver: {receiver}")
            if receiver == message.sender_id:
                continue
            if message.sender_id in self._isolated or receiver in self._isolated:
                self._event(
                    NetworkEventKind.PARTITION_DROPPED,
                    message.sent_tick,
                    message,
                    receiver,
                )
                continue
            if self._random.random() < self._config.loss_rate:
                self._event(
                    NetworkEventKind.DROPPED, message.sent_tick, message, receiver
                )
                continue
            self._schedule(message, receiver, duplicated=False)
            if self._random.random() < self._config.duplicate_rate:
                self._schedule(message, receiver, duplicated=True)

    def _schedule(
        self, message: MessageEnvelope, receiver: str, *, duplicated: bool
    ) -> None:
        latency = self._random.randint(
            self._config.minimum_latency_ticks, self._config.maximum_latency_ticks
        )
        delivery_tick = message.sent_tick + latency
        self._counter += 1
        heapq.heappush(self._queue, (delivery_tick, self._counter, receiver, message))
        kind = NetworkEventKind.DUPLICATED if duplicated else NetworkEventKind.SCHEDULED
        self._event(kind, delivery_tick, message, receiver)

    def advance(self, current_tick: int) -> None:
        while self._queue and self._queue[0][0] <= current_tick:
            delivery_tick, _, receiver, message = heapq.heappop(self._queue)
            if message.sender_id in self._isolated or receiver in self._isolated:
                self._event(
                    NetworkEventKind.PARTITION_DROPPED, delivery_tick, message, receiver
                )
                continue
            self._inboxes[receiver].append(message)
            self._event(NetworkEventKind.DELIVERED, delivery_tick, message, receiver)

    def receive(self, node_id: str) -> tuple[MessageEnvelope, ...]:
        messages = tuple(self._inboxes.get(node_id, ()))
        self._inboxes[node_id] = []
        return messages

    def _event(
        self,
        kind: NetworkEventKind,
        tick: int,
        message: MessageEnvelope,
        receiver: str,
    ) -> None:
        self.events.append(
            NetworkEvent(kind, tick, message.sender_id, receiver, message.message_id)
        )
