import pytest

from kinesis.comparison import compare_policies
from kinesis.domain import Cell, RobotState, Task
from kinesis.fleet import CoordinationPolicy, SimulationConfig
from kinesis.graph import WarehouseMap
from kinesis.scenario import Scenario


def test_policy_comparison_uses_paired_task_outcomes() -> None:
    scenario = Scenario(
        "comparison",
        WarehouseMap(5, 2),
        (
            RobotState("R1", Cell(0, 0), 1.0),
            RobotState("R2", Cell(0, 1), 1.0),
        ),
        (
            Task("T1", Cell(1, 0), Cell(4, 0), 0, 30),
            Task("T2", Cell(1, 1), Cell(4, 1), 0, 30),
        ),
        17,
    )

    result = compare_policies(
        scenario,
        SimulationConfig(max_ticks=30, planning_horizon_ticks=30),
        bootstrap_samples=200,
    )

    assert result.space_time.metrics.completed_tasks == 2
    assert result.stop_and_wait.metrics.completed_tasks == 2
    assert result.paired_completed_task_flow_ticks is not None
    assert result.paired_completed_task_flow_ticks.paired_tasks == 2
    assert result.completion_rate_difference_percentage_points == 0.0
    assert result.throughput_relative_change_percent is not None


def test_policy_comparison_rejects_empty_task_sets() -> None:
    scenario = Scenario(
        "empty",
        WarehouseMap(2, 1),
        (RobotState("R1", Cell(0, 0), 1.0),),
        (),
        1,
    )

    with pytest.raises(ValueError, match="at least one task"):
        compare_policies(scenario, SimulationConfig(), bootstrap_samples=10)


def test_comparison_reports_every_policy_and_the_graded_reduction() -> None:
    scenario = Scenario(
        "three-arm",
        WarehouseMap(6, 3),
        (
            RobotState("R1", Cell(0, 0), 1.0),
            RobotState("R2", Cell(0, 2), 1.0),
        ),
        (
            Task("T1", Cell(1, 0), Cell(5, 0), 0, 40),
            Task("T2", Cell(1, 2), Cell(5, 2), 0, 40),
        ),
        23,
    )

    result = compare_policies(
        scenario,
        SimulationConfig(max_ticks=40, planning_horizon_ticks=40),
        bootstrap_samples=200,
    )

    assert result.rolling_horizon is not None
    assert set(result.runs) == {
        CoordinationPolicy.STOP_AND_WAIT.value,
        CoordinationPolicy.SPACE_TIME.value,
        CoordinationPolicy.ROLLING_HORIZON.value,
    }
    graded = result.delta(
        CoordinationPolicy.ROLLING_HORIZON.value,
        CoordinationPolicy.STOP_AND_WAIT.value,
    )
    assert graded is not None
    assert graded.paired_mean_flow_reduction_percent is not None
    assert graded.baseline_paired_mean_flow_ticks is not None
    assert graded.candidate_paired_mean_flow_ticks is not None


def test_comparison_requires_the_two_reference_arms() -> None:
    scenario = Scenario(
        "one-arm",
        WarehouseMap(4, 1),
        (RobotState("R1", Cell(0, 0), 1.0),),
        (Task("T1", Cell(1, 0), Cell(3, 0), 0, 20),),
        1,
    )

    with pytest.raises(ValueError, match="stop-and-wait and space-time"):
        compare_policies(
            scenario,
            SimulationConfig(max_ticks=20, planning_horizon_ticks=20),
            policies=(CoordinationPolicy.SPACE_TIME,),
        )
