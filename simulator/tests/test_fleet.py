from __future__ import annotations

from pathlib import Path

from kinesis.domain import Cell, RobotState, Task
from kinesis.fleet import FleetSimulation, SimulationConfig
from kinesis.graph import WarehouseMap
from kinesis.operations import ConflictZone, Intervention, InterventionKind
from kinesis.scenario import load_scenario


SCENARIO = Path(__file__).parents[1] / "scenarios" / "warehouse-12.json"


def test_warehouse_twelve_executes_without_conflicts() -> None:
    scenario = load_scenario(SCENARIO)
    result = FleetSimulation(
        scenario.warehouse_map,
        scenario.robots,
        config=SimulationConfig(max_ticks=180, planning_horizon_ticks=180),
    ).run(scenario.tasks)

    assert len(scenario.robots) == 12
    assert result.metrics.completed_tasks >= 12
    assert result.metrics.executed_grid_vertex_conflicts == 0
    assert result.metrics.executed_grid_reverse_edge_conflicts == 0
    assert result.metrics.total_distance_cells > 0
    assert {assignment.task_id for assignment in result.assignments}


def test_fleet_run_is_deterministic() -> None:
    scenario = load_scenario(SCENARIO)
    config = SimulationConfig(max_ticks=180, planning_horizon_ticks=180)

    first = FleetSimulation(scenario.warehouse_map, scenario.robots, config=config).run(
        scenario.tasks
    )
    second = FleetSimulation(
        scenario.warehouse_map, scenario.robots, config=config
    ).run(scenario.tasks)

    assert first.metrics == second.metrics
    assert first.outcomes == second.outcomes
    assert first.assignments == second.assignments
    assert first.events.events == second.events.events


def test_idle_robot_holds_its_cell() -> None:
    warehouse = WarehouseMap(width=3, height=1)
    robots = (
        RobotState("moving", Cell(0, 0), 1.0),
        RobotState("parked", Cell(1, 0), 1.0),
    )
    task = Task("blocked", Cell(0, 0), Cell(2, 0), 0, 8)

    result = FleetSimulation(
        warehouse,
        robots,
        config=SimulationConfig(max_ticks=8, planning_horizon_ticks=8),
    ).run((task,))

    assert result.metrics.completed_tasks == 0
    assert result.metrics.executed_grid_vertex_conflicts == 0


def test_blocked_cell_invalidates_and_replans_an_active_route() -> None:
    warehouse = WarehouseMap(width=3, height=2)
    robot = RobotState("R1", Cell(0, 0), 1.0)
    task = Task("T1", Cell(0, 0), Cell(2, 0), 0, 12, service_ticks=0)
    blocked = Intervention(
        "blocked-aisle",
        1,
        InterventionKind.BLOCK_CELLS,
        cells=(Cell(1, 0),),
    )

    result = FleetSimulation(
        warehouse,
        (robot,),
        config=SimulationConfig(max_ticks=12, planning_horizon_ticks=12),
    ).run((task,), (blocked,))

    assert result.metrics.completed_tasks == 1
    assert result.metrics.executed_grid_vertex_conflicts == 0
    kinds = [event.kind for event in result.events.events]
    assert "cells_blocked" in kinds
    assert "task_requeued" in kinds
    assert any(
        event.kind == "robot_moved" and event.data["to"] == {"x": 0, "y": 1}
        for event in result.events.events
    )


def test_failed_robot_safe_stops_and_unstarted_task_is_reassigned() -> None:
    warehouse = WarehouseMap(width=4, height=2)
    robots = (
        RobotState("R1", Cell(0, 0), 1.0),
        RobotState("R2", Cell(0, 1), 1.0),
    )
    task = Task("T1", Cell(2, 0), Cell(3, 0), 0, 15, service_ticks=0)
    failure = Intervention(
        "failure-r1", 1, InterventionKind.ROBOT_FAILURE, robot_id="R1"
    )

    result = FleetSimulation(
        warehouse,
        robots,
        config=SimulationConfig(max_ticks=15, planning_horizon_ticks=15),
    ).run((task,), (failure,))

    assert result.metrics.completed_tasks == 1
    assert result.outcomes[0].robot_id == "R2"
    assert next(robot for robot in result.robots if robot.robot_id == "R1").mode.value == "safe_stop"
    assert any(event.kind == "robot_safe_stopped" for event in result.events.events)
    assert any(event.kind == "task_requeued" for event in result.events.events)


def test_low_battery_robot_requeues_work_until_charge_recovery() -> None:
    warehouse = WarehouseMap(width=4, height=2)
    robots = (
        RobotState("R1", Cell(0, 0), 1.0),
        RobotState("R2", Cell(0, 1), 1.0),
    )
    task = Task("T1", Cell(2, 0), Cell(3, 0), 0, 15, service_ticks=0)
    battery = Intervention(
        "battery-r1",
        1,
        InterventionKind.BATTERY_LOW,
        robot_id="R1",
        battery_soc=0.12,
        recover_tick=8,
        recovered_soc=0.9,
    )

    result = FleetSimulation(
        warehouse,
        robots,
        config=SimulationConfig(max_ticks=15, planning_horizon_ticks=15),
    ).run((task,), (battery,))

    assert result.metrics.completed_tasks == 1
    assert result.outcomes[0].robot_id == "R2"
    kinds = [event.kind for event in result.events.events]
    assert "robot_charge_requested" in kinds
    assert "robot_charge_completed" in kinds


def test_conflict_zone_emits_fenced_entry_and_physical_release() -> None:
    warehouse = WarehouseMap(width=4, height=1)
    robot = RobotState("R1", Cell(0, 0), 1.0)
    task = Task("T1", Cell(0, 0), Cell(3, 0), 0, 8, service_ticks=0)
    zone = ConflictZone("crossing-a", frozenset({Cell(1, 0)}))

    result = FleetSimulation(
        warehouse,
        (robot,),
        config=SimulationConfig(max_ticks=8, planning_horizon_ticks=8),
        conflict_zones=(zone,),
    ).run((task,))

    entries = [e for e in result.events.events if e.kind == "zone_lease_entered"]
    releases = [e for e in result.events.events if e.kind == "zone_lease_released"]
    assert len(entries) == 1
    assert len(releases) == 1
    assert entries[0].data["epoch"] == releases[0].data["epoch"]
