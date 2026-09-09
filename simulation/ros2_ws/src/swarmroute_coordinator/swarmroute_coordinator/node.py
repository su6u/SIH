from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import rclpy
from geometry_msgs.msg import PoseStamped
from nav_msgs.msg import Path as PathMessage
from rclpy.duration import Duration
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import Int64, String

from swarmroute.admission import AdmissionError, CellAdmission
from swarmroute.domain import PlanStep, RobotState
from swarmroute.fleet import FleetSimulation, RouteAssignment, SimulationConfig
from swarmroute.physics import MotionConfig
from swarmroute.runtime import replicated_auction_for
from swarmroute.scenario import load_scenario


@dataclass(frozen=True, slots=True)
class ScheduledStep:
    task_id: str
    robot_id: str
    assigned_tick: int
    finish_tick: int
    step: PlanStep


@dataclass(frozen=True, slots=True)
class InflightStep:
    scheduled: ScheduledStep
    token: int


class CoordinatorNode(Node):
    def __init__(self) -> None:
        super().__init__("coordinator")
        scenario_path = self.declare_parameter("scenario", "").value
        self._resolution = float(self.declare_parameter("cell_resolution", 1.5).value)
        self._origin_x = float(self.declare_parameter("origin_x", -15.0).value)
        self._origin_y = float(self.declare_parameter("origin_y", -9.0).value)
        self._tick_seconds = float(self.declare_parameter("tick_seconds", 5.0).value)
        max_ticks = int(self.declare_parameter("max_ticks", 180).value)
        if not scenario_path:
            raise ValueError("the scenario parameter is required")
        if self._resolution <= 0 or self._tick_seconds <= 0:
            raise ValueError("cell_resolution and tick_seconds must be positive")

        scenario = load_scenario(Path(scenario_path))
        result = FleetSimulation(
            scenario.warehouse_map,
            scenario.robots,
            config=SimulationConfig(
                max_ticks=max_ticks,
                planning_horizon_ticks=max_ticks,
                motion=MotionConfig(
                    cell_size_m=self._resolution,
                    tick_seconds=self._tick_seconds,
                ),
            ),
            auction=replicated_auction_for(scenario),
            conflict_zones=scenario.conflict_zones,
        ).run(scenario.tasks, scenario.interventions)
        self._steps = self._build_steps(result.assignments, scenario.robots)
        self._indices = {robot.robot_id: 0 for robot in scenario.robots}
        self._inflight: dict[str, InflightStep] = {}
        self._admission = CellAdmission(scenario.robots)
        route_qos = QoSProfile(
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.VOLATILE,
        )
        self._route_publishers = {
            robot.robot_id: self.create_publisher(
                PathMessage, f"/{robot.robot_id}/route", route_qos
            )
            for robot in scenario.robots
        }
        self._progress_subscriptions = [
            self.create_subscription(
                Int64,
                f"/{robot.robot_id}/progress",
                lambda message, robot_id=robot.robot_id: self._confirm_progress(
                    robot_id, message.data
                ),
                10,
            )
            for robot in scenario.robots
        ]
        self._event_publisher = self.create_publisher(String, "/swarmroute/events", 100)
        self._schedule_epoch = self.get_clock().now()
        self._last_dispatch_ns = {robot.robot_id: 0 for robot in scenario.robots}
        self._timer = self.create_timer(0.05, self._publish_admitted_steps)
        self.get_logger().info(
            f"loaded {len(result.assignments)} assignments for {len(scenario.robots)} robots"
        )

    @staticmethod
    def _build_steps(
        assignments: Iterable[RouteAssignment],
        robots: Iterable[RobotState],
    ) -> dict[str, tuple[ScheduledStep, ...]]:
        queues: dict[str, list[ScheduledStep]] = {
            robot.robot_id: [] for robot in robots
        }
        for assignment in sorted(
            assignments,
            key=lambda item: (item.assigned_tick, item.robot_id, item.task_id),
        ):
            queue = queues[assignment.robot_id]
            for step in assignment.plan.steps:
                if queue and queue[-1].step == step:
                    continue
                queue.append(
                    ScheduledStep(
                        assignment.task_id,
                        assignment.robot_id,
                        assignment.assigned_tick,
                        assignment.finish_tick,
                        step,
                    )
                )
        return {robot_id: tuple(queue) for robot_id, queue in queues.items()}

    def _publish_admitted_steps(self) -> None:
        now = self.get_clock().now()
        elapsed_seconds = (now - self._schedule_epoch).nanoseconds / 1e9
        current_tick = math.floor(max(0.0, elapsed_seconds) / self._tick_seconds)
        for robot_id in sorted(self._steps):
            if robot_id in self._inflight:
                if now.nanoseconds - self._last_dispatch_ns[robot_id] >= 500_000_000:
                    self._publish_path(self._inflight[robot_id])
                continue
            queue = self._steps[robot_id]
            index = self._indices[robot_id]
            while index < len(queue):
                scheduled = queue[index]
                if (
                    scheduled.assigned_tick > current_tick
                    or scheduled.step.tick > current_tick
                ):
                    break
                if scheduled.step.cell == self._admission.confirmed_cell(robot_id):
                    index += 1
                    self._indices[robot_id] = index
                    continue
                if not self._admission.can_enter(robot_id, scheduled.step.cell):
                    break
                self._dispatch(scheduled)
                break

    def _dispatch(self, scheduled: ScheduledStep) -> None:
        self._admission.reserve(scheduled.robot_id, scheduled.step.cell)
        due = self._schedule_epoch + Duration(
            seconds=scheduled.step.tick * self._tick_seconds
        )
        token = due.nanoseconds
        inflight = InflightStep(scheduled, token)
        self._inflight[scheduled.robot_id] = inflight
        self._publish_path(inflight)
        self._publish_event(
            "step_admitted",
            scheduled,
            {"step_tick": scheduled.step.tick, "token": token},
        )

    def _publish_path(self, inflight: InflightStep) -> None:
        scheduled = inflight.scheduled
        due = self._schedule_epoch + Duration(
            seconds=scheduled.step.tick * self._tick_seconds
        )
        message = PathMessage()
        message.header.frame_id = "world"
        message.header.stamp = self.get_clock().now().to_msg()
        pose = PoseStamped()
        pose.header.frame_id = "world"
        pose.header.stamp = due.to_msg()
        pose.pose.position.x = self._origin_x + scheduled.step.cell.x * self._resolution
        pose.pose.position.y = self._origin_y + scheduled.step.cell.y * self._resolution
        pose.pose.orientation.w = 1.0
        message.poses.append(pose)
        self._route_publishers[scheduled.robot_id].publish(message)
        self._last_dispatch_ns[scheduled.robot_id] = self.get_clock().now().nanoseconds

    def _confirm_progress(self, robot_id: str, token: int) -> None:
        inflight = self._inflight.get(robot_id)
        if inflight is None or inflight.token != token:
            self.get_logger().warning(
                f"ignored unexpected progress token from {robot_id}"
            )
            return
        try:
            self._admission.confirm(robot_id, inflight.scheduled.step.cell)
        except AdmissionError as error:
            self.get_logger().error(str(error))
            return
        self._indices[robot_id] += 1
        del self._inflight[robot_id]
        self._publish_event(
            "step_confirmed",
            inflight.scheduled,
            {"step_tick": inflight.scheduled.step.tick, "token": token},
        )

    def _publish_event(
        self,
        kind: str,
        scheduled: ScheduledStep,
        values: dict[str, int],
    ) -> None:
        payload = {
            "kind": kind,
            "task_id": scheduled.task_id,
            "robot_id": scheduled.robot_id,
            "assigned_tick": scheduled.assigned_tick,
            "finish_tick": scheduled.finish_tick,
            **values,
        }
        self._event_publisher.publish(
            String(data=json.dumps(payload, sort_keys=True, separators=(",", ":")))
        )


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = CoordinatorNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()
