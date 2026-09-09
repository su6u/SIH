from __future__ import annotations

from dataclasses import asdict, dataclass, replace

from .allocation import Bid, Bidder, select_winner
from .domain import RobotState, Task
from .events import EventLog
from .graph import WarehouseMap
from .planner import SpaceTimeAStar
from .physics import MotionConfig
from .reservations import ReservationTable


@dataclass(frozen=True, slots=True)
class TaskOutcome:
    task_id: str
    status: str
    robot_id: str | None
    release_tick: int
    finish_tick: int | None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class ExperimentMetrics:
    task_count: int
    completed_tasks: int
    unassigned_tasks: int
    deadline_misses: int
    makespan_ticks: int
    total_flow_ticks: int
    mean_flow_ticks: float


@dataclass(frozen=True, slots=True)
class ExperimentResult:
    outcomes: tuple[TaskOutcome, ...]
    robots: tuple[RobotState, ...]
    metrics: ExperimentMetrics
    events: EventLog


class FleetExperiment:
    def __init__(
        self,
        warehouse_map: WarehouseMap,
        robots: tuple[RobotState, ...],
        *,
        motion: MotionConfig = MotionConfig(),
    ) -> None:
        if not robots:
            raise ValueError("at least one robot is required")
        if len({robot.robot_id for robot in robots}) != len(robots):
            raise ValueError("robot identifiers must be unique")
        for robot in robots:
            if not warehouse_map.traversable(robot.cell):
                raise ValueError(f"robot {robot.robot_id} starts in a blocked cell")
        self._map = warehouse_map
        self._initial_robots = tuple(sorted(robots, key=lambda robot: robot.robot_id))
        self._motion = motion

    def run(self, tasks: tuple[Task, ...]) -> ExperimentResult:
        reservations = ReservationTable()
        planner = SpaceTimeAStar(
            self._map, reservations, move_ticks=self._motion.move_ticks
        )
        bidder = Bidder(planner, reservations, motion=self._motion)
        robots = {robot.robot_id: robot for robot in self._initial_robots}
        events = EventLog()
        outcomes: list[TaskOutcome] = []

        for epoch, task in enumerate(
            sorted(tasks, key=lambda item: (item.release_tick, item.task_id)), 1
        ):
            events.append(
                tick=task.release_tick,
                kind="task_announced",
                entity_id=task.task_id,
                data={"auction_epoch": epoch},
            )
            bids = tuple(
                bidder.bid(
                    robot, task, current_tick=task.release_tick, auction_epoch=epoch
                )
                for robot in robots.values()
            )
            for bid in bids:
                events.append(
                    tick=task.release_tick,
                    kind="task_bid",
                    entity_id=task.task_id,
                    data=_bid_event_data(bid),
                )

            try:
                winner = select_winner(bids)
            except ValueError:
                reason = "no feasible bid"
                outcomes.append(
                    TaskOutcome(
                        task.task_id,
                        "unassigned",
                        None,
                        task.release_tick,
                        None,
                        reason,
                    )
                )
                events.append(
                    tick=task.release_tick,
                    kind="task_unassigned",
                    entity_id=task.task_id,
                    data={"reason": reason},
                )
                continue

            if (
                winner.execution_plan is None
                or winner.expected_finish_tick is None
                or winner.expected_soc is None
            ):
                raise AssertionError("feasible bid is missing its execution plan")
            conflicts = reservations.commit(winner.execution_plan)
            if conflicts:
                raise AssertionError(
                    f"selected plan conflicted during commit: {conflicts}"
                )

            current = robots[winner.robot_id]
            robots[winner.robot_id] = replace(
                current,
                cell=task.dropoff,
                battery_soc=winner.expected_soc,
                available_tick=winner.expected_finish_tick,
                completed_tasks=current.completed_tasks + 1,
            )
            outcome = TaskOutcome(
                task.task_id,
                "completed",
                winner.robot_id,
                task.release_tick,
                winner.expected_finish_tick,
            )
            outcomes.append(outcome)
            events.append(
                tick=task.release_tick,
                kind="task_awarded",
                entity_id=task.task_id,
                data={
                    "robot_id": winner.robot_id,
                    "auction_epoch": epoch,
                    "score": winner.score,
                    "finish_tick": winner.expected_finish_tick,
                },
            )
            events.append(
                tick=winner.expected_finish_tick,
                kind="task_completed",
                entity_id=task.task_id,
                data={"robot_id": winner.robot_id, "battery_soc": winner.expected_soc},
            )

        metrics = _metrics(tuple(outcomes), len(tasks))
        return ExperimentResult(
            outcomes=tuple(outcomes),
            robots=tuple(sorted(robots.values(), key=lambda robot: robot.robot_id)),
            metrics=metrics,
            events=events,
        )


def _bid_event_data(bid: Bid) -> dict[str, object]:
    return {
        "robot_id": bid.robot_id,
        "auction_epoch": bid.auction_epoch,
        "feasible": bid.feasible,
        "score": bid.score,
        "expected_finish_tick": bid.expected_finish_tick,
        "expected_soc": bid.expected_soc,
        "components": asdict(bid.components),
        "reason": bid.reason,
    }


def _metrics(outcomes: tuple[TaskOutcome, ...], task_count: int) -> ExperimentMetrics:
    completed = [outcome for outcome in outcomes if outcome.status == "completed"]
    flow_times = [
        outcome.finish_tick - outcome.release_tick
        for outcome in completed
        if outcome.finish_tick is not None
    ]
    deadline_misses = 0
    return ExperimentMetrics(
        task_count=task_count,
        completed_tasks=len(completed),
        unassigned_tasks=task_count - len(completed),
        deadline_misses=deadline_misses,
        makespan_ticks=max(
            (outcome.finish_tick or 0 for outcome in completed), default=0
        ),
        total_flow_ticks=sum(flow_times),
        mean_flow_ticks=sum(flow_times) / len(flow_times) if flow_times else 0.0,
    )
