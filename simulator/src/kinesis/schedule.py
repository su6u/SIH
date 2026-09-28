from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence

from .domain import Cell, Task
from .heuristics import DistanceOracle


@dataclass(frozen=True, slots=True)
class ScheduleWeights:
    """Relative importance of the three fleet objectives.

    ``makespan`` balances load across the fleet, ``flow`` shortens the average
    order, and ``lateness`` keeps deadline misses out of the solution.
    """

    makespan: float = 0.5
    flow: float = 0.5
    lateness: float = 20.0

    def __post_init__(self) -> None:
        values = (self.makespan, self.flow, self.lateness)
        if any(not math.isfinite(value) or value < 0 for value in values):
            raise ValueError("schedule weights must be finite and non-negative")
        if self.makespan <= 0 and self.flow <= 0:
            raise ValueError("at least one of makespan or flow must be positive")


@dataclass(frozen=True, slots=True)
class RobotHorizon:
    """Where a robot will be, and when, once its committed work is done."""

    robot_id: str
    cell: Cell
    ready_tick: int
    payload_capacity_kg: float = math.inf

    def __post_init__(self) -> None:
        if not self.robot_id:
            raise ValueError("robot_id must not be empty")
        if self.ready_tick < 0:
            raise ValueError("ready_tick must be non-negative")


@dataclass(frozen=True, slots=True)
class ScheduledTask:
    task_id: str
    robot_id: str
    position: int
    start_tick: int
    finish_tick: int


@dataclass(frozen=True, slots=True)
class Schedule:
    sequences: Mapping[str, tuple[str, ...]]
    entries: Mapping[str, ScheduledTask]
    unassigned: tuple[str, ...]
    objective: float
    improvement_steps: int = 0

    def head(self, robot_id: str) -> str | None:
        sequence = self.sequences.get(robot_id, ())
        return sequence[0] if sequence else None

    def ranked_robots(self, task_id: str) -> tuple[str, ...]:
        entry = self.entries.get(task_id)
        return (entry.robot_id,) if entry is not None else ()


@dataclass(slots=True)
class _Lane:
    """One robot's tentative task sequence plus its cached roll-up.

    ``solve`` evaluates the objective once per candidate placement, and only
    one lane changes between evaluations. Caching each lane's contribution and
    recomputing just the lane that moved keeps a full fleet allocation linear
    in the sequence rather than in the whole order book.
    """

    robot_id: str
    cell: Cell
    ready_tick: int
    capacity_kg: float
    sequence: list[str] = field(default_factory=list)
    summary: tuple[int, int, int, int] | None = None
    feasible: bool = True

    def invalidate(self) -> None:
        self.summary = None

    def append(self, task_id: str) -> None:
        self.sequence.append(task_id)
        self.invalidate()

    def pop(self) -> str:
        self.invalidate()
        return self.sequence.pop()


class RollingHorizonScheduler:
    """Look-ahead task allocation over every robot, not only the idle ones.

    The shipped auction awards one task at a time to whichever robot is free
    right now, so a robot two ticks from finishing never competes with an idle
    robot twenty cells away. This scheduler instead projects every robot to the
    pose and tick where its committed work ends, then allocates the whole known
    order book as per-robot sequences.

    Allocation is a sequential single-item auction with regret clearing: each
    round awards the task whose best and second-best robots differ most, which
    is the task that would suffer most from being left until later. A bounded
    large-neighbourhood search then relocates and swaps tasks between robots
    while the objective strictly improves.

    Costs come from :class:`DistanceOracle`, so a full allocation is arithmetic
    over cached distance fields rather than space-time search. The caller keeps
    the sequences as advice: only the head of each idle robot's sequence is
    auctioned for real, and the whole schedule is recomputed on the next tick
    with fresher information.
    """

    def __init__(
        self,
        distances: DistanceOracle,
        *,
        move_ticks: int = 1,
        weights: ScheduleWeights = ScheduleWeights(),
        improvement_steps: int = 0,
        seed: int = 0,
    ) -> None:
        if move_ticks <= 0:
            raise ValueError("move_ticks must be positive")
        if improvement_steps < 0:
            raise ValueError("improvement_steps must be non-negative")
        self._distances = distances
        self._move_ticks = move_ticks
        self._weights = weights
        self._improvement_steps = improvement_steps
        self._seed = seed

    def route_ticks(self, cell: Cell, task: Task) -> int | None:
        """Ticks to reach the pickup, serve it, reach the drop-off and serve it."""
        to_pickup = self._distances.distance(cell, task.pickup)
        if to_pickup is None:
            return None
        to_dropoff = self._distances.distance(task.pickup, task.dropoff)
        if to_dropoff is None:
            return None
        return (to_pickup + to_dropoff) * self._move_ticks + 2 * task.service_ticks

    def finish_tick(
        self, horizon: RobotHorizon, task: Task, *, current_tick: int
    ) -> int | None:
        ticks = self.route_ticks(horizon.cell, task)
        if ticks is None:
            return None
        start = max(horizon.ready_tick, task.release_tick, current_tick)
        return start + ticks

    def solve(
        self,
        horizons: Iterable[RobotHorizon],
        tasks: Iterable[Task],
        *,
        current_tick: int,
    ) -> Schedule:
        lanes = [
            _Lane(item.robot_id, item.cell, item.ready_tick, item.payload_capacity_kg)
            for item in sorted(horizons, key=lambda item: item.robot_id)
        ]
        catalogue = {task.task_id: task for task in tasks}
        if not lanes or not catalogue:
            return Schedule({}, {}, tuple(sorted(catalogue)), 0.0)

        by_robot = {lane.robot_id: lane for lane in lanes}
        remaining = sorted(catalogue)
        unassigned: list[str] = []

        while remaining:
            best_choice: tuple[tuple[float, float, str], str, str] | None = None
            for task_id in remaining:
                task = catalogue[task_id]
                candidates = (
                    self._append_objective(lanes, lane, task, catalogue, current_tick)
                    for lane in lanes
                )
                costs = sorted(cost for cost in candidates if cost is not None)
                if not costs:
                    continue
                best_cost, best_robot = costs[0]
                runner_up = costs[1][0] if len(costs) > 1 else best_cost
                regret = runner_up - best_cost
                key = (-regret, best_cost, task_id)
                if best_choice is None or key < best_choice[0]:
                    best_choice = (key, task_id, best_robot)
            if best_choice is None:
                unassigned.extend(remaining)
                break
            _, task_id, robot_id = best_choice
            by_robot[robot_id].append(task_id)
            remaining.remove(task_id)

        steps = self._improve(lanes, catalogue, current_tick)
        entries = self._timeline(lanes, catalogue, current_tick)
        return Schedule(
            sequences={lane.robot_id: tuple(lane.sequence) for lane in lanes},
            entries=entries,
            unassigned=tuple(sorted(unassigned)),
            objective=self._objective(lanes, catalogue, current_tick),
            improvement_steps=steps,
        )

    # -- objective -----------------------------------------------------------

    def _timeline(
        self,
        lanes: Sequence[_Lane],
        catalogue: Mapping[str, Task],
        current_tick: int,
    ) -> dict[str, ScheduledTask]:
        entries: dict[str, ScheduledTask] = {}
        for lane in lanes:
            cell, clock = lane.cell, lane.ready_tick
            for position, task_id in enumerate(lane.sequence):
                task = catalogue[task_id]
                ticks = self.route_ticks(cell, task)
                if ticks is None:
                    continue
                start = max(clock, task.release_tick, current_tick)
                clock = start + ticks
                cell = task.dropoff
                entries[task_id] = ScheduledTask(
                    task_id, lane.robot_id, position, start, clock
                )
        return entries

    def _lane_summary(
        self, lane: _Lane, catalogue: Mapping[str, Task], current_tick: int
    ) -> tuple[int, int, int, int] | None:
        """``(end_tick, flow_total, lateness, count)`` for one lane, cached."""
        if lane.summary is not None:
            return lane.summary if lane.feasible else None
        cell, clock = lane.cell, lane.ready_tick
        flow_total = lateness = count = 0
        for task_id in lane.sequence:
            task = catalogue[task_id]
            ticks = self.route_ticks(cell, task)
            if ticks is None or task.payload_kg > lane.capacity_kg:
                lane.summary = (0, 0, 0, 0)
                lane.feasible = False
                return None
            clock = max(clock, task.release_tick, current_tick) + ticks
            cell = task.dropoff
            flow_total += clock - task.release_tick
            lateness += max(0, clock - task.deadline_tick)
            count += 1
        lane.summary = (clock, flow_total, lateness, count)
        lane.feasible = True
        return lane.summary

    def _objective(
        self,
        lanes: Sequence[_Lane],
        catalogue: Mapping[str, Task],
        current_tick: int,
    ) -> float:
        makespan = 0
        flow_total = 0
        lateness = 0
        count = 0
        for lane in lanes:
            summary = self._lane_summary(lane, catalogue, current_tick)
            if summary is None:
                return math.inf
            end_tick, lane_flow, lane_lateness, lane_count = summary
            makespan = max(makespan, end_tick)
            flow_total += lane_flow
            lateness += lane_lateness
            count += lane_count
        if count == 0:
            return 0.0
        return (
            self._weights.makespan * makespan
            + self._weights.flow * flow_total / count
            + self._weights.lateness * lateness
        )

    def _append_objective(
        self,
        lanes: Sequence[_Lane],
        lane: _Lane,
        task: Task,
        catalogue: Mapping[str, Task],
        current_tick: int,
    ) -> tuple[float, str] | None:
        if task.payload_kg > lane.capacity_kg:
            return None
        if self.route_ticks(self._lane_end_cell(lane, catalogue), task) is None:
            return None
        lane.append(task.task_id)
        value = self._objective(lanes, catalogue, current_tick)
        lane.pop()
        if not math.isfinite(value):
            return None
        return value, lane.robot_id

    def _lane_end_cell(self, lane: _Lane, catalogue: Mapping[str, Task]) -> Cell:
        if not lane.sequence:
            return lane.cell
        return catalogue[lane.sequence[-1]].dropoff

    # -- improvement ---------------------------------------------------------

    def _improve(
        self,
        lanes: Sequence[_Lane],
        catalogue: Mapping[str, Task],
        current_tick: int,
    ) -> int:
        """Bounded large-neighbourhood search over the allocation.

        Relocate and swap moves are drawn from a generator seeded by the run
        seed and the tick, so the search is reproducible, and a move is kept
        only when it strictly improves the objective. The schedule can
        therefore never come out worse than the auction that produced it.
        """
        if self._improvement_steps <= 0 or not lanes:
            return 0
        generator = random.Random(self._seed * 1_000_003 + current_tick)
        best = self._objective(lanes, catalogue, current_tick)
        accepted = 0
        for _ in range(self._improvement_steps):
            populated = [lane for lane in lanes if lane.sequence]
            if not populated:
                break
            source = generator.choice(populated)
            index = generator.randrange(len(source.sequence))
            relocate = generator.random() < 0.65
            target = generator.choice(lanes if relocate else populated)
            snapshot = {id(lane): list(lane.sequence) for lane in (source, target)}
            if relocate:
                task_id = source.sequence.pop(index)
                target.sequence.insert(
                    generator.randrange(len(target.sequence) + 1), task_id
                )
            else:
                position = generator.randrange(len(target.sequence))
                source.sequence[index], target.sequence[position] = (
                    target.sequence[position],
                    source.sequence[index],
                )
            source.invalidate()
            target.invalidate()
            value = self._objective(lanes, catalogue, current_tick)
            if value < best - 1e-9:
                best = value
                accepted += 1
                continue
            for lane in (source, target):
                lane.sequence[:] = snapshot[id(lane)]
                lane.invalidate()
        return accepted
