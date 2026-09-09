"""ROS 2/DDS adapter for one independent SwarmRoute robot peer.

The node owns only the replica for its namespace.  It publishes authenticated
intent, liveness, bids, and completion facts on a shared DDS topic; DDS fan-out
is the data plane, not a broker or a coordinator.  Gazebo is used only for
odometry and actuation through the existing per-robot route executor.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import threading
from collections import deque
from pathlib import Path

import rclpy
from geometry_msgs.msg import PoseStamped
from nav_msgs.msg import Odometry, Path as PathMessage
from rclpy.clock import ClockType
from rclpy.duration import Duration
from rclpy.node import Node
from rclpy.qos import (
    DurabilityPolicy,
    HistoryPolicy,
    QoSProfile,
    ReliabilityPolicy,
    qos_profile_sensor_data,
)
from rclpy.time import Time
from std_msgs.msg import Bool, Int64, String

from swarmroute.allocation import Bid, BidComponents, Bidder
from swarmroute.distributed import DistributedRobotNode, RobotIntent, unix_time_ms
from swarmroute.domain import Cell, Plan, RobotState, Task
from swarmroute.durable import JsonPeerStateStore
from swarmroute.physics import MotionConfig
from swarmroute.planner import SpaceTimeAStar
from swarmroute.protocol import MessageEnvelope, MessageRejected
from swarmroute.reservations import ReservationTable
from swarmroute.scenario import load_scenario


class RosPeerTransport:
    """PeerTransport implementation over one ROS 2 DDS topic.

    DDS discovery and delivery are peer-to-peer (or multicast) between robot
    processes.  The topic is only a typed fan-out surface; no process receives
    or forwards another robot's state.  The envelope remains HMAC-authenticated
    so a valid ROS graph connection cannot forge a robot identity.
    """

    def __init__(self, node: Node, local_id: str, topic: str, ttl_ms: int) -> None:
        self._local_id = local_id
        self._messages: deque[MessageEnvelope] = deque()
        self._lock = threading.Lock()
        qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=128,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.VOLATILE,
            lifespan=Duration(nanoseconds=int(ttl_ms * 1_000_000 * 1.5)),
        )
        self._publisher = node.create_publisher(String, topic, qos)
        self._subscription = node.create_subscription(
            String, topic, self._on_message, qos
        )

    def send(
        self, message: MessageEnvelope, recipients: tuple[str, ...] | list[str]
    ) -> None:
        if message.sender_id != self._local_id:
            raise ValueError("transport may send only the local robot's messages")
        if not recipients:
            raise ValueError("distributed transport requires at least one peer")
        outgoing = String()
        outgoing.data = base64.b64encode(message.to_bytes()).decode("ascii")
        self._publisher.publish(outgoing)

    def receive(self, node_id: str) -> tuple[MessageEnvelope, ...]:
        if node_id != self._local_id:
            raise ValueError("transport may receive only for its local robot")
        with self._lock:
            messages = tuple(self._messages)
            self._messages.clear()
        return messages

    def close(self) -> None:
        # ROS owns the publisher/subscription lifetime; this hook satisfies the
        # core transport contract and keeps shutdown idempotent.
        return None

    def _on_message(self, message: String) -> None:
        try:
            raw = base64.b64decode(message.data.encode("ascii"), validate=True)
            envelope = MessageEnvelope.from_bytes(raw)
        except (ValueError, UnicodeError, MessageRejected):
            return
        if envelope.sender_id == self._local_id:
            return
        with self._lock:
            self._messages.append(envelope)


class PeerNode(Node):
    """One robot's local auction, intent arbitration, and route publisher."""

    def __init__(self) -> None:
        super().__init__("peer")
        scenario_value = str(self.declare_parameter("scenario", "").value)
        if not scenario_value:
            raise ValueError("the scenario parameter is required")
        scenario_path = Path(scenario_value)
        scenario_digest = hashlib.sha256(scenario_path.read_bytes()).hexdigest()
        self._scenario = load_scenario(scenario_path)
        namespace_robot_id = self.get_namespace().strip("/")
        self._robot_id = str(
            self.declare_parameter("robot_id", namespace_robot_id).value
        )
        self._resolution = float(
            self.declare_parameter("cell_resolution", 1.5).value
        )
        self._grid_origin_x = float(
            self.declare_parameter("grid_origin_x", -15.0).value
        )
        self._grid_origin_y = float(
            self.declare_parameter("grid_origin_y", -9.0).value
        )
        self._robot_origin_x = float(
            self.declare_parameter("world_origin_x", 0.0).value
        )
        self._robot_origin_y = float(
            self.declare_parameter("world_origin_y", 0.0).value
        )
        self._robot_origin_yaw = float(
            self.declare_parameter("world_origin_yaw", 0.0).value
        )
        self._tick_seconds = float(
            self.declare_parameter("tick_seconds", 5.0).value
        )
        max_ticks = int(self.declare_parameter("max_ticks", 360).value)
        ttl_ms = int(self.declare_parameter("message_ttl_ms", 1_000).value)
        skew_ms = int(
            self.declare_parameter("maximum_clock_skew_ms", 1_000).value
        )
        heartbeat_period = float(
            self.declare_parameter("heartbeat_period_seconds", 0.25).value
        )
        intent_period = float(
            self.declare_parameter("intent_period_seconds", 0.20).value
        )
        membership_grace_seconds = float(
            self.declare_parameter(
                "membership_reconfiguration_grace_seconds", 5.0
            ).value
        )
        state_directory = Path(
            str(self.declare_parameter("state_directory", "/tmp/swarmroute-state").value)
        )
        if self._resolution <= 0 or self._tick_seconds <= 0:
            raise ValueError("cell_resolution and tick_seconds must be positive")
        if (
            ttl_ms <= 0
            or heartbeat_period <= 0
            or intent_period <= 0
            or membership_grace_seconds <= 0
        ):
            raise ValueError("peer timing parameters must be positive")
        self._membership_grace_ms = int(membership_grace_seconds * 1_000)

        robot = next(
            (item for item in self._scenario.robots if item.robot_id == self._robot_id),
            None,
        )
        if robot is None:
            raise ValueError(f"robot_id {self._robot_id!r} is not in the scenario")
        self._robot = robot
        self._members = {
            item.robot_id: f"{item.boot_id}:{item.robot_id}"
            for item in self._scenario.robots
        }
        self._keys = {
            item.robot_id: hashlib.sha256(
                f"swarmroute-research:{self._scenario.seed}:{item.robot_id}".encode()
            ).digest()
            for item in self._scenario.robots
        }
        neighbors = tuple(
            item.robot_id
            for item in self._scenario.robots
            if item.robot_id != self._robot_id
        )
        self._transport = RosPeerTransport(
            self, self._robot_id, "/swarmroute/peer_bus", ttl_ms
        )
        self._peer = DistributedRobotNode(
            robot_id=self._robot_id,
            boot_id=self._members[self._robot_id],
            members=self._members,
            authentication_keys=self._keys,
            map_version=self._scenario.warehouse_map.version,
            transport=self._transport,
            neighbors=neighbors,
            message_ttl_ms=ttl_ms,
            maximum_clock_skew_ms=skew_ms,
            state_store=JsonPeerStateStore(
                state_directory / f"{scenario_digest[:16]}-{self._robot_id}.json"
            ),
            deployment_id=scenario_digest,
        )
        self._reservations = ReservationTable()
        self._motion = MotionConfig(
            cell_size_m=self._resolution,
            tick_seconds=self._tick_seconds,
        )
        self._planner = SpaceTimeAStar(
            self._scenario.warehouse_map,
            self._reservations,
            move_ticks=self._motion.move_ticks,
        )
        self._bidder = Bidder(
            self._planner,
            self._reservations,
            motion=self._motion,
            planning_horizon_ticks=max_ticks,
        )
        self._tasks = tuple(
            sorted(self._scenario.tasks, key=lambda task: (task.release_tick, task.task_id))
        )
        self._cell = robot.cell
        self._battery_soc = robot.battery_soc
        # Gazebo's ROS clock starts at zero.  Using that shared epoch keeps
        # independent peers' tick-to-wall conversions aligned even though the
        # launch system starts their processes a few milliseconds apart.
        self._schedule_epoch = Time(
            nanoseconds=0, clock_type=ClockType.ROS_TIME
        )
        self._task_index = 0
        self._current_epoch: int | None = None
        self._candidate_task: Task | None = None
        self._candidate_plan: Plan | None = None
        self._current_task: Task | None = None
        self._current_plan: Plan | None = None
        self._current_bid: Bid | None = None
        self._local_bids: dict[tuple[str, int], Bid] = {}
        self._intent_announced_ms = 0
        self._yield_until_ms = 0
        self._received_odometry = False
        self._observed_membership_epoch = self._peer.membership_epoch
        self._stale_view_since_ms: int | None = None
        self._stale_view_signature: tuple[str, ...] | None = None
        self._last_membership_proposal: tuple[int, tuple[str, ...]] | None = None
        self._stop_route_active = False
        self._recovery_claims_reported: set[tuple[str, int]] = set()

        route_qos = QoSProfile(
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.VOLATILE,
        )
        self._route_publisher = self.create_publisher(PathMessage, "route", route_qos)
        self._authority_publisher = self.create_publisher(Bool, "authority_lease", 10)
        self._progress_subscription = self.create_subscription(
            Int64, "progress", self._on_progress, 10
        )
        self._odometry_subscription = self.create_subscription(
            Odometry,
            "odometry",
            self._on_odometry,
            qos_profile_sensor_data,
        )
        self._event_publisher = self.create_publisher(String, "/swarmroute/events", 100)
        if self._peer.is_active_member:
            self._peer.publish_heartbeat()
            self._publish_authority(
                self._peer.has_live_quorum(current_time_ms=unix_time_ms())
            )
            self._publish_intent(mode="idle")
        else:
            self._publish_authority(False)
            self._publish_stop_route("restored_peer_is_fenced")
        self._heartbeat_timer = self.create_wall_timer(
            heartbeat_period, self._publish_heartbeat
        )
        self._intent_timer = self.create_wall_timer(
            intent_period, self._publish_periodic_intent
        )
        self._tick_timer = self.create_wall_timer(0.10, self._tick)
        self.get_logger().info(
            f"{self._robot_id}: distributed peer started; members={len(self._members)}"
        )

    def _tick(self) -> None:
        now_ms = unix_time_ms()
        self._peer.poll(current_time_ms=now_ms)
        self._handle_membership_transition()
        if not self._peer.is_active_member:
            self._publish_authority(False)
            self._publish_stop_route("membership_fenced")
            return
        self._maybe_reconfigure_membership(now_ms)
        current_tick = self._current_tick()
        self._advance_completed_tasks()
        self._auction(current_tick, now_ms)
        if self._candidate_plan is not None:
            self._try_commit(now_ms)

    def _auction(self, current_tick: int, now_ms: int) -> None:
        if not self._peer.is_active_member:
            return
        if self._task_index >= len(self._tasks):
            return
        task = self._tasks[self._task_index]
        epoch = self._task_index
        if current_tick < task.release_tick:
            return
        known_claim = self._peer.claim_winner(task.task_id, epoch)
        if known_claim is not None:
            if known_claim != self._robot_id:
                self._task_index += 1
            elif self._current_plan is None:
                key = (task.task_id, epoch)
                self._publish_stop_route("restart_reconciliation_required")
                if key not in self._recovery_claims_reported:
                    self._recovery_claims_reported.add(key)
                    self._publish_event(
                        "recovery_blocked",
                        task.task_id,
                        {
                            "reason": "durable claim exists but execution state is unknown",
                            "fence_token": self._peer.claim_fence_token(
                                task.task_id, epoch
                            ),
                        },
                    )
            return
        key = (task.task_id, epoch)
        if key not in self._local_bids:
            completed_tasks = (
                self._robot.completed_tasks
                + self._peer.completed_task_count(self._robot_id)
            )
            if self._current_plan is not None or self._candidate_plan is not None:
                bid = Bid(
                    robot_id=self._robot_id,
                    task_id=task.task_id,
                    auction_epoch=epoch,
                    feasible=False,
                    score=0.0,
                    components=BidComponents(0.0, 0.0, 0.0, 0.0),
                    expected_finish_tick=None,
                    expected_soc=None,
                    workload=completed_tasks,
                    reason="robot already has an active assignment",
                )
            else:
                state = RobotState(
                    robot_id=self._robot_id,
                    cell=self._cell,
                    battery_soc=self._battery_soc,
                    available_tick=current_tick,
                    completed_tasks=completed_tasks,
                    boot_id=self._robot.boot_id,
                    payload_capacity_kg=self._robot.payload_capacity_kg,
                    reserve_soc=self._robot.reserve_soc,
                )
                bid = self._bidder.bid(
                    state, task, current_tick=current_tick, auction_epoch=epoch
                )
            self._local_bids[key] = bid
            self._peer.publish_bid(
                bid,
                revision=self._peer.next_local_revision("bid"),
                current_time_ms=now_ms,
            )
            self._publish_event(
                "bid_published", task.task_id, {"feasible": bid.feasible}
            )
            return
        candidate = self._peer.claim_candidate(
            task.task_id, epoch, current_time_ms=now_ms
        )
        if candidate is None:
            return
        if candidate.robot_id != self._robot_id:
            return
        if self._candidate_plan is None:
            local_bid = self._local_bids[key]
            if local_bid.execution_plan is None:
                return
            self._candidate_task = task
            self._candidate_plan = local_bid.execution_plan
            self._current_bid = local_bid
            self._intent_announced_ms = 0
            self._publish_event("intent_proposed", task.task_id, {})

    def _try_commit(self, now_ms: int) -> None:
        if not self._peer.is_active_member:
            self._publish_stop_route("membership_fenced")
            return
        assert self._candidate_plan is not None
        assert self._candidate_task is not None
        if self._intent_announced_ms == 0:
            self._intent_announced_ms = now_ms
            return
        if now_ms - self._intent_announced_ms < 300:
            return
        if now_ms < self._yield_until_ms:
            return
        conflicts = self._peer.intent_conflicts(current_time_ms=now_ms)
        peer_modes = {
            intent.robot_id: intent.mode
            for intent in self._peer.fresh_intents(current_time_ms=now_ms)
        }
        blockers = [
            item
            for item in conflicts
            if peer_modes.get(item.peer_id) != "planning"
            or item.peer_id < self._robot_id
        ]
        if blockers:
            self._yield_until_ms = now_ms + 1_000
            self._publish_event(
                "intent_yielded",
                self._candidate_task.task_id,
                {"blocking_peer": min(item.peer_id for item in blockers)},
            )
            return
        self._current_task = self._candidate_task
        self._current_plan = self._candidate_plan
        self._current_epoch = self._task_index
        self._peer.publish_task_claim(
            self._current_task.task_id,
            self._current_epoch,
            claim_revision=self._peer.next_local_revision("claim"),
            current_time_ms=now_ms,
        )
        self._task_index += 1
        self._candidate_task = None
        self._candidate_plan = None
        self._publish_route(self._current_plan)
        self._stop_route_active = False
        self._publish_event(
            "route_committed",
            self._current_task.task_id,
            {"steps": len(self._current_plan.steps)},
        )

    def _publish_periodic_intent(self) -> None:
        if not self._peer.is_active_member:
            return
        if self._yield_until_ms > unix_time_ms() and self._current_plan is None:
            self._publish_intent(mode="safe_stop", path=(self._cell,))
        elif self._current_plan is not None:
            self._publish_intent(
                mode="moving", path=tuple(step.cell for step in self._current_plan.steps)
            )
        elif self._candidate_plan is not None:
            self._publish_intent(
                mode="planning", path=tuple(step.cell for step in self._candidate_plan.steps)
            )
        else:
            self._publish_intent(mode="idle", path=(self._cell,))

    def _publish_heartbeat(self) -> None:
        if not self._peer.is_active_member:
            self._publish_authority(False)
            return
        now_ms = unix_time_ms()
        self._peer.publish_heartbeat(current_time_ms=now_ms)
        self._peer.repeat_membership_vote(current_time_ms=now_ms)
        self._publish_authority(
            self._peer.has_live_quorum(current_time_ms=now_ms)
        )

    def _publish_authority(self, active: bool) -> None:
        message = Bool()
        message.data = active
        self._authority_publisher.publish(message)

    def _publish_intent(
        self, *, mode: str, path: tuple[Cell, ...] | None = None
    ) -> None:
        if not self._peer.is_active_member:
            return
        intent_revision = self._peer.next_local_revision("intent")
        task_id = None
        if self._current_task is not None:
            task_id = self._current_task.task_id
        elif self._candidate_task is not None:
            task_id = self._candidate_task.task_id
        cells = tuple(path or (self._cell,))
        if not cells:
            cells = (self._cell,)
        if cells[0] != self._cell:
            try:
                cells = cells[cells.index(self._cell) :]
            except ValueError:
                cells = (self._cell,)
        intent = RobotIntent(
            robot_id=self._robot_id,
            boot_id=self._members[self._robot_id],
            revision=intent_revision,
            plan_epoch=(
                self._current_epoch
                if self._current_plan is not None and self._current_epoch is not None
                else self._task_index
            ),
            step_duration_ms=max(1, int(self._tick_seconds * 1_000)),
            cell=self._cell,
            path=cells[:64],
            task_id=task_id,
            battery_soc=self._battery_soc,
            position_uncertainty_m=0.05 if self._received_odometry else 0.20,
            mode=mode,
        )
        self._peer.publish_intent(intent, current_time_ms=unix_time_ms())

    def _publish_route(self, plan: Plan) -> None:
        message = PathMessage()
        message.header.frame_id = "world"
        message.header.stamp = self.get_clock().now().to_msg()
        for step in plan.steps:
            pose = PoseStamped()
            pose.header.frame_id = "world"
            due = self._schedule_epoch + Duration(
                seconds=step.tick * self._tick_seconds
            )
            pose.header.stamp = due.to_msg()
            pose.pose.position.x = self._grid_origin_x + step.cell.x * self._resolution
            pose.pose.position.y = self._grid_origin_y + step.cell.y * self._resolution
            pose.pose.orientation.w = 1.0
            message.poses.append(pose)
        self._route_publisher.publish(message)

    def _publish_stop_route(self, reason: str) -> None:
        if self._stop_route_active:
            return
        message = PathMessage()
        message.header.frame_id = "world"
        message.header.stamp = self.get_clock().now().to_msg()
        self._route_publisher.publish(message)
        self._stop_route_active = True
        self._publish_event("route_revoked", None, {"reason": reason})

    def _handle_membership_transition(self) -> None:
        current_epoch = self._peer.membership_epoch
        if current_epoch == self._observed_membership_epoch:
            return
        previous_epoch = self._observed_membership_epoch
        self._observed_membership_epoch = current_epoch
        if self._current_epoch is not None:
            self._task_index = min(self._task_index, self._current_epoch)
        self._candidate_task = None
        self._candidate_plan = None
        self._current_task = None
        self._current_plan = None
        self._current_bid = None
        self._current_epoch = None
        self._local_bids.clear()
        self._stale_view_since_ms = None
        self._stale_view_signature = None
        self._last_membership_proposal = None
        self._publish_stop_route("membership_epoch_changed")
        self._publish_event(
            "membership_installed",
            None,
            {
                "previous_epoch": previous_epoch,
                "membership_epoch": current_epoch,
                "members": list(self._peer.active_members),
            },
        )

    def _maybe_reconfigure_membership(self, now_ms: int) -> None:
        active = set(self._peer.active_members)
        live = set(self._peer.live_members(current_time_ms=now_ms))
        if live == active:
            self._stale_view_since_ms = None
            self._stale_view_signature = None
            return
        if self._robot_id not in live or not self._peer.has_live_quorum(
            current_time_ms=now_ms
        ):
            self._stale_view_since_ms = None
            self._stale_view_signature = None
            return
        signature = tuple(sorted(live))
        if signature != self._stale_view_signature:
            self._stale_view_signature = signature
            self._stale_view_since_ms = now_ms
            return
        if (
            self._stale_view_since_ms is None
            or now_ms - self._stale_view_since_ms < self._membership_grace_ms
        ):
            return
        proposal = (self._peer.membership_epoch, signature)
        if proposal == self._last_membership_proposal:
            return
        self._peer.publish_membership_vote(frozenset(live), current_time_ms=now_ms)
        self._last_membership_proposal = proposal
        self._publish_event(
            "membership_vote",
            None,
            {"retained_members": list(signature)},
        )

    def _on_progress(self, message: Int64) -> None:
        if self._current_plan is None or self._current_task is None:
            return
        final_due = self._schedule_epoch + Duration(
            seconds=self._current_plan.end.tick * self._tick_seconds
        )
        if message.data < final_due.nanoseconds:
            return
        task = self._current_task
        self._peer.publish_task_done(
            task.task_id,
            self._current_epoch if self._current_epoch is not None else self._task_index,
            completion_revision=self._peer.next_local_revision("completion"),
            current_time_ms=unix_time_ms(),
        )
        self._cell = task.dropoff
        if self._current_bid is not None and self._current_bid.expected_soc is not None:
            self._battery_soc = max(self._robot.reserve_soc, self._current_bid.expected_soc)
        self._current_task = None
        self._current_plan = None
        self._current_bid = None
        self._current_epoch = None
        self._local_bids = {
            key: bid
            for key, bid in self._local_bids.items()
            if key[1] < self._task_index
        }
        self._publish_intent(mode="idle", path=(self._cell,))
        self._publish_event("task_completed", task.task_id, {})

    def _on_odometry(self, message: Odometry) -> None:
        local_x = message.pose.pose.position.x
        local_y = message.pose.pose.position.y
        cosine = math.cos(self._robot_origin_yaw)
        sine = math.sin(self._robot_origin_yaw)
        world_x = self._robot_origin_x + cosine * local_x - sine * local_y
        world_y = self._robot_origin_y + sine * local_x + cosine * local_y
        candidate = Cell(
            round((world_x - self._grid_origin_x) / self._resolution),
            round((world_y - self._grid_origin_y) / self._resolution),
        )
        if self._scenario.warehouse_map.traversable(candidate):
            self._cell = candidate
        self._received_odometry = True

    def _advance_completed_tasks(self) -> None:
        while self._task_index < len(self._tasks):
            task = self._tasks[self._task_index]
            if not self._peer.task_completed(task.task_id, self._task_index):
                break
            self._task_index += 1
            self._candidate_task = None
            self._candidate_plan = None

    def _current_tick(self) -> int:
        elapsed = (self.get_clock().now() - self._schedule_epoch).nanoseconds
        return max(0, math.floor(elapsed / (self._tick_seconds * 1e9)))

    def _publish_event(
        self, kind: str, task_id: str | None, values: dict[str, object]
    ) -> None:
        payload = {
            "kind": kind,
            "robot_id": self._robot_id,
            "task_id": task_id,
            "mode": "moving" if self._current_plan is not None else "idle",
            **values,
        }
        message = String()
        message.data = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        self._event_publisher.publish(message)


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = PeerNode()
    try:
        rclpy.spin(node)
    finally:
        node._peer.close()
        node.destroy_node()
        rclpy.shutdown()
