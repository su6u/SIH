from __future__ import annotations

import random
from dataclasses import dataclass, replace

from .fleet import CoordinationPolicy, FleetRunResult, FleetSimulation, SimulationConfig
from .scenario import Scenario


@dataclass(frozen=True, slots=True)
class ConfidenceInterval:
    lower: float
    estimate: float
    upper: float
    paired_tasks: int


@dataclass(frozen=True, slots=True)
class PolicyDelta:
    """One candidate policy measured against one baseline policy."""

    candidate: str
    baseline: str
    completion_rate_difference_percentage_points: float
    throughput_relative_change_percent: float | None
    paired_completed_task_flow_ticks: ConfidenceInterval | None
    paired_mean_flow_reduction_percent: float | None
    baseline_paired_mean_flow_ticks: float | None
    candidate_paired_mean_flow_ticks: float | None


@dataclass(frozen=True, slots=True)
class PolicyComparison:
    space_time: FleetRunResult
    stop_and_wait: FleetRunResult
    completion_rate_difference_percentage_points: float
    throughput_relative_change_percent: float | None
    paired_completed_task_flow_ticks: ConfidenceInterval | None
    rolling_horizon: FleetRunResult | None = None
    deltas: tuple[PolicyDelta, ...] = ()

    @property
    def runs(self) -> dict[str, FleetRunResult]:
        results = {
            CoordinationPolicy.STOP_AND_WAIT.value: self.stop_and_wait,
            CoordinationPolicy.SPACE_TIME.value: self.space_time,
        }
        if self.rolling_horizon is not None:
            results[CoordinationPolicy.ROLLING_HORIZON.value] = self.rolling_horizon
        return results

    def delta(self, candidate: str, baseline: str) -> PolicyDelta | None:
        for item in self.deltas:
            if item.candidate == candidate and item.baseline == baseline:
                return item
        return None


def compare_policies(
    scenario: Scenario,
    config: SimulationConfig,
    *,
    bootstrap_samples: int = 10_000,
    policies: tuple[CoordinationPolicy, ...] = (
        CoordinationPolicy.STOP_AND_WAIT,
        CoordinationPolicy.SPACE_TIME,
        CoordinationPolicy.ROLLING_HORIZON,
    ),
) -> PolicyComparison:
    """Run the same workload under each policy and pair the shared outcomes.

    ``stop_and_wait`` is the baseline the problem statement names. Every other
    policy is reported against it, and the look-ahead policy is additionally
    reported against the greedy space-time auction so the contribution of the
    allocation layer alone is visible.
    """
    if bootstrap_samples <= 0:
        raise ValueError("bootstrap_samples must be positive")
    if not scenario.tasks:
        raise ValueError("policy comparison requires at least one task")
    required = {CoordinationPolicy.STOP_AND_WAIT, CoordinationPolicy.SPACE_TIME}
    if not required <= set(policies):
        raise ValueError("comparison requires the stop-and-wait and space-time arms")

    runs = {
        policy: FleetSimulation(
            scenario.warehouse_map,
            scenario.robots,
            config=replace(
                config,
                policy=policy,
                schedule_seed=config.schedule_seed or scenario.seed,
            ),
            conflict_zones=scenario.conflict_zones,
        ).run(scenario.tasks)
        for policy in policies
    }
    baseline_run = runs[CoordinationPolicy.STOP_AND_WAIT]

    pairs = [
        (candidate, CoordinationPolicy.STOP_AND_WAIT)
        for candidate in policies
        if candidate is not CoordinationPolicy.STOP_AND_WAIT
    ]
    if CoordinationPolicy.ROLLING_HORIZON in runs:
        pairs.append(
            (CoordinationPolicy.ROLLING_HORIZON, CoordinationPolicy.SPACE_TIME)
        )
    deltas = tuple(
        _delta(
            runs[candidate],
            runs[baseline],
            candidate=candidate.value,
            baseline=baseline.value,
            seed=scenario.seed,
            samples=bootstrap_samples,
        )
        for candidate, baseline in pairs
    )

    headline = next(
        item
        for item in deltas
        if item.candidate == CoordinationPolicy.SPACE_TIME.value
        and item.baseline == CoordinationPolicy.STOP_AND_WAIT.value
    )
    return PolicyComparison(
        space_time=runs[CoordinationPolicy.SPACE_TIME],
        stop_and_wait=baseline_run,
        rolling_horizon=runs.get(CoordinationPolicy.ROLLING_HORIZON),
        completion_rate_difference_percentage_points=(
            headline.completion_rate_difference_percentage_points
        ),
        throughput_relative_change_percent=headline.throughput_relative_change_percent,
        paired_completed_task_flow_ticks=headline.paired_completed_task_flow_ticks,
        deltas=deltas,
    )


def _delta(
    candidate_run: FleetRunResult,
    baseline_run: FleetRunResult,
    *,
    candidate: str,
    baseline: str,
    seed: int,
    samples: int,
) -> PolicyDelta:
    completion = 100.0 * (
        candidate_run.metrics.completed_tasks / candidate_run.metrics.task_count
        - baseline_run.metrics.completed_tasks / baseline_run.metrics.task_count
    )
    throughput = _relative_increase(
        baseline_run.metrics.throughput_per_simulated_minute,
        candidate_run.metrics.throughput_per_simulated_minute,
    )
    paired, baseline_mean, candidate_mean = _paired_flow_improvement(
        candidate_run, baseline_run, seed=seed, samples=samples
    )
    reduction = (
        None
        if baseline_mean is None or not baseline_mean
        else 100.0 * (baseline_mean - candidate_mean) / baseline_mean
    )
    return PolicyDelta(
        candidate=candidate,
        baseline=baseline,
        completion_rate_difference_percentage_points=completion,
        throughput_relative_change_percent=throughput,
        paired_completed_task_flow_ticks=paired,
        paired_mean_flow_reduction_percent=reduction,
        baseline_paired_mean_flow_ticks=baseline_mean,
        candidate_paired_mean_flow_ticks=candidate_mean,
    )


def _relative_increase(baseline: float, candidate: float) -> float | None:
    if baseline <= 0:
        return None
    return 100.0 * (candidate - baseline) / baseline


def _paired_flow_improvement(
    candidate: FleetRunResult,
    baseline: FleetRunResult,
    *,
    seed: int,
    samples: int,
) -> tuple[ConfidenceInterval | None, float | None, float | None]:
    candidate_flow = {
        outcome.task_id: outcome.finish_tick - outcome.release_tick
        for outcome in candidate.outcomes
        if outcome.finish_tick is not None
    }
    baseline_flow = {
        outcome.task_id: outcome.finish_tick - outcome.release_tick
        for outcome in baseline.outcomes
        if outcome.finish_tick is not None
    }
    task_ids = sorted(candidate_flow.keys() & baseline_flow.keys())
    if not task_ids:
        return None, None, None
    differences = [
        baseline_flow[task_id] - candidate_flow[task_id] for task_id in task_ids
    ]
    estimate = sum(differences) / len(differences)
    baseline_mean = sum(baseline_flow[task_id] for task_id in task_ids) / len(task_ids)
    candidate_mean = sum(candidate_flow[task_id] for task_id in task_ids) / len(
        task_ids
    )
    generator = random.Random(seed)
    means = sorted(
        sum(generator.choice(differences) for _ in differences) / len(differences)
        for _ in range(samples)
    )
    interval = ConfidenceInterval(
        lower=_quantile(means, 0.025),
        estimate=estimate,
        upper=_quantile(means, 0.975),
        paired_tasks=len(differences),
    )
    return interval, baseline_mean, candidate_mean


def _quantile(values: list[float], probability: float) -> float:
    index = probability * (len(values) - 1)
    lower = int(index)
    upper = min(lower + 1, len(values) - 1)
    fraction = index - lower
    return values[lower] * (1.0 - fraction) + values[upper] * fraction
