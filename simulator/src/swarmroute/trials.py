from __future__ import annotations

import random
from dataclasses import dataclass, replace
from typing import Mapping, Sequence

from .comparison import PolicyDelta, compare_policies
from .domain import Cell, RobotState, Task
from .fleet import CoordinationPolicy, FleetMetrics, SimulationConfig
from .heuristics import DistanceOracle
from .scenario import Scenario


@dataclass(frozen=True, slots=True)
class Estimate:
    """A statistic over trials, with a percentile bootstrap interval."""

    mean: float
    lower: float
    upper: float
    minimum: float
    maximum: float
    samples: int


@dataclass(frozen=True, slots=True)
class TrialResult:
    seed: int
    metrics: Mapping[str, FleetMetrics]
    deltas: tuple[PolicyDelta, ...]


@dataclass(frozen=True, slots=True)
class PairSummary:
    candidate: str
    baseline: str
    paired_mean_flow_reduction_percent: Estimate
    throughput_relative_change_percent: Estimate
    completion_rate_difference_percentage_points: Estimate
    trials_meeting_twenty_percent_target: int


@dataclass(frozen=True, slots=True)
class TrialReport:
    scenario: str
    trials: int
    seed: int
    pairs: tuple[PairSummary, ...]
    completed_tasks: Mapping[str, Estimate]
    makespan_ticks: Mapping[str, Estimate]
    executed_conflicts: Mapping[str, int]
    results: tuple[TrialResult, ...]

    def pair(self, candidate: str, baseline: str) -> PairSummary | None:
        for item in self.pairs:
            if item.candidate == candidate and item.baseline == baseline:
                return item
        return None


def randomize_scenario(base: Scenario, *, seed: int) -> Scenario:
    """Resample robot start cells and task endpoints on the same map.

    The workload shape is held fixed — same fleet size, same number of orders,
    same release schedule, same deadline slack and payloads — so trials differ
    only in where the work is. That keeps the trials comparable to each other
    and to the authored scenario while giving a real distribution to average
    over, which a single deterministic run cannot provide.
    """
    generator = random.Random(seed)
    oracle = DistanceOracle(base.warehouse_map)
    reserved = {cell for zone in base.conflict_zones for cell in zone.cells}
    free = [
        Cell(x, y)
        for y in range(base.warehouse_map.height)
        for x in range(base.warehouse_map.width)
        if base.warehouse_map.traversable(Cell(x, y)) and Cell(x, y) not in reserved
    ]
    if len(free) < len(base.robots) + 2:
        raise ValueError("map has too few free cells to randomise")

    starts = generator.sample(free, len(base.robots))
    ordered = sorted(base.robots, key=lambda item: item.robot_id)
    robots = tuple(
        replace(robot, cell=cell)
        for robot, cell in zip(ordered, starts, strict=True)
    )

    tasks: list[Task] = []
    for task in sorted(base.tasks, key=lambda item: item.task_id):
        for _ in range(64):
            pickup, dropoff = generator.sample(free, 2)
            if oracle.reachable(pickup, dropoff):
                break
        else:  # pragma: no cover - only reachable on a pathological map
            pickup, dropoff = task.pickup, task.dropoff
        tasks.append(replace(task, pickup=pickup, dropoff=dropoff))

    return replace(
        base,
        name=f"{base.name}-trial-{seed}",
        robots=robots,
        tasks=tuple(tasks),
        seed=seed,
    )


def run_trials(
    base: Scenario,
    config: SimulationConfig,
    *,
    trials: int = 30,
    seed: int = 20260904,
    bootstrap_samples: int = 2_000,
    policies: tuple[CoordinationPolicy, ...] = (
        CoordinationPolicy.STOP_AND_WAIT,
        CoordinationPolicy.SPACE_TIME,
        CoordinationPolicy.ROLLING_HORIZON,
    ),
) -> TrialReport:
    """Run every policy on ``trials`` randomised layouts of the same workload."""
    if trials <= 0:
        raise ValueError("trials must be positive")
    generator = random.Random(seed)
    trial_seeds = [generator.randrange(1, 2**31 - 1) for _ in range(trials)]

    results: list[TrialResult] = []
    for trial_seed in trial_seeds:
        scenario = randomize_scenario(base, seed=trial_seed)
        comparison = compare_policies(
            scenario,
            config,
            bootstrap_samples=bootstrap_samples,
            policies=policies,
        )
        results.append(
            TrialResult(
                seed=trial_seed,
                metrics={
                    name: run.metrics for name, run in comparison.runs.items()
                },
                deltas=comparison.deltas,
            )
        )

    pair_keys: list[tuple[str, str]] = []
    for item in results[0].deltas:
        if (item.candidate, item.baseline) not in pair_keys:
            pair_keys.append((item.candidate, item.baseline))

    pairs = []
    for candidate, baseline in pair_keys:
        found = [
            item
            for result in results
            for item in result.deltas
            if item.candidate == candidate and item.baseline == baseline
        ]
        reductions = [
            item.paired_mean_flow_reduction_percent
            for item in found
            if item.paired_mean_flow_reduction_percent is not None
        ]
        throughputs = [
            item.throughput_relative_change_percent
            for item in found
            if item.throughput_relative_change_percent is not None
        ]
        completions = [
            item.completion_rate_difference_percentage_points for item in found
        ]
        pairs.append(
            PairSummary(
                candidate=candidate,
                baseline=baseline,
                paired_mean_flow_reduction_percent=_estimate(reductions, seed),
                throughput_relative_change_percent=_estimate(throughputs, seed),
                completion_rate_difference_percentage_points=_estimate(
                    completions, seed
                ),
                trials_meeting_twenty_percent_target=sum(
                    1 for value in reductions if value >= 20.0
                ),
            )
        )

    names = sorted(results[0].metrics)
    return TrialReport(
        scenario=base.name,
        trials=trials,
        seed=seed,
        pairs=tuple(pairs),
        completed_tasks={
            name: _estimate(
                [float(result.metrics[name].completed_tasks) for result in results],
                seed,
            )
            for name in names
        },
        makespan_ticks={
            name: _estimate(
                [float(result.metrics[name].makespan_ticks) for result in results],
                seed,
            )
            for name in names
        },
        executed_conflicts={
            name: sum(
                result.metrics[name].executed_grid_vertex_conflicts
                + result.metrics[name].executed_grid_reverse_edge_conflicts
                for result in results
            )
            for name in names
        },
        results=tuple(results),
    )


def _estimate(values: Sequence[float], seed: int, *, samples: int = 10_000) -> Estimate:
    if not values:
        return Estimate(0.0, 0.0, 0.0, 0.0, 0.0, 0)
    ordered = sorted(values)
    mean = sum(values) / len(values)
    generator = random.Random(seed)
    means = sorted(
        sum(generator.choice(values) for _ in values) / len(values)
        for _ in range(samples)
    )
    return Estimate(
        mean=mean,
        lower=_quantile(means, 0.025),
        upper=_quantile(means, 0.975),
        minimum=ordered[0],
        maximum=ordered[-1],
        samples=len(values),
    )


def _quantile(values: list[float], probability: float) -> float:
    index = probability * (len(values) - 1)
    lower = int(index)
    upper = min(lower + 1, len(values) - 1)
    fraction = index - lower
    return values[lower] * (1.0 - fraction) + values[upper] * fraction
