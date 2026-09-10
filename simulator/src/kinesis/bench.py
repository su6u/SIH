from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Sequence

from .allocation import Bidder
from .fleet import SimulationConfig
from .heuristics import DistanceOracle
from .planner import SpaceTimeAStar
from .reservations import ReservationTable
from .scenario import Scenario
from .schedule import RobotHorizon, RollingHorizonScheduler


@dataclass(frozen=True, slots=True)
class LatencySamples:
    name: str
    count: int
    mean_ms: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    max_ms: float


@dataclass(frozen=True, slots=True)
class LatencyReport:
    scenario: str
    robots: int
    tasks: int
    repetitions: int
    stages: tuple[LatencySamples, ...]

    def stage(self, name: str) -> LatencySamples | None:
        for item in self.stages:
            if item.name == name:
                return item
        return None


def measure_decision_latency(
    scenario: Scenario,
    config: SimulationConfig = SimulationConfig(),
    *,
    repetitions: int = 30,
) -> LatencyReport:
    """Time the per-decision work a robot does on its own hardware.

    ``bid`` is one robot pricing one task: two complete space-time searches.
    ``schedule`` is one whole-fleet look-ahead allocation over every open order,
    which the rolling-horizon policy runs when the fleet state moves. Both are
    measured on the empty reservation table so the figure is a property of the
    map and workload rather than of one moment in one run.
    """
    if repetitions <= 0:
        raise ValueError("repetitions must be positive")
    reservations = ReservationTable(clearance_cells=config.clearance_cells)
    distances = DistanceOracle(scenario.warehouse_map)
    planner = SpaceTimeAStar(
        scenario.warehouse_map,
        reservations,
        move_ticks=config.motion.move_ticks,
        distances=distances,
    )
    bidder = Bidder(
        planner,
        reservations,
        motion=config.motion,
        planning_horizon_ticks=config.planning_horizon_ticks,
    )
    scheduler = RollingHorizonScheduler(
        distances,
        move_ticks=config.motion.move_ticks,
        weights=config.schedule_weights,
        improvement_steps=config.schedule_improvement_steps,
        seed=config.schedule_seed or scenario.seed,
    )
    horizons = tuple(
        RobotHorizon(robot.robot_id, robot.cell, 0, robot.payload_capacity_kg)
        for robot in scenario.robots
    )

    # Warm the distance-field cache first; a cold field is a one-off cost that
    # would otherwise be charged to whichever decision happened to run first.
    for task in scenario.tasks:
        distances.field(task.pickup)
        distances.field(task.dropoff)

    bid_samples: list[float] = []
    schedule_samples: list[float] = []
    for repetition in range(repetitions):
        for robot in scenario.robots:
            for task in scenario.tasks:
                start = time.perf_counter()
                bidder.bid(robot, task, current_tick=0, auction_epoch=repetition + 1)
                bid_samples.append((time.perf_counter() - start) * 1000.0)
        start = time.perf_counter()
        scheduler.solve(horizons, scenario.tasks, current_tick=0)
        schedule_samples.append((time.perf_counter() - start) * 1000.0)

    return LatencyReport(
        scenario=scenario.name,
        robots=len(scenario.robots),
        tasks=len(scenario.tasks),
        repetitions=repetitions,
        stages=(
            _summarise("bid", bid_samples),
            _summarise("schedule", schedule_samples),
        ),
    )


def _summarise(name: str, samples: Sequence[float]) -> LatencySamples:
    ordered = sorted(samples)
    return LatencySamples(
        name=name,
        count=len(ordered),
        mean_ms=sum(ordered) / len(ordered) if ordered else 0.0,
        p50_ms=_percentile(ordered, 0.50),
        p95_ms=_percentile(ordered, 0.95),
        p99_ms=_percentile(ordered, 0.99),
        max_ms=ordered[-1] if ordered else 0.0,
    )


def _percentile(ordered: Sequence[float], probability: float) -> float:
    if not ordered:
        return 0.0
    index = probability * (len(ordered) - 1)
    lower = int(index)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = index - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction
