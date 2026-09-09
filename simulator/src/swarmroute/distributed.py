from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from .allocation import Bid, select_winner
from .consensus import (
    AuctionProtocolError,
    BidRecord,
    parse_bid_record,
)
from .domain import Cell
from .durable import PeerStateStore
from .membership import (
    MembershipError,
    MembershipState,
    MembershipView,
    MembershipVote,
)
from .peer_transport import PeerTransport
from .protocol import MessageEnvelope, MessageRejected, ReplayGuard


class DistributedProtocolError(ValueError):
    pass


def unix_time_ms() -> int:
    return time.time_ns() // 1_000_000


@dataclass(frozen=True, slots=True)
class RobotIntent:
    robot_id: str
    boot_id: str
    revision: int
    plan_epoch: int
    step_duration_ms: int
    cell: Cell
    path: tuple[Cell, ...]
    task_id: str | None
    battery_soc: float
    position_uncertainty_m: float
    mode: str

    def __post_init__(self) -> None:
        if not self.robot_id or not self.boot_id or not self.mode:
            raise ValueError("intent identity and mode must not be empty")
        if self.revision < 0 or self.plan_epoch < 0 or self.step_duration_ms <= 0:
            raise ValueError("intent revision, plan epoch, or step duration is invalid")
        if not self.path or len(self.path) > 64:
            raise ValueError("intent path must contain between 1 and 64 cells")
        if self.path[0] != self.cell:
            raise ValueError("intent path must begin at the current cell")
        for previous, current in zip(self.path, self.path[1:], strict=False):
            if previous.manhattan_distance(current) > 1:
                raise ValueError("intent path moves must be cardinal or wait actions")
        if self.task_id is not None and not self.task_id:
            raise ValueError("task_id must be non-empty when present")
        if not math.isfinite(self.battery_soc) or not 0 <= self.battery_soc <= 1:
            raise ValueError("battery_soc must be in [0, 1]")
        if (
            not math.isfinite(self.position_uncertainty_m)
            or self.position_uncertainty_m < 0
        ):
            raise ValueError("position uncertainty must be finite and non-negative")

    def to_payload(self) -> dict[str, Any]:
        return {
            "robot_id": self.robot_id,
            "boot_id": self.boot_id,
            "revision": self.revision,
            "plan_epoch": self.plan_epoch,
            "step_duration_ms": self.step_duration_ms,
            "cell": {"x": self.cell.x, "y": self.cell.y},
            "path": [{"x": item.x, "y": item.y} for item in self.path],
            "task_id": self.task_id,
            "battery_soc": self.battery_soc,
            "position_uncertainty_m": self.position_uncertainty_m,
            "mode": self.mode,
        }

    @classmethod
    def from_payload(cls, raw: Any) -> "RobotIntent":
        if not isinstance(raw, dict):
            raise DistributedProtocolError("intent payload must be an object")
        required = {
            "robot_id",
            "boot_id",
            "revision",
            "plan_epoch",
            "step_duration_ms",
            "cell",
            "path",
            "task_id",
            "battery_soc",
            "position_uncertainty_m",
            "mode",
        }
        if set(raw) != required:
            raise DistributedProtocolError("intent fields do not match schema")
        if not all(
            isinstance(raw[field], str) and raw[field]
            for field in ("robot_id", "boot_id", "mode")
        ):
            raise DistributedProtocolError("intent identity fields are invalid")
        for field in ("revision", "plan_epoch", "step_duration_ms"):
            if isinstance(raw[field], bool) or not isinstance(raw[field], int):
                raise DistributedProtocolError(f"intent {field} must be an integer")
        if raw["task_id"] is not None and (
            not isinstance(raw["task_id"], str) or not raw["task_id"]
        ):
            raise DistributedProtocolError("intent task_id is invalid")
        battery = raw["battery_soc"]
        uncertainty = raw["position_uncertainty_m"]
        if isinstance(battery, bool) or not isinstance(battery, (int, float)):
            raise DistributedProtocolError("intent battery_soc must be numeric")
        if isinstance(uncertainty, bool) or not isinstance(uncertainty, (int, float)):
            raise DistributedProtocolError(
                "intent position_uncertainty_m must be numeric"
            )
        return cls(
            robot_id=raw["robot_id"],
            boot_id=raw["boot_id"],
            revision=raw["revision"],
            plan_epoch=raw["plan_epoch"],
            step_duration_ms=raw["step_duration_ms"],
            cell=_parse_cell(raw["cell"]),
            path=tuple(_parse_cell(item) for item in _parse_path(raw["path"])),
            task_id=raw["task_id"],
            battery_soc=float(battery),
            position_uncertainty_m=float(uncertainty),
            mode=raw["mode"],
        )


@dataclass(frozen=True, slots=True)
class DistributedEvent:
    time_ms: int
    kind: str
    peer_id: str
    detail: str


@dataclass(frozen=True, slots=True)
class IntentConflict:
    peer_id: str
    kind: str
    starts_at_ms: int
    ends_at_ms: int
    local_from: Cell
    local_to: Cell


@dataclass(frozen=True, slots=True)
class TaskClaimRecord:
    task_id: str
    auction_epoch: int
    winner_id: str
    membership_epoch: int
    revision: int
    fence_token: int


@dataclass(frozen=True, slots=True)
class TaskCompletionRecord:
    task_id: str
    auction_epoch: int
    winner_id: str
    membership_epoch: int
    revision: int
    fence_token: int


class DistributedRobotNode:
    """One robot's private replicated state and peer protocol endpoint.

    One instance is intended to live in exactly one robot process. It never
    creates another robot's replica and never owns a fleet-wide network object.
    Removal-only membership changes require a durable predecessor majority;
    heartbeat timeouts provide suspicion but never authority by themselves.
    """

    INTENT_KIND = "robot_state_intent"
    BID_KIND = "auction_bid_gossip"
    HEARTBEAT_KIND = "robot_heartbeat"
    MEMBERSHIP_VOTE_KIND = "membership_vote"
    TASK_CLAIM_KIND = "task_claim"
    TASK_DONE_KIND = "task_completion"
    SEQUENCE_RESERVATION_SIZE = 1_024
    REVISION_STREAMS = frozenset({"intent", "bid", "claim", "completion"})

    def __init__(
        self,
        *,
        robot_id: str,
        boot_id: str,
        members: Mapping[str, str],
        authentication_keys: Mapping[str, bytes],
        map_version: str,
        transport: PeerTransport,
        neighbors: tuple[str, ...],
        message_ttl_ms: int = 1_000,
        maximum_clock_skew_ms: int = 250,
        fairness_tolerance: float = 0.05,
        state_store: PeerStateStore | None = None,
        deployment_id: str | None = None,
    ) -> None:
        if members.get(robot_id) != boot_id:
            raise ValueError("local robot boot identity must match membership")
        if set(authentication_keys) != set(members):
            raise ValueError("authentication keys must match membership")
        unknown = set(neighbors) - set(members)
        if unknown or robot_id in neighbors:
            raise ValueError(f"invalid neighbors: {sorted(unknown)}")
        if set(neighbors) != set(members) - {robot_id}:
            raise ValueError("safety-critical intent exchange requires full-mesh peers")
        if message_ttl_ms <= 0 or maximum_clock_skew_ms < 0:
            raise ValueError("message timing limits are invalid")
        if not 0 <= fairness_tolerance <= 1:
            raise ValueError("fairness_tolerance must be in [0, 1]")

        self.robot_id = robot_id
        self.boot_id = boot_id
        self._known_members = dict(members)
        self._membership = MembershipState(members)
        self._members = self._membership.current.member_map
        self._authentication_keys = dict(authentication_keys)
        self._map_version = map_version
        self._deployment_id = deployment_id or map_version
        if not self._deployment_id:
            raise ValueError("deployment_id must not be empty")
        self._transport = transport
        self._neighbors = tuple(sorted(neighbors))
        self._ttl_ms = message_ttl_ms
        self._fairness_tolerance = fairness_tolerance
        self._state_store = state_store
        self._higher_epoch_observed = False
        self._local_membership_vote: MembershipVote | None = None
        self._guard = ReplayGuard(
            schema_version="1.0",
            map_version=map_version,
            authentication_keys=authentication_keys,
            maximum_future_skew_ticks=maximum_clock_skew_ms,
        )
        self._send_sequence = 0
        self._sequence_limit = 0
        self._revision_next = {stream: 0 for stream in self.REVISION_STREAMS}
        self._revision_limits = {stream: 0 for stream in self.REVISION_STREAMS}
        self._bid_records: dict[tuple[str, int, str], BidRecord] = {}
        self._peer_intents: dict[str, RobotIntent] = {}
        self._peer_intent_sent_ms: dict[str, int] = {}
        self._intent_deadlines_ms: dict[str, int] = {}
        self._liveness_deadlines_ms: dict[str, int] = {}
        self._claimed_tasks: dict[tuple[str, int], TaskClaimRecord] = {}
        self._completed_tasks: dict[tuple[str, int], TaskCompletionRecord] = {}
        self.events: list[DistributedEvent] = []
        self._restore_state()
        self._activate_membership_view()

    @property
    def membership_epoch(self) -> int:
        return self._membership.current.epoch

    @property
    def membership_digest(self) -> str:
        return self._membership.current.digest

    @property
    def is_active_member(self) -> bool:
        return self.robot_id in self._members and not self._higher_epoch_observed

    @property
    def active_members(self) -> tuple[str, ...]:
        return tuple(sorted(self._members))

    def live_members(self, *, current_time_ms: int | None = None) -> tuple[str, ...]:
        now = unix_time_ms() if current_time_ms is None else current_time_ms
        live = {
            robot_id
            for robot_id, deadline in self._liveness_deadlines_ms.items()
            if robot_id in self._members and deadline >= now
        }
        if self.robot_id in self._members:
            live.add(self.robot_id)
        return tuple(sorted(live))

    def has_live_quorum(self, *, current_time_ms: int | None = None) -> bool:
        return len(self.live_members(current_time_ms=current_time_ms)) >= (
            len(self._members) // 2 + 1
        )

    def next_local_revision(self, stream: str) -> int:
        """Return a durable, restart-monotonic application revision."""
        if stream not in self.REVISION_STREAMS:
            raise ValueError(f"unknown revision stream: {stream}")
        revision = self._revision_next[stream]
        if revision >= self._revision_limits[stream]:
            self._revision_limits[stream] = (
                revision + self.SEQUENCE_RESERVATION_SIZE
            )
            self._persist_state()
        self._revision_next[stream] = revision + 1
        return revision

    def completed_task_count(self, robot_id: str) -> int:
        return sum(
            record.winner_id == robot_id
            for record in self._completed_tasks.values()
        )

    def publish_membership_vote(
        self,
        retained_members: set[str] | frozenset[str],
        *,
        current_time_ms: int | None = None,
    ) -> None:
        self._require_active()
        vote = self._membership.create_vote(self.robot_id, retained_members)
        installed = self._membership.merge(vote)
        self._local_membership_vote = vote
        self._persist_state()
        now = unix_time_ms() if current_time_ms is None else current_time_ms
        self._send(
            kind=self.MEMBERSHIP_VOTE_KIND,
            payload=vote.to_mapping(),
            current_time_ms=now,
        )
        if installed is not None:
            self._activate_membership_view(current_time_ms=now)

    def repeat_membership_vote(
        self, *, current_time_ms: int | None = None
    ) -> None:
        if self._local_membership_vote is None or not self.is_active_member:
            return
        now = unix_time_ms() if current_time_ms is None else current_time_ms
        self._send(
            kind=self.MEMBERSHIP_VOTE_KIND,
            payload=self._local_membership_vote.to_mapping(),
            current_time_ms=now,
        )

    def publish_heartbeat(self, *, current_time_ms: int | None = None) -> None:
        self._require_active()
        now = unix_time_ms() if current_time_ms is None else current_time_ms
        self._send(
            kind=self.HEARTBEAT_KIND,
            payload={
                "robot_id": self.robot_id,
                "boot_id": self.boot_id,
                "membership_epoch": self.membership_epoch,
                "membership_digest": self.membership_digest,
            },
            current_time_ms=now,
        )

    def publish_intent(
        self, intent: RobotIntent, *, current_time_ms: int | None = None
    ) -> None:
        self._require_active()
        if intent.robot_id != self.robot_id or intent.boot_id != self.boot_id:
            raise DistributedProtocolError("node may publish only its own intent")
        now = unix_time_ms() if current_time_ms is None else current_time_ms
        self._peer_intents[self.robot_id] = intent
        self._peer_intent_sent_ms[self.robot_id] = now
        self._intent_deadlines_ms[self.robot_id] = now + self._ttl_ms
        self._send(
            kind=self.INTENT_KIND,
            payload=intent.to_payload(),
            current_time_ms=now,
        )

    def publish_bid(
        self,
        bid: Bid,
        *,
        revision: int,
        current_time_ms: int | None = None,
    ) -> None:
        self._require_active()
        if bid.robot_id != self.robot_id:
            raise AuctionProtocolError("node may originate only its own bid")
        now = unix_time_ms() if current_time_ms is None else current_time_ms
        self._merge_bid(
            BidRecord.from_bid(bid, boot_id=self.boot_id, revision=revision),
            current_time_ms=now,
        )
        self.gossip_bid_view(current_time_ms=now)

    def gossip_bid_view(self, *, current_time_ms: int | None = None) -> None:
        self._require_active()
        now = unix_time_ms() if current_time_ms is None else current_time_ms
        records = [
            asdict(record)
            for record in sorted(
                self._bid_records.values(),
                key=lambda item: (item.task_id, item.auction_epoch, item.robot_id),
            )
        ]
        self._send(
            kind=self.BID_KIND,
            payload={"records": records},
            current_time_ms=now,
        )

    def publish_task_done(
        self,
        task_id: str,
        auction_epoch: int,
        *,
        completion_revision: int,
        current_time_ms: int | None = None,
    ) -> None:
        """Gossip an idempotent completion marker from the winning peer."""
        self._require_active()
        if (
            not isinstance(task_id, str)
            or not task_id
            or isinstance(auction_epoch, bool)
            or not isinstance(auction_epoch, int)
            or auction_epoch < 0
            or isinstance(completion_revision, bool)
            or not isinstance(completion_revision, int)
            or completion_revision < 0
        ):
            raise DistributedProtocolError("task completion fields are invalid")
        now = unix_time_ms() if current_time_ms is None else current_time_ms
        claim = self._claimed_tasks.get((task_id, auction_epoch))
        if claim is None or claim.winner_id != self.robot_id:
            raise DistributedProtocolError(
                "task completion requires the local active fenced claim"
            )
        self._merge_task_done(
            task_id,
            auction_epoch,
            self.robot_id,
            claim.membership_epoch,
            completion_revision,
            claim.fence_token,
            current_time_ms=now,
        )
        self._send(
            kind=self.TASK_DONE_KIND,
            payload={
                "task_id": task_id,
                "auction_epoch": auction_epoch,
                "winner_id": self.robot_id,
                "membership_epoch": claim.membership_epoch,
                "completion_revision": completion_revision,
                "fence_token": claim.fence_token,
            },
            current_time_ms=now,
        )

    def publish_task_claim(
        self,
        task_id: str,
        auction_epoch: int,
        *,
        claim_revision: int,
        current_time_ms: int | None = None,
    ) -> None:
        """Gossip the winner's durable claim before route execution begins."""
        self._require_active()
        if (
            not isinstance(task_id, str)
            or not task_id
            or isinstance(auction_epoch, bool)
            or not isinstance(auction_epoch, int)
            or auction_epoch < 0
            or isinstance(claim_revision, bool)
            or not isinstance(claim_revision, int)
            or claim_revision < 0
        ):
            raise DistributedProtocolError("task claim fields are invalid")
        now = unix_time_ms() if current_time_ms is None else current_time_ms
        fence_token = _fence_token(
            self.membership_epoch, auction_epoch, claim_revision
        )
        self._merge_task_claim(
            task_id,
            auction_epoch,
            self.robot_id,
            self.membership_epoch,
            claim_revision,
            fence_token,
            current_time_ms=now,
        )
        self._send(
            kind=self.TASK_CLAIM_KIND,
            payload={
                "task_id": task_id,
                "auction_epoch": auction_epoch,
                "winner_id": self.robot_id,
                "membership_epoch": self.membership_epoch,
                "claim_revision": claim_revision,
                "fence_token": fence_token,
            },
            current_time_ms=now,
        )

    def poll(self, *, current_time_ms: int | None = None) -> int:
        now = unix_time_ms() if current_time_ms is None else current_time_ms
        accepted = 0
        for message in self._transport.receive(self.robot_id):
            bids_before = dict(self._bid_records)
            claimed_before = dict(self._claimed_tasks)
            completed_before = dict(self._completed_tasks)
            intents_before = dict(self._peer_intents)
            intent_sent_before = dict(self._peer_intent_sent_ms)
            intent_deadlines_before = dict(self._intent_deadlines_ms)
            liveness_before = dict(self._liveness_deadlines_ms)
            try:
                self._guard.validate(message, current_tick=now)
                expected_boot = self._members.get(message.sender_id)
                if expected_boot != message.boot_id:
                    raise DistributedProtocolError(
                        "sender boot identity is outside current membership"
                    )
                self._apply_message(message, current_time_ms=now)
                self._guard.accept(message, current_tick=now)
                deadline = min(
                    message.sent_tick + message.ttl_ticks,
                    now + message.ttl_ticks,
                )
                self._liveness_deadlines_ms[message.sender_id] = max(
                    deadline,
                    self._liveness_deadlines_ms.get(message.sender_id, -1),
                )
                self.events.append(
                    DistributedEvent(now, "accepted", message.sender_id, message.kind)
                )
                accepted += 1
            except (
                MessageRejected,
                AuctionProtocolError,
                DistributedProtocolError,
                MembershipError,
            ) as error:
                self._bid_records = bids_before
                self._claimed_tasks = claimed_before
                self._completed_tasks = completed_before
                self._peer_intents = intents_before
                self._peer_intent_sent_ms = intent_sent_before
                self._intent_deadlines_ms = intent_deadlines_before
                self._liveness_deadlines_ms = liveness_before
                self.events.append(
                    DistributedEvent(now, "rejected", message.sender_id, str(error))
                )
        return accepted

    def fresh_intents(
        self,
        *,
        current_time_ms: int | None = None,
        include_local: bool = False,
    ) -> tuple[RobotIntent, ...]:
        now = unix_time_ms() if current_time_ms is None else current_time_ms
        return tuple(
            sorted(
                (
                    intent
                    for robot_id, intent in self._peer_intents.items()
                    if robot_id in self._members
                    and self._intent_deadlines_ms.get(robot_id, -1) >= now
                    and (include_local or robot_id != self.robot_id)
                ),
                key=lambda item: item.robot_id,
            )
        )

    def intent_conflicts(
        self, *, current_time_ms: int | None = None
    ) -> tuple[IntentConflict, ...]:
        now = unix_time_ms() if current_time_ms is None else current_time_ms
        local = self._peer_intents.get(self.robot_id)
        local_sent = self._peer_intent_sent_ms.get(self.robot_id)
        if local is None or local_sent is None:
            return ()
        conflicts: list[IntentConflict] = []
        for peer in self.fresh_intents(current_time_ms=now):
            peer_sent = self._peer_intent_sent_ms[peer.robot_id]
            conflict = _first_intent_conflict(local, local_sent, peer, peer_sent)
            if conflict is not None:
                conflicts.append(conflict)
        return tuple(sorted(conflicts, key=lambda item: (item.starts_at_ms, item.peer_id)))

    def has_fresh_membership(self, *, current_time_ms: int | None = None) -> bool:
        now = unix_time_ms() if current_time_ms is None else current_time_ms
        live = {
            robot_id
            for robot_id, deadline in self._liveness_deadlines_ms.items()
            if robot_id in self._members and deadline >= now
        }
        return self.is_active_member and live == set(self._members)

    def records_for(self, task_id: str, auction_epoch: int) -> tuple[BidRecord, ...]:
        return tuple(
            sorted(
                (
                    record
                    for key, record in self._bid_records.items()
                    if key[0] == task_id and key[1] == auction_epoch
                    and record.robot_id in self._members
                ),
                key=lambda item: item.robot_id,
            )
        )

    def has_complete_bid_view(self, task_id: str, auction_epoch: int) -> bool:
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

    def claim_candidate(
        self,
        task_id: str,
        auction_epoch: int,
        *,
        current_time_ms: int | None = None,
    ) -> Bid | None:
        if not self.is_active_member:
            return None
        if not self.has_complete_bid_view(task_id, auction_epoch):
            return None
        if not self.has_fresh_membership(current_time_ms=current_time_ms):
            return None
        return self.local_winner(task_id, auction_epoch)

    def task_completed(self, task_id: str, auction_epoch: int) -> bool:
        return (task_id, auction_epoch) in self._completed_tasks

    def task_claimed(self, task_id: str, auction_epoch: int) -> bool:
        record = self._claimed_tasks.get((task_id, auction_epoch))
        return record is not None and record.membership_epoch == self.membership_epoch

    def claim_winner(self, task_id: str, auction_epoch: int) -> str | None:
        record = self._claimed_tasks.get((task_id, auction_epoch))
        if record is None or record.membership_epoch != self.membership_epoch:
            return None
        return record.winner_id

    def claim_fence_token(self, task_id: str, auction_epoch: int) -> int | None:
        record = self._claimed_tasks.get((task_id, auction_epoch))
        if record is None or record.membership_epoch != self.membership_epoch:
            return None
        return record.fence_token

    def completion_winner(self, task_id: str, auction_epoch: int) -> str | None:
        record = self._completed_tasks.get((task_id, auction_epoch))
        return None if record is None else record.winner_id

    def close(self) -> None:
        self._transport.close()

    def _send(
        self, *, kind: str, payload: Mapping[str, Any], current_time_ms: int
    ) -> None:
        self._require_active()
        if self._send_sequence >= self._sequence_limit:
            self._sequence_limit = (
                self._send_sequence + self.SEQUENCE_RESERVATION_SIZE
            )
            self._persist_state()
        message = MessageEnvelope.create(
            kind=kind,
            sender_id=self.robot_id,
            boot_id=self.boot_id,
            sequence=self._send_sequence,
            sent_tick=current_time_ms,
            ttl_ticks=self._ttl_ms,
            map_version=self._map_version,
            payload=payload,
            signing_key=self._authentication_keys[self.robot_id],
        )
        self._send_sequence += 1
        self._transport.send(message, self._neighbors)
        self._liveness_deadlines_ms[self.robot_id] = current_time_ms + self._ttl_ms
        self.events.append(
            DistributedEvent(current_time_ms, "sent", self.robot_id, kind)
        )

    def _apply_message(
        self, message: MessageEnvelope, *, current_time_ms: int
    ) -> None:
        if message.kind == self.HEARTBEAT_KIND:
            required = {
                "robot_id",
                "boot_id",
                "membership_epoch",
                "membership_digest",
            }
            if set(message.payload) != required:
                raise DistributedProtocolError("heartbeat identity mismatch")
            if (
                message.payload["robot_id"] != message.sender_id
                or message.payload["boot_id"] != message.boot_id
            ):
                raise DistributedProtocolError("heartbeat identity mismatch")
            remote_epoch = message.payload["membership_epoch"]
            remote_digest = message.payload["membership_digest"]
            if (
                isinstance(remote_epoch, bool)
                or not isinstance(remote_epoch, int)
                or remote_epoch < 0
                or not isinstance(remote_digest, str)
                or not remote_digest
            ):
                raise DistributedProtocolError("heartbeat membership is invalid")
            if remote_epoch < self.membership_epoch:
                raise DistributedProtocolError("heartbeat membership epoch is stale")
            if remote_epoch == self.membership_epoch:
                if remote_digest != self.membership_digest:
                    raise DistributedProtocolError("membership digest disagreement")
            else:
                self._higher_epoch_observed = True
                self.events.append(
                    DistributedEvent(
                        current_time_ms,
                        "higher_epoch_observed",
                        message.sender_id,
                        str(remote_epoch),
                    )
                )
            return
        if message.kind == self.MEMBERSHIP_VOTE_KIND:
            vote = MembershipVote.from_mapping(message.payload)
            if vote.voter_id != message.sender_id:
                raise DistributedProtocolError("membership vote origin mismatch")
            installed = self._membership.merge(vote)
            self._persist_state()
            if installed is not None:
                self._activate_membership_view(current_time_ms=current_time_ms)
            return
        if message.kind == self.INTENT_KIND:
            intent = RobotIntent.from_payload(message.payload)
            if (
                intent.robot_id != message.sender_id
                or intent.boot_id != message.boot_id
            ):
                raise DistributedProtocolError("intent origin mismatch")
            existing = self._peer_intents.get(intent.robot_id)
            if existing is not None:
                if intent.revision < existing.revision:
                    return
                if intent.revision == existing.revision and intent != existing:
                    raise DistributedProtocolError(
                        "intent equivocation at the same revision"
                    )
            self._peer_intents[intent.robot_id] = intent
            self._peer_intent_sent_ms[intent.robot_id] = message.sent_tick
            self._intent_deadlines_ms[intent.robot_id] = min(
                message.sent_tick + message.ttl_ticks,
                current_time_ms + message.ttl_ticks,
            )
            return
        if message.kind == self.BID_KIND:
            records = message.payload.get("records")
            if not isinstance(records, list) or set(message.payload) != {"records"}:
                raise DistributedProtocolError("bid gossip payload is invalid")
            for raw in records:
                self._merge_bid(
                    parse_bid_record(raw), current_time_ms=current_time_ms
                )
            return
        if message.kind == self.TASK_CLAIM_KIND:
            required = {
                "task_id",
                "auction_epoch",
                "winner_id",
                "membership_epoch",
                "claim_revision",
                "fence_token",
            }
            if set(message.payload) != required:
                raise DistributedProtocolError("task claim payload is invalid")
            task_id = message.payload["task_id"]
            epoch = message.payload["auction_epoch"]
            winner_id = message.payload["winner_id"]
            membership_epoch = message.payload["membership_epoch"]
            revision = message.payload["claim_revision"]
            fence_token = message.payload["fence_token"]
            if (
                not isinstance(task_id, str)
                or not task_id
                or isinstance(epoch, bool)
                or not isinstance(epoch, int)
                or epoch < 0
                or winner_id != message.sender_id
                or isinstance(membership_epoch, bool)
                or not isinstance(membership_epoch, int)
                or membership_epoch < 0
                or isinstance(revision, bool)
                or not isinstance(revision, int)
                or revision < 0
                or isinstance(fence_token, bool)
                or not isinstance(fence_token, int)
                or fence_token < 0
            ):
                raise DistributedProtocolError("task claim fields are invalid")
            self._merge_task_claim(
                task_id,
                epoch,
                winner_id,
                membership_epoch,
                revision,
                fence_token,
                current_time_ms=current_time_ms,
            )
            return
        if message.kind == self.TASK_DONE_KIND:
            required = {
                "task_id",
                "auction_epoch",
                "winner_id",
                "membership_epoch",
                "completion_revision",
                "fence_token",
            }
            if set(message.payload) != required:
                raise DistributedProtocolError("task completion payload is invalid")
            task_id = message.payload["task_id"]
            epoch = message.payload["auction_epoch"]
            winner_id = message.payload["winner_id"]
            membership_epoch = message.payload["membership_epoch"]
            revision = message.payload["completion_revision"]
            fence_token = message.payload["fence_token"]
            if (
                not isinstance(task_id, str)
                or not task_id
                or isinstance(epoch, bool)
                or not isinstance(epoch, int)
                or epoch < 0
                or winner_id != message.sender_id
                or isinstance(membership_epoch, bool)
                or not isinstance(membership_epoch, int)
                or membership_epoch < 0
                or isinstance(revision, bool)
                or not isinstance(revision, int)
                or revision < 0
                or isinstance(fence_token, bool)
                or not isinstance(fence_token, int)
                or fence_token < 0
            ):
                raise DistributedProtocolError("task completion fields are invalid")
            self._merge_task_done(
                task_id,
                epoch,
                winner_id,
                membership_epoch,
                revision,
                fence_token,
                current_time_ms=current_time_ms,
            )
            return
        raise DistributedProtocolError(f"unexpected message kind: {message.kind}")

    def _merge_task_claim(
        self,
        task_id: str,
        auction_epoch: int,
        winner_id: str,
        membership_epoch: int,
        revision: int,
        fence_token: int,
        *,
        current_time_ms: int,
    ) -> None:
        expected_boot = self._members.get(winner_id)
        if expected_boot is None:
            raise AuctionProtocolError("claim origin is outside membership")
        if membership_epoch != self.membership_epoch:
            raise DistributedProtocolError("claim membership epoch is not current")
        if fence_token != _fence_token(membership_epoch, auction_epoch, revision):
            raise DistributedProtocolError("claim fence token is invalid")
        key = (task_id, auction_epoch)
        existing = self._claimed_tasks.get(key)
        if existing is not None:
            if existing.fence_token > fence_token:
                return
            if existing.fence_token == fence_token and existing.winner_id != winner_id:
                raise DistributedProtocolError("task claim equivocation")
            if (
                existing.membership_epoch == membership_epoch
                and existing.winner_id != winner_id
            ):
                raise DistributedProtocolError("task claim winner changed within epoch")
            if existing.fence_token == fence_token:
                return
        self._claimed_tasks[key] = TaskClaimRecord(
            task_id,
            auction_epoch,
            winner_id,
            membership_epoch,
            revision,
            fence_token,
        )
        self._persist_state()
        self.events.append(
            DistributedEvent(
                current_time_ms,
                "task_claimed",
                winner_id,
                f"{task_id}:{auction_epoch}:{revision}",
            )
        )

    def _merge_task_done(
        self,
        task_id: str,
        auction_epoch: int,
        winner_id: str,
        membership_epoch: int,
        revision: int,
        fence_token: int,
        *,
        current_time_ms: int,
    ) -> None:
        expected_boot = self._members.get(winner_id)
        if expected_boot is None:
            raise AuctionProtocolError("completion origin is outside membership")
        key = (task_id, auction_epoch)
        claim = self._claimed_tasks.get(key)
        if (
            membership_epoch != self.membership_epoch
            or claim is None
            or claim.winner_id != winner_id
            or claim.membership_epoch != membership_epoch
            or claim.fence_token != fence_token
        ):
            raise DistributedProtocolError("completion does not match active fence")
        existing = self._completed_tasks.get(key)
        if existing is not None:
            if existing.fence_token > fence_token:
                return
            if existing.fence_token == fence_token and existing.winner_id != winner_id:
                raise DistributedProtocolError("task completion equivocation")
            if existing.fence_token == fence_token and revision <= existing.revision:
                return
        self._completed_tasks[key] = TaskCompletionRecord(
            task_id,
            auction_epoch,
            winner_id,
            membership_epoch,
            revision,
            fence_token,
        )
        self._persist_state()
        self.events.append(
            DistributedEvent(
                current_time_ms,
                "task_completed",
                winner_id,
                f"{task_id}:{auction_epoch}:{revision}",
            )
        )

    def _merge_bid(self, record: BidRecord, *, current_time_ms: int) -> None:
        expected_boot = self._members.get(record.robot_id)
        if expected_boot is None or expected_boot != record.boot_id:
            raise AuctionProtocolError("bid origin is outside current membership epoch")
        if record.auction_epoch < 0 or record.revision < 0 or record.workload < 0:
            raise AuctionProtocolError("negative auction fields are invalid")
        if not math.isfinite(record.score) or record.score < 0:
            raise AuctionProtocolError("bid score must be finite and non-negative")
        key = (record.task_id, record.auction_epoch, record.robot_id)
        existing = self._bid_records.get(key)
        if existing is not None:
            if record.revision < existing.revision:
                return
            if record.revision == existing.revision:
                if record != existing:
                    raise AuctionProtocolError("equivocation at the same bid revision")
                return
        self._bid_records[key] = record
        self.events.append(
            DistributedEvent(
                current_time_ms,
                "bid_merged",
                record.robot_id,
                f"{record.task_id}:{record.auction_epoch}:{record.revision}",
            )
        )

    def _activate_membership_view(self, *, current_time_ms: int | None = None) -> None:
        self._members = self._membership.current.member_map
        self._neighbors = tuple(
            sorted(robot_id for robot_id in self._members if robot_id != self.robot_id)
        )
        # Bids, intents, and liveness are evidence for exactly one membership
        # view. Reusing them after a view change can authorize a plan computed
        # against robots or positions that are no longer current.
        self._bid_records.clear()
        self._peer_intents.clear()
        self._peer_intent_sent_ms.clear()
        self._intent_deadlines_ms.clear()
        self._liveness_deadlines_ms.clear()
        self._higher_epoch_observed = False
        now = unix_time_ms() if current_time_ms is None else current_time_ms
        self.events.append(
            DistributedEvent(
                now,
                "membership_installed",
                self.robot_id,
                f"{self.membership_epoch}:{self.membership_digest}",
            )
        )
        self._persist_state()

    def _require_active(self) -> None:
        if not self.is_active_member:
            raise DistributedProtocolError(
                "local robot is fenced by membership reconciliation"
            )

    def _persist_state(self) -> None:
        if self._state_store is None:
            return
        self._state_store.save(
            {
                "schema_version": "1.1",
                "robot_id": self.robot_id,
                "boot_id": self.boot_id,
                "map_version": self._map_version,
                "deployment_id": self._deployment_id,
                "sequence_limit": self._sequence_limit,
                "revision_limits": dict(sorted(self._revision_limits.items())),
                "membership_history": [
                    view.to_mapping() for view in self._membership.history
                ],
                "membership_votes": [
                    vote.to_mapping() for vote in self._membership.votes
                ],
                "task_claims": [
                    asdict(record)
                    for record in sorted(
                        self._claimed_tasks.values(),
                        key=lambda item: (item.task_id, item.auction_epoch),
                    )
                ],
                "task_completions": [
                    asdict(record)
                    for record in sorted(
                        self._completed_tasks.values(),
                        key=lambda item: (item.task_id, item.auction_epoch),
                    )
                ],
            }
        )

    def _restore_state(self) -> None:
        if self._state_store is None:
            return
        raw = self._state_store.load()
        if raw is None:
            return
        required = {
            "schema_version",
            "robot_id",
            "boot_id",
            "map_version",
            "deployment_id",
            "sequence_limit",
            "revision_limits",
            "membership_history",
            "membership_votes",
            "task_claims",
            "task_completions",
        }
        if set(raw) != required or raw["schema_version"] != "1.1":
            raise DistributedProtocolError("persisted peer state schema is invalid")
        if raw["robot_id"] != self.robot_id or raw["boot_id"] != self.boot_id:
            raise DistributedProtocolError("persisted peer identity does not match")
        if (
            raw["map_version"] != self._map_version
            or raw["deployment_id"] != self._deployment_id
        ):
            raise DistributedProtocolError("persisted deployment identity does not match")
        sequence_limit = raw["sequence_limit"]
        if (
            isinstance(sequence_limit, bool)
            or not isinstance(sequence_limit, int)
            or sequence_limit < 0
        ):
            raise DistributedProtocolError("persisted sequence limit is invalid")
        revision_limits = raw["revision_limits"]
        if (
            not isinstance(revision_limits, dict)
            or set(revision_limits) != self.REVISION_STREAMS
            or any(
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
                for value in revision_limits.values()
            )
        ):
            raise DistributedProtocolError("persisted revision limits are invalid")
        history_raw = raw["membership_history"]
        votes_raw = raw["membership_votes"]
        claims_raw = raw["task_claims"]
        completions_raw = raw["task_completions"]
        if not all(
            isinstance(item, list)
            for item in (history_raw, votes_raw, claims_raw, completions_raw)
        ):
            raise DistributedProtocolError("persisted peer collections are invalid")
        history = tuple(MembershipView.from_mapping(item) for item in history_raw)
        votes = tuple(MembershipVote.from_mapping(item) for item in votes_raw)
        self._membership.restore(history, votes)
        views_by_epoch = {
            view.epoch: view.member_map for view in self._membership.history
        }
        self._sequence_limit = sequence_limit
        self._send_sequence = sequence_limit
        self._revision_limits = dict(revision_limits)
        self._revision_next = dict(revision_limits)
        self._claimed_tasks = {}
        for item in claims_raw:
            record = _parse_claim_record(item)
            key = (record.task_id, record.auction_epoch)
            if key in self._claimed_tasks:
                raise DistributedProtocolError("persisted task claim is duplicated")
            claim_members = views_by_epoch.get(record.membership_epoch)
            if claim_members is None or record.winner_id not in claim_members:
                raise DistributedProtocolError(
                    "persisted claim winner is outside its membership view"
                )
            self._claimed_tasks[key] = record
        self._completed_tasks = {}
        for item in completions_raw:
            record = _parse_completion_record(item)
            key = (record.task_id, record.auction_epoch)
            if key in self._completed_tasks:
                raise DistributedProtocolError("persisted task completion is duplicated")
            claim = self._claimed_tasks.get(key)
            if (
                claim is None
                or claim.winner_id != record.winner_id
                or claim.membership_epoch != record.membership_epoch
                or claim.fence_token != record.fence_token
            ):
                raise DistributedProtocolError(
                    "persisted completion does not match a fenced claim"
                )
            self._completed_tasks[key] = record
        pending_votes = [
            vote
            for vote in votes
            if vote.voter_id == self.robot_id
            and vote.view.epoch in {
                self.membership_epoch,
                self.membership_epoch + 1,
            }
        ]
        self._local_membership_vote = pending_votes[-1] if pending_votes else None


def _fence_token(membership_epoch: int, auction_epoch: int, revision: int) -> int:
    if membership_epoch < 0 or auction_epoch < 0 or revision < 0:
        raise ValueError("fence token components must be non-negative")
    return (membership_epoch << 96) | (auction_epoch << 32) | revision


def _parse_claim_record(raw: Any) -> TaskClaimRecord:
    required = {
        "task_id",
        "auction_epoch",
        "winner_id",
        "membership_epoch",
        "revision",
        "fence_token",
    }
    if not isinstance(raw, dict) or set(raw) != required:
        raise DistributedProtocolError("persisted task claim schema is invalid")
    if not all(
        isinstance(raw[field], str) and raw[field]
        for field in ("task_id", "winner_id")
    ) or not all(
        not isinstance(raw[field], bool)
        and isinstance(raw[field], int)
        and raw[field] >= 0
        for field in (
            "auction_epoch",
            "membership_epoch",
            "revision",
            "fence_token",
        )
    ):
        raise DistributedProtocolError("persisted task claim is invalid")
    record = TaskClaimRecord(**raw)
    if (
        not record.task_id
        or not record.winner_id
        or record.auction_epoch < 0
        or record.membership_epoch < 0
        or record.revision < 0
        or record.fence_token
        != _fence_token(record.membership_epoch, record.auction_epoch, record.revision)
    ):
        raise DistributedProtocolError("persisted task claim is invalid")
    return record


def _parse_completion_record(raw: Any) -> TaskCompletionRecord:
    required = {
        "task_id",
        "auction_epoch",
        "winner_id",
        "membership_epoch",
        "revision",
        "fence_token",
    }
    if not isinstance(raw, dict) or set(raw) != required:
        raise DistributedProtocolError("persisted completion schema is invalid")
    if not all(
        isinstance(raw[field], str) and raw[field]
        for field in ("task_id", "winner_id")
    ) or not all(
        not isinstance(raw[field], bool)
        and isinstance(raw[field], int)
        and raw[field] >= 0
        for field in (
            "auction_epoch",
            "membership_epoch",
            "revision",
            "fence_token",
        )
    ):
        raise DistributedProtocolError("persisted task completion is invalid")
    record = TaskCompletionRecord(**raw)
    if (
        not record.task_id
        or not record.winner_id
        or record.auction_epoch < 0
        or record.membership_epoch < 0
        or record.revision < 0
        or record.fence_token < 0
    ):
        raise DistributedProtocolError("persisted task completion is invalid")
    return record


def _parse_path(raw: Any) -> list[Any]:
    if not isinstance(raw, list) or not 1 <= len(raw) <= 64:
        raise DistributedProtocolError("intent path must contain 1 to 64 cells")
    return raw


def _parse_cell(raw: Any) -> Cell:
    if not isinstance(raw, dict) or set(raw) != {"x", "y"}:
        raise DistributedProtocolError("cell fields do not match schema")
    if any(isinstance(raw[field], bool) or not isinstance(raw[field], int) for field in raw):
        raise DistributedProtocolError("cell coordinates must be integers")
    return Cell(raw["x"], raw["y"])


def _first_intent_conflict(
    local: RobotIntent,
    local_sent_ms: int,
    peer: RobotIntent,
    peer_sent_ms: int,
) -> IntentConflict | None:
    for local_index, local_cell in enumerate(local.path):
        local_start = local_sent_ms + local_index * local.step_duration_ms
        local_end = local_start + local.step_duration_ms
        for peer_index, peer_cell in enumerate(peer.path):
            peer_start = peer_sent_ms + peer_index * peer.step_duration_ms
            peer_end = peer_start + peer.step_duration_ms
            overlap_start = max(local_start, peer_start)
            overlap_end = min(local_end, peer_end)
            if local_cell == peer_cell and overlap_start < overlap_end:
                return IntentConflict(
                    peer.robot_id,
                    "vertex",
                    overlap_start,
                    overlap_end,
                    local_cell,
                    local_cell,
                )
    for local_index, (local_from, local_to) in enumerate(
        zip(local.path, local.path[1:], strict=False)
    ):
        local_start = local_sent_ms + local_index * local.step_duration_ms
        local_end = local_start + local.step_duration_ms
        for peer_index, (peer_from, peer_to) in enumerate(
            zip(peer.path, peer.path[1:], strict=False)
        ):
            peer_start = peer_sent_ms + peer_index * peer.step_duration_ms
            peer_end = peer_start + peer.step_duration_ms
            overlap_start = max(local_start, peer_start)
            overlap_end = min(local_end, peer_end)
            if (
                local_from == peer_to
                and local_to == peer_from
                and local_from != local_to
                and overlap_start < overlap_end
            ):
                return IntentConflict(
                    peer.robot_id,
                    "reverse_edge",
                    overlap_start,
                    overlap_end,
                    local_from,
                    local_to,
                )
    return None
