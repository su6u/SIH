from __future__ import annotations

from operator import attrgetter
from pathlib import Path

import pytest

from kinesis.domain import Cell, RobotState, Task
from kinesis.fleet import CoordinationPolicy, SimulationConfig
from kinesis.graph import WarehouseMap
from kinesis.heuristics import DistanceOracle
from kinesis.scenario import Scenario, load_scenario
from kinesis.trials import randomize_scenario, run_trials

SCENARIO = Path(__file__).parents[1] / "scenarios" / "warehouse-12.json"


def _small_scenario() -> Scenario:
    return Scenario(
        "trial-fixture",
        WarehouseMap(9, 5, frozenset({Cell(4, 1), Cell(4, 3)})),
        tuple(RobotState(f"R{i}", Cell(0, i), 1.0) for i in range(3)),
        tuple(
            Task(f"T{i}", Cell(2, 1), Cell(7, 3), 2 * i, 90, service_ticks=1)
            for i in range(4)
        ),
        41,
    )


def test_randomised_layout_keeps_the_workload_shape() -> None:
    base = load_scenario(SCENARIO)
    variant = randomize_scenario(base, seed=99)

    assert len(variant.robots) == len(base.robots)
    assert len(variant.tasks) == len(base.tasks)
    assert variant.warehouse_map == base.warehouse_map
    by_id = attrgetter("task_id")
    assert [task.release_tick for task in sorted(variant.tasks, key=by_id)] == [
        task.release_tick for task in sorted(base.tasks, key=by_id)
    ]
    assert variant.seed == 99


def test_randomised_layout_is_valid_and_reproducible() -> None:
    base = load_scenario(SCENARIO)
    variant = randomize_scenario(base, seed=7)
    oracle = DistanceOracle(variant.warehouse_map)

    assert len({robot.cell for robot in variant.robots}) == len(variant.robots)
    for robot in variant.robots:
        assert variant.warehouse_map.traversable(robot.cell)
    for task in variant.tasks:
        assert variant.warehouse_map.traversable(task.pickup)
        assert variant.warehouse_map.traversable(task.dropoff)
        assert oracle.reachable(task.pickup, task.dropoff)

    assert randomize_scenario(base, seed=7).tasks == variant.tasks


def test_different_seeds_give_different_layouts() -> None:
    base = load_scenario(SCENARIO)

    first = randomize_scenario(base, seed=1)
    second = randomize_scenario(base, seed=2)

    assert first.tasks != second.tasks


def test_trial_report_summarises_every_policy_pair() -> None:
    report = run_trials(
        _small_scenario(),
        SimulationConfig(max_ticks=90, planning_horizon_ticks=90),
        trials=3,
        seed=5,
        bootstrap_samples=100,
    )

    assert report.trials == 3
    assert len(report.results) == 3
    assert {result.seed for result in report.results} != {5}
    names = set(report.completed_tasks)
    assert names == {
        CoordinationPolicy.STOP_AND_WAIT.value,
        CoordinationPolicy.SPACE_TIME.value,
        CoordinationPolicy.ROLLING_HORIZON.value,
    }
    pair = report.pair(
        CoordinationPolicy.ROLLING_HORIZON.value,
        CoordinationPolicy.STOP_AND_WAIT.value,
    )
    assert pair is not None
    assert pair.paired_mean_flow_reduction_percent.samples == 3
    assert (
        pair.paired_mean_flow_reduction_percent.lower
        <= pair.paired_mean_flow_reduction_percent.mean
        <= pair.paired_mean_flow_reduction_percent.upper
    )
    assert 0 <= pair.trials_meeting_twenty_percent_target <= 3
    assert report.executed_conflicts[CoordinationPolicy.ROLLING_HORIZON.value] == 0


def test_trial_count_is_validated() -> None:
    with pytest.raises(ValueError, match="trials must be positive"):
        run_trials(_small_scenario(), SimulationConfig(), trials=0)
