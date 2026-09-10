from __future__ import annotations

import math
from dataclasses import dataclass

from .domain import Plan, PlanStep, RobotState, Task
from .physics import MotionConfig, estimate_motion
from .planner import NoPathError, SpaceTimeAStar
from .reservations import ReservationTable


@dataclass(frozen=True, slots=True)
class BidWeights:
    eta: float = 0.45
    congestion: float = 0.20
    battery: float = 0.20
    deadline: float = 0.15

    def __post_init__(self) -> None:
        values = (self.eta, self.congestion, self.battery, self.deadline)
        if any(value < 0 for value in values) or not math.isclose(sum(values), 1.0):
            raise ValueError("bid weights must be non-negative and sum to 1")


@dataclass(frozen=True, slots=True)
class BidComponents:
    eta: float
    congestion: float
    battery: float
    deadline: float

    def __post_init__(self) -> None:
        if any(
            not math.isfinite(value) or value < 0
            for value in (self.eta, self.congestion, self.battery, self.deadline)
        ):
            raise ValueError("bid components must be finite and non-negative")


# Refusals that stay true as the clock advances, provided no reservation has
# changed. Starting later never buys a robot more room: its earliest possible
# finish only moves outwards while the deadline and the horizon stay put, and
# any route available from a later tick was already available from an earlier
# one by waiting. Re-pricing such a pair before the table changes cannot
# produce a different answer, so the auction is free to skip it.
SETTLED_REFUSALS = frozenset(
    {
        "payload capacity exceeded",
        "no route to pickup or dropoff",
        "deadline cannot be met",
        "route exceeds planning horizon",
        "pickup and service exceed planning horizon",
    }
)


def is_settled_refusal(bid: "Bid") -> bool:
    if bid.feasible or bid.reason is None:
        return False
    return bid.reason in SETTLED_REFUSALS or bid.reason.startswith("no path to")


@dataclass(frozen=True, slots=True)
class Bid:
    robot_id: str
    task_id: str
    auction_epoch: int
    feasible: bool
    score: float
    components: BidComponents
    expected_finish_tick: int | None
    expected_soc: float | None
    workload: int
    execution_plan: Plan | None = None
    pickup_plan: Plan | None = None
    dropoff_plan: Plan | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if not self.robot_id or not self.task_id:
            raise ValueError("bid identifiers must not be empty")
        if self.auction_epoch < 0 or self.workload < 0:
            raise ValueError("bid epoch and workload must be non-negative")
        if not math.isfinite(self.score) or self.score < 0:
            raise ValueError("bid score must be finite and non-negative")


class Bidder:
    def __init__(
        self,
        planner: SpaceTimeAStar,
        reservations: ReservationTable,
        *,
        weights: BidWeights = BidWeights(),
        motion: MotionConfig = MotionConfig(),
        planning_horizon_ticks: int = 120,
        safe_soc: float = 0.25,
        deadline_sigma_ticks: float = 20.0,
        max_plan_tick: int | None = None,
    ) -> None:
        if planning_horizon_ticks <= 0 or deadline_sigma_ticks <= 0:
            raise ValueError("horizons must be positive")
        if not 0 <= safe_soc <= 1:
            raise ValueError("safe_soc must be in [0, 1]")
        self._planner = planner
        self._reservations = reservations
        self._weights = weights
        self._motion = motion
        self._horizon = planning_horizon_ticks
        self._safe_soc = safe_soc
        self._deadline_sigma = deadline_sigma_ticks
        self._max_plan_tick = max_plan_tick

    def bid(
        self, robot: RobotState, task: Task, *, current_tick: int, auction_epoch: int
    ) -> Bid:
        if task.payload_kg > robot.payload_capacity_kg:
            return self._infeasible(
                robot, task, auction_epoch, "payload capacity exceeded"
            )
        start_tick = max(current_tick, robot.available_tick, task.release_tick)
        # A parking reservation only runs to the end of the simulated horizon.
        # Planning past it would let a robot "wait out" another robot's tail
        # and call that a route, so the search is clamped to the same tick the
        # reservations are known to.
        horizon_end = start_tick + self._horizon
        if self._max_plan_tick is not None:
            horizon_end = min(horizon_end, self._max_plan_tick)
        earliest_finish = self._earliest_possible_finish(robot, task, start_tick)
        if earliest_finish is None:
            return self._infeasible(
                robot, task, auction_epoch, "no route to pickup or dropoff"
            )
        if earliest_finish > task.deadline_tick:
            return self._infeasible(
                robot, task, auction_epoch, "deadline cannot be met"
            )
        if earliest_finish > horizon_end:
            return self._infeasible(
                robot, task, auction_epoch, "route exceeds planning horizon"
            )
        try:
            pickup = self._planner.plan(
                robot.robot_id,
                robot.cell,
                task.pickup,
                start_tick=start_tick,
                max_tick=horizon_end,
            )
            dropoff_start = pickup.end.tick + task.service_ticks
            if dropoff_start > horizon_end:
                return self._infeasible(
                    robot,
                    task,
                    auction_epoch,
                    "pickup and service exceed planning horizon",
                )
            dropoff = self._planner.plan(
                robot.robot_id,
                task.pickup,
                task.dropoff,
                start_tick=dropoff_start,
                max_tick=horizon_end - task.service_ticks,
            )
        except NoPathError as error:
            return self._infeasible(robot, task, auction_epoch, str(error))

        service_seconds = task.service_ticks * self._motion.tick_seconds
        empty_motion = estimate_motion(
            pickup,
            payload_kg=0.0,
            config=self._motion,
            dwell_seconds=service_seconds,
        )
        loaded_motion = estimate_motion(
            dropoff,
            payload_kg=task.payload_kg,
            config=self._motion,
            include_lift=True,
            dwell_seconds=service_seconds,
        )
        expected_soc = (
            robot.battery_soc - empty_motion.soc_delta - loaded_motion.soc_delta
        )
        execution_steps = list(pickup.steps)
        execution_steps.extend(
            PlanStep(task.pickup, tick)
            for tick in range(pickup.end.tick + 1, dropoff.start.tick)
        )
        execution_steps.extend(
            step for step in dropoff.steps if step.tick > pickup.end.tick
        )
        execution_steps.extend(
            PlanStep(task.dropoff, tick)
            for tick in range(
                dropoff.end.tick + 1, dropoff.end.tick + task.service_ticks + 1
            )
        )
        execution = Plan.from_steps(robot.robot_id, execution_steps)
        expected_finish = execution.end.tick
        eta = min(1.0, (expected_finish - current_tick) / self._horizon)
        congestion = self._reservations.pressure(execution)
        reserve_soc = max(self._safe_soc, robot.reserve_soc)
        battery = 1.0 / (1.0 + math.exp(15.0 * (expected_soc - reserve_soc)))
        slack = task.deadline_tick - expected_finish
        deadline = (
            math.exp(-slack / self._deadline_sigma)
            if slack >= 0
            else 1.0 + abs(slack) / self._deadline_sigma
        )
        components = BidComponents(eta, congestion, battery, deadline)
        score = (
            self._weights.eta * eta
            + self._weights.congestion * congestion
            + self._weights.battery * battery
            + self._weights.deadline * deadline
        )
        feasible = expected_soc >= reserve_soc and expected_finish <= task.deadline_tick
        reason = None
        if expected_soc < reserve_soc:
            reason = "battery reserve would be violated"
        elif expected_finish > task.deadline_tick:
            reason = "deadline cannot be met"
        return Bid(
            robot_id=robot.robot_id,
            task_id=task.task_id,
            auction_epoch=auction_epoch,
            feasible=feasible,
            score=score,
            components=components,
            expected_finish_tick=expected_finish,
            expected_soc=expected_soc,
            workload=robot.completed_tasks,
            execution_plan=execution,
            pickup_plan=pickup,
            dropoff_plan=dropoff,
            reason=reason,
        )

    def _earliest_possible_finish(
        self, robot: RobotState, task: Task, start_tick: int
    ) -> int | None:
        """Admissible lower bound on the execution plan's final tick.

        Uses exact obstacle-aware distances and assumes the robot never waits,
        so a bound past the deadline proves the real bid is infeasible too.
        Pruning on it keeps auction outcomes identical while skipping two
        space-time searches per hopeless robot/task pair.
        """
        distances = self._planner.distances
        to_pickup = distances.distance(robot.cell, task.pickup)
        if to_pickup is None:
            return None
        to_dropoff = distances.distance(task.pickup, task.dropoff)
        if to_dropoff is None:
            return None
        travel = (to_pickup + to_dropoff) * self._planner.move_ticks
        return start_tick + travel + 2 * task.service_ticks

    @staticmethod
    def _infeasible(robot: RobotState, task: Task, epoch: int, reason: str) -> Bid:
        return Bid(
            robot_id=robot.robot_id,
            task_id=task.task_id,
            auction_epoch=epoch,
            feasible=False,
            score=0.0,
            components=BidComponents(0.0, 0.0, 0.0, 0.0),
            expected_finish_tick=None,
            expected_soc=None,
            workload=robot.completed_tasks,
            reason=reason,
        )


def select_winner(
    bids: list[Bid] | tuple[Bid, ...], *, fairness_tolerance: float = 0.05
) -> Bid:
    if not 0 <= fairness_tolerance <= 1:
        raise ValueError("fairness_tolerance must be in [0, 1]")
    feasible = [bid for bid in bids if bid.feasible]
    if not feasible:
        raise ValueError("auction has no feasible bids")
    task_keys = {(bid.task_id, bid.auction_epoch) for bid in feasible}
    if len(task_keys) != 1:
        raise ValueError("all bids must refer to the same task and epoch")

    best_score = min(bid.score for bid in feasible)
    threshold = best_score * (1.0 + fairness_tolerance)
    shortlist = [bid for bid in feasible if bid.score <= threshold + 1e-12]
    return min(shortlist, key=lambda bid: (bid.workload, bid.score, bid.robot_id))
