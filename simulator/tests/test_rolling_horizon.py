from __future__ import annotations

from pathlib import Path

from kinesis.domain import Cell, RobotState, Task
from kinesis.fleet import CoordinationPolicy, FleetSimulation, SimulationConfig
from kinesis.graph import WarehouseMap
from kinesis.scenario import load_scenario

SCENARIO = Path(__file__).parents[1] / "scenarios" / "warehouse-12.json"


def _config(**kwargs) -> SimulationConfig:
    return SimulationConfig(
        max_ticks=180,
        planning_horizon_ticks=180,
        policy=CoordinationPolicy.ROLLING_HORIZON,
        schedule_seed=20260904,
        **kwargs,
    )


def _run(config: SimulationConfig):
    scenario = load_scenario(SCENARIO)
    return FleetSimulation(
        scenario.warehouse_map,
        scenario.robots,
        config=config,
        conflict_zones=scenario.conflict_zones,
    ).run(scenario.tasks)


def test_rolling_horizon_executes_without_conflicts() -> None:
    result = _run(_config())

    assert result.metrics.completed_tasks == result.metrics.task_count
    assert result.metrics.executed_grid_vertex_conflicts == 0
    assert result.metrics.executed_grid_reverse_edge_conflicts == 0
    assert result.metrics.deadline_misses == 0


def test_rolling_horizon_is_deterministic() -> None:
    first = _run(_config())
    second = _run(_config())

    assert first.metrics == second.metrics
    assert first.outcomes == second.outcomes
    assert first.assignments == second.assignments


def test_rolling_horizon_beats_the_greedy_auction_on_flow_and_distance() -> None:
    scenario = load_scenario(SCENARIO)

    def run(policy: CoordinationPolicy):
        return FleetSimulation(
            scenario.warehouse_map,
            scenario.robots,
            config=SimulationConfig(
                max_ticks=180,
                planning_horizon_ticks=180,
                policy=policy,
                schedule_seed=scenario.seed,
            ),
            conflict_zones=scenario.conflict_zones,
        ).run(scenario.tasks)

    greedy = run(CoordinationPolicy.SPACE_TIME)
    lookahead = run(CoordinationPolicy.ROLLING_HORIZON)

    assert lookahead.metrics.completed_tasks >= greedy.metrics.completed_tasks
    assert lookahead.metrics.mean_flow_ticks < greedy.metrics.mean_flow_ticks
    assert lookahead.metrics.total_distance_cells < greedy.metrics.total_distance_cells


def test_look_ahead_waits_for_the_robot_that_will_be_closest() -> None:
    """A robot two ticks from finishing should out-bid a distant idle robot."""
    warehouse = WarehouseMap(22, 1)
    robots = (
        # busy_near is already carrying work that ends beside the second pickup
        RobotState("busy_near", Cell(0, 0), 1.0),
        RobotState("far_idle", Cell(21, 0), 1.0),
    )
    tasks = (
        Task("first", Cell(1, 0), Cell(9, 0), 0, 200, service_ticks=0),
        Task("second", Cell(10, 0), Cell(14, 0), 6, 200, service_ticks=0),
    )
    result = FleetSimulation(
        warehouse,
        robots,
        config=SimulationConfig(
            max_ticks=120,
            planning_horizon_ticks=120,
            policy=CoordinationPolicy.ROLLING_HORIZON,
        ),
    ).run(tasks)

    awarded = {item.task_id: item.robot_id for item in result.assignments}
    assert awarded["first"] == "busy_near"
    assert awarded["second"] == "busy_near"
    assert result.metrics.completed_tasks == 2


def test_a_task_the_schedule_cannot_place_still_reaches_an_idle_robot() -> None:
    """Anti-starvation: unschedulable work is opened up to whoever is free."""
    warehouse = WarehouseMap(8, 2)
    robots = (
        RobotState("light", Cell(0, 0), 1.0, payload_capacity_kg=50.0),
        RobotState("heavy", Cell(0, 1), 1.0, payload_capacity_kg=900.0),
    )
    tasks = (Task("bulk", Cell(3, 1), Cell(6, 1), 0, 80, payload_kg=800.0),)

    result = FleetSimulation(
        warehouse,
        robots,
        config=SimulationConfig(
            max_ticks=60,
            planning_horizon_ticks=60,
            policy=CoordinationPolicy.ROLLING_HORIZON,
        ),
    ).run(tasks)

    assert result.metrics.completed_tasks == 1
    assert result.assignments[0].robot_id == "heavy"


def test_schedule_knobs_are_validated() -> None:
    import pytest

    with pytest.raises(ValueError, match="schedule_improvement_steps"):
        SimulationConfig(schedule_improvement_steps=-1)
    with pytest.raises(ValueError, match="schedule_shortlist"):
        SimulationConfig(schedule_shortlist=0)
