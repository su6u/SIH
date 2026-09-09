import pytest

from swarmroute.domain import Cell, Task
from swarmroute.graph import WarehouseMap
from swarmroute.heuristics import DistanceOracle
from swarmroute.schedule import (
    RobotHorizon,
    RollingHorizonScheduler,
    ScheduleWeights,
)


def _scheduler(warehouse: WarehouseMap, **kwargs) -> RollingHorizonScheduler:
    return RollingHorizonScheduler(DistanceOracle(warehouse), **kwargs)


def test_route_ticks_covers_approach_haul_and_both_services() -> None:
    scheduler = _scheduler(WarehouseMap(10, 1))
    task = Task("T1", Cell(2, 0), Cell(6, 0), 0, 100, service_ticks=3)

    assert scheduler.route_ticks(Cell(0, 0), task) == 2 + 4 + 2 * 3


def test_route_ticks_is_none_when_the_haul_is_unreachable() -> None:
    wall = frozenset({Cell(1, 0), Cell(1, 1), Cell(1, 2)})
    scheduler = _scheduler(WarehouseMap(3, 3, wall))
    task = Task("T1", Cell(0, 0), Cell(2, 2), 0, 100)

    assert scheduler.route_ticks(Cell(0, 0), task) is None


def test_a_robot_finishing_soon_beats_an_idle_robot_that_is_far_away() -> None:
    scheduler = _scheduler(WarehouseMap(20, 1))
    # near_soon is busy until tick 4 but parks next to the pickup; far_now is
    # free immediately and nineteen cells away.
    horizons = (
        RobotHorizon("near_soon", Cell(9, 0), 4),
        RobotHorizon("far_now", Cell(19, 0), 0),
    )
    task = Task("T1", Cell(8, 0), Cell(2, 0), 0, 100, service_ticks=1)

    schedule = scheduler.solve(horizons, (task,), current_tick=0)

    assert schedule.entries["T1"].robot_id == "near_soon"
    assert schedule.entries["T1"].finish_tick == 4 + 1 + 6 + 2


def test_regret_clearing_spreads_work_across_robots() -> None:
    scheduler = _scheduler(WarehouseMap(12, 3))
    horizons = (
        RobotHorizon("R1", Cell(0, 0), 0),
        RobotHorizon("R2", Cell(11, 2), 0),
    )
    tasks = (
        Task("near_R1", Cell(1, 0), Cell(2, 0), 0, 200),
        Task("near_R2", Cell(10, 2), Cell(9, 2), 0, 200),
    )

    schedule = scheduler.solve(horizons, tasks, current_tick=0)

    assert schedule.entries["near_R1"].robot_id == "R1"
    assert schedule.entries["near_R2"].robot_id == "R2"


def test_tasks_beyond_a_robot_payload_capacity_are_left_unassigned() -> None:
    scheduler = _scheduler(WarehouseMap(6, 1))
    horizons = (RobotHorizon("R1", Cell(0, 0), 0, payload_capacity_kg=100.0),)
    tasks = (Task("heavy", Cell(1, 0), Cell(4, 0), 0, 100, payload_kg=500.0),)

    schedule = scheduler.solve(horizons, tasks, current_tick=0)

    assert schedule.unassigned == ("heavy",)
    assert schedule.entries == {}


def test_improvement_never_worsens_the_objective_and_is_reproducible() -> None:
    warehouse = WarehouseMap(24, 5)
    horizons = tuple(RobotHorizon(f"R{i}", Cell(i, 0), 0) for i in range(3))
    tasks = tuple(
        Task(f"T{i}", Cell(2 + i, 2), Cell(20 - i, 4), 0, 400, service_ticks=1)
        for i in range(9)
    )
    plain = _scheduler(warehouse, improvement_steps=0, seed=11).solve(
        horizons, tasks, current_tick=0
    )
    improved = _scheduler(warehouse, improvement_steps=500, seed=11).solve(
        horizons, tasks, current_tick=0
    )
    again = _scheduler(warehouse, improvement_steps=500, seed=11).solve(
        horizons, tasks, current_tick=0
    )

    assert improved.objective <= plain.objective
    assert improved.sequences == again.sequences


def test_every_task_is_placed_exactly_once() -> None:
    scheduler = _scheduler(WarehouseMap(16, 4), improvement_steps=300, seed=3)
    horizons = tuple(RobotHorizon(f"R{i}", Cell(i, 0), i) for i in range(4))
    tasks = tuple(
        Task(f"T{i}", Cell(1 + i, 1), Cell(14 - i, 3), 0, 400) for i in range(10)
    )

    schedule = scheduler.solve(horizons, tasks, current_tick=0)

    placed = [
        task_id for sequence in schedule.sequences.values() for task_id in sequence
    ]
    assert sorted(placed) == sorted(task.task_id for task in tasks)
    assert len(placed) == len(set(placed))


def test_release_and_current_tick_delay_the_start() -> None:
    scheduler = _scheduler(WarehouseMap(8, 1))
    horizon = RobotHorizon("R1", Cell(0, 0), 0)
    task = Task("late", Cell(1, 0), Cell(3, 0), 40, 200, service_ticks=0)

    assert scheduler.finish_tick(horizon, task, current_tick=0) == 40 + 1 + 2


def test_weights_and_steps_are_validated() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        ScheduleWeights(makespan=-1.0)
    with pytest.raises(ValueError, match="makespan or flow"):
        ScheduleWeights(makespan=0.0, flow=0.0)
    with pytest.raises(ValueError, match="improvement_steps"):
        _scheduler(WarehouseMap(3, 3), improvement_steps=-1)


def test_empty_inputs_produce_an_empty_schedule() -> None:
    scheduler = _scheduler(WarehouseMap(4, 4))

    assert scheduler.solve((), (), current_tick=0).sequences == {}
    assert scheduler.solve(
        (RobotHorizon("R1", Cell(0, 0), 0),), (), current_tick=0
    ).entries == {}
