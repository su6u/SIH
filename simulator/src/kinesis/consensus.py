from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from .allocation import Bid, BidComponents, select_winner
from .network import DeterministicNetwork
from .protocol import MessageEnvelope, MessageRejected, ReplayGuard


class AuctionProtocolError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class BidRecord:
    task_id: str
    auction_epoch: int
    robot_id: str
    boot_id: str
    revision: int
    feasible: bool
    score: float
    workload: int

    @classmethod
    def from_bid(cls, bid: Bid, *, boot_id: str, revision: int) -> "BidRecord":
        if revision < 0:
            raise ValueError("revision must be non-negative")
        return cls(
            task_id=bid.task_id,
            auction_epoch=bid.auction_epoch,
            robot_id=bid.robot_id,
            boot_id=boot_id,
            revision=revision,
            feasible=bid.feasible,
            score=bid.score,
            workload=bid.workload,
        )

    def to_bid(self) -> Bid:
        return Bid(
            robot_id=self.robot_id,
            task_id=self.task_id,
            auction_epoch=self.auction_epoch,
            feasible=self.feasible,
            score=self.score,
            components=BidComponents(0.0, 0.0, 0.0, 0.0),
            expected_finish_tick=None,
            expected_soc=None,
            workload=self.workload,
            reason="replicated infeasible bid" if not self.feasible else None,
        )


@dataclass(frozen=True, slots=True)
class ReplicaEvent:
    tick: int
    kind: str
    detail: str


class AuctionReplica:
    MESSAGE_KIND = "auction_bid_gossip"

    def __init__(
        self,
        *,
        robot_id: str,
        boot_id: str,
        members: Mapping[str, str],
        authentication_keys: Mapping[str, bytes],
        map_version: str,
        network: DeterministicNetwork,
        neighbors: tuple[str, ...],
        message_ttl_ticks: int = 5,
        fairness_tolerance: float = 0.05,
    ) -> None:
        if members.get(robot_id) != boot_id:
            raise ValueError("local robot boot identity must match membership")
        if set(authentication_keys) != set(members):
            raise ValueError("authentication keys must match membership")
        unknown = set(neighbors) - set(members)
        if unknown or robot_id in neighbors:
            raise ValueError(f"invalid neighbors: {sorted(unknown)}")
        if message_ttl_ticks <= 0:
            raise ValueError("message_ttl_ticks must be positive")
        self.robot_id = robot_id
        self.boot_id = boot_id
        self._members = dict(members)
        self._map_version = map_version
        self._authentication_keys = dict(authentication_keys)
        self._network = network
        self._neighbors = tuple(sorted(neighbors))
        self._ttl = message_ttl_ticks
        self._fairness_tolerance = fairness_tolerance
        self._guard = ReplayGuard(
            schema_version="1.0",
            map_version=map_version,
            authentication_keys=authentication_keys,
        )
        self._records: dict[tuple[str, int, str], BidRecord] = {}
        self._send_sequence = 0
        self.events: list[ReplicaEvent] = []

    def observe_local_bid(self, bid: Bid, *, revision: int, current_tick: int) -> None:
        if bid.robot_id != self.robot_id:
            raise AuctionProtocolError("a replica may originate only its own bid")
        self._merge(
            BidRecord.from_bid(bid, boot_id=self.boot_id, revision=revision),
            current_tick=current_tick,
        )

    def broadcast(self, *, current_tick: int) -> MessageEnvelope:
        records = [
            asdict(record)
            for record in sorted(
                self._records.values(),
                key=lambda item: (item.task_id, item.auction_epoch, item.robot_id),
            )
        ]
        message = MessageEnvelope.create(
            kind=self.MESSAGE_KIND,
            sender_id=self.robot_id,
            boot_id=self.boot_id,
            sequence=self._send_sequence,
            sent_tick=current_tick,
            ttl_ticks=self._ttl,
            map_version=self._map_version,
            payload={"records": records},
            signing_key=self._authentication_keys[self.robot_id],
        )
        self._send_sequence += 1
        self._network.send(message, self._neighbors)
        self.events.append(ReplicaEvent(current_tick, "broadcast", message.message_id))
        return message

    def receive(self, *, current_tick: int) -> None:
        for message in self._network.receive(self.robot_id):
            records_before = dict(self._records)
            events_before = len(self.events)
            try:
                self._guard.validate(message, current_tick=current_tick)
                if message.kind != self.MESSAGE_KIND:
                    raise AuctionProtocolError(
                        f"unexpected message kind: {message.kind}"
                    )
                records = message.payload.get("records")
                if not isinstance(records, list):
                    raise AuctionProtocolError("gossip records must be an array")
                parsed = tuple(parse_bid_record(raw) for raw in records)
                for record in parsed:
                    self._merge(record, current_tick=current_tick)
                self._guard.accept(message, current_tick=current_tick)
                self.events.append(
                    ReplicaEvent(current_tick, "accepted", message.message_id)
                )
            except (MessageRejected, AuctionProtocolError) as error:
                self._records = records_before
                del self.events[events_before:]
                self.events.append(ReplicaEvent(current_tick, "rejected", str(error)))

    def records_for(self, task_id: str, auction_epoch: int) -> tuple[BidRecord, ...]:
        return tuple(
            sorted(
                (
                    record
                    for key, record in self._records.items()
                    if key[0] == task_id and key[1] == auction_epoch
                ),
                key=lambda record: record.robot_id,
            )
        )

    def has_complete_view(self, task_id: str, auction_epoch: int) -> bool:
        origins = {
            record.robot_id for record in self.records_for(task_id, auction_epoch)
        }
        return origins == set(self._members)

    def local_winner(self, task_id: str, auction_epoch: int) -> Bid | None:
        bids = tuple(
            record.to_bid() for record in self.records_for(task_id, auction_epoch)
        )
        if not any(bid.feasible for bid in bids):
            return None
        return select_winner(bids, fairness_tolerance=self._fairness_tolerance)

    def claim_candidate(self, task_id: str, auction_epoch: int) -> Bid | None:
        if not self.has_complete_view(task_id, auction_epoch):
            return None
        return self.local_winner(task_id, auction_epoch)

    def _merge(self, record: BidRecord, *, current_tick: int) -> None:
        expected_boot = self._members.get(record.robot_id)
        if expected_boot is None or expected_boot != record.boot_id:
            raise AuctionProtocolError("bid origin is outside current membership epoch")
        if record.auction_epoch < 0 or record.revision < 0 or record.workload < 0:
            raise AuctionProtocolError("negative auction fields are invalid")
        if not math.isfinite(record.score) or record.score < 0:
            raise AuctionProtocolError("bid score must be finite and non-negative")
        key = (record.task_id, record.auction_epoch, record.robot_id)
        existing = self._records.get(key)
        if existing is not None:
            if record.revision < existing.revision:
                return
            if record.revision == existing.revision:
                if record != existing:
                    raise AuctionProtocolError("equivocation at the same bid revision")
                return
        self._records[key] = record
        self.events.append(
            ReplicaEvent(
                current_tick,
                "bid_merged",
                f"{record.task_id}:{record.robot_id}:{record.revision}",
            )
        )


def parse_bid_record(raw: Any) -> BidRecord:
    if not isinstance(raw, dict):
        raise AuctionProtocolError("bid record must be an object")
    required = {
        "task_id",
        "auction_epoch",
        "robot_id",
        "boot_id",
        "revision",
        "feasible",
        "score",
        "workload",
    }
    if set(raw) != required:
        raise AuctionProtocolError("bid record fields do not match schema")
    if not all(
        isinstance(raw[field], str) and raw[field]
        for field in ("task_id", "robot_id", "boot_id")
    ):
        raise AuctionProtocolError("bid string fields must be non-empty")
    if not isinstance(raw["feasible"], bool):
        raise AuctionProtocolError("feasible must be boolean")
    for field in ("auction_epoch", "revision", "workload"):
        if isinstance(raw[field], bool) or not isinstance(raw[field], int):
            raise AuctionProtocolError(f"{field} must be an integer")
    if isinstance(raw["score"], bool) or not isinstance(raw["score"], (int, float)):
        raise AuctionProtocolError("score must be numeric")
    return BidRecord(
        task_id=raw["task_id"],
        auction_epoch=raw["auction_epoch"],
        robot_id=raw["robot_id"],
        boot_id=raw["boot_id"],
        revision=raw["revision"],
        feasible=raw["feasible"],
        score=float(raw["score"]),
        workload=raw["workload"],
    )
