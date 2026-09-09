from __future__ import annotations

from swarmroute.domain import Cell, RobotState, Task
from swarmroute.fleet import CoordinationPolicy, FleetSimulation, SimulationConfig
from swarmroute.graph import WarehouseMap


def test_an_idle_robot_steps_off_an_endpoint_another_order_still_needs() -> None:
    """Parking on a shared pickup or drop-off deadlocks the remaining work."""
    warehouse = WarehouseMap(7, 3)
    robots = (
        RobotState("first", Cell(0, 0), 1.0),
        RobotState("second", Cell(0, 2), 1.0),
    )
    # Both orders drop at the same cell. Without evacuation the first robot
    # parks on it for the rest of the run and the second order can never land.
    tasks = (
        Task("early", Cell(2, 0), Cell(6, 1), 0, 60, service_ticks=0),
        Task("late", Cell(2, 2), Cell(6, 1), 20, 60, service_ticks=0),
    )
    result = FleetSimulation(
        warehouse,
        robots,
        config=SimulationConfig(max_ticks=60, planning_horizon_ticks=60),
    ).run(tasks)

    assert result.metrics.completed_tasks == 2
    assert result.metrics.expired_tasks == 0
    assert any(event.kind == "endpoint_vacated" for event in result.events.events)
    assert result.metrics.executed_grid_vertex_conflicts == 0


def test_robots_do_not_vacate_once_every_order_is_done() -> None:
    warehouse = WarehouseMap(6, 2)
    robots = (RobotState("only", Cell(0, 0), 1.0),)
    tasks = (Task("single", Cell(1, 0), Cell(4, 0), 0, 40, service_ticks=0),)

    result = FleetSimulation(
        warehouse,
        robots,
        config=SimulationConfig(max_ticks=40, planning_horizon_ticks=40),
    ).run(tasks)

    assert result.metrics.completed_tasks == 1
    # The drop-off belongs to no outstanding order once it is delivered, so
    # there is nothing to step aside for.
    assert not any(event.kind == "endpoint_vacated" for event in result.events.events)


def test_no_plan_is_awarded_past_the_reservation_horizon() -> None:
    """Reservations only run to ``max_ticks``; plans must not outlive them.

    A robot parked on the goal holds it to the end of the run. Planning beyond
    that point would let a bidder "wait out" the parking tail and call the
    result a route, which is a plan that only works because the simulation
    stopped.
    """
    warehouse = WarehouseMap(5, 1)
    robots = (
        RobotState("blocker", Cell(4, 0), 1.0),
        RobotState("mover", Cell(0, 0), 1.0),
    )
    tasks = (Task("blocked", Cell(1, 0), Cell(4, 0), 0, 200, service_ticks=0),)

    result = FleetSimulation(
        warehouse,
        robots,
        config=SimulationConfig(max_ticks=30, planning_horizon_ticks=200),
    ).run(tasks)

    for assignment in result.assignments:
        assert assignment.finish_tick <= 30
    assert result.metrics.executed_grid_vertex_conflicts == 0


def test_every_policy_keeps_its_conflict_guarantee_under_endpoint_pressure() -> None:
    warehouse = WarehouseMap(9, 5)
    robots = tuple(RobotState(f"R{i}", Cell(0, i), 1.0) for i in range(4))
    # Four orders sharing two endpoints, with only four robots to hold them.
    tasks = tuple(
        Task(
            f"T{i}",
            Cell(3, 1) if i % 2 else Cell(3, 3),
            Cell(8, 1) if i % 2 else Cell(8, 3),
            4 * i,
            120,
            service_ticks=1,
        )
        for i in range(4)
    )
    for policy in CoordinationPolicy:
        result = FleetSimulation(
            warehouse,
            robots,
            config=SimulationConfig(
                max_ticks=120, planning_horizon_ticks=120, policy=policy
            ),
        ).run(tasks)

        assert result.metrics.executed_grid_vertex_conflicts == 0, policy
        assert result.metrics.executed_grid_reverse_edge_conflicts == 0, policy
