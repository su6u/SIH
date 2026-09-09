from __future__ import annotations

import random

from swarmroute.domain import Cell, Plan, PlanStep
from swarmroute.graph import WarehouseMap
from swarmroute.heuristics import DistanceOracle
from swarmroute.planner import NoPathError, SpaceTimeAStar
from swarmroute.reservations import ReservationTable
from swarmroute.sipp import SafeIntervalSearch


def _search(warehouse: WarehouseMap, table: ReservationTable) -> SafeIntervalSearch:
    return SafeIntervalSearch(warehouse, table, DistanceOracle(warehouse))


def test_free_corridor_is_traversed_without_waiting() -> None:
    warehouse = WarehouseMap(4, 1)
    steps = _search(warehouse, ReservationTable()).plan(
        "R1", Cell(0, 0), Cell(3, 0), start_tick=0, max_tick=10
    )

    assert steps is not None
    assert [(step.cell.x, step.tick) for step in steps] == [(0, 0), (1, 1), (2, 2), (3, 3)]


def test_search_waits_out_a_reserved_vertex() -> None:
    table = ReservationTable()
    table.commit(
        Plan.from_steps("R1", [PlanStep(Cell(1, 0), 1), PlanStep(Cell(2, 0), 2)])
    )
    steps = _search(WarehouseMap(3, 1), table).plan(
        "R2", Cell(0, 0), Cell(2, 0), start_tick=0, max_tick=5
    )

    assert steps is not None
    assert steps[0] == PlanStep(Cell(0, 0), 0)
    assert steps[1] == PlanStep(Cell(0, 0), 1)
    assert steps[-1] == PlanStep(Cell(2, 0), 3)


def test_head_on_swap_is_refused() -> None:
    table = ReservationTable()
    table.commit(
        Plan.from_steps("R1", [PlanStep(Cell(1, 0), 0), PlanStep(Cell(0, 0), 1)])
    )
    steps = _search(WarehouseMap(2, 2), table).plan(
        "R2", Cell(0, 0), Cell(1, 0), start_tick=0, max_tick=6
    )

    assert steps is not None
    # Going straight across at tick 0 would swap with R1, so the route detours
    # through the second row or waits, but never crosses that edge at tick 0.
    assert (steps[0].cell, steps[1].cell) != (Cell(0, 0), Cell(1, 0))


def test_a_reserved_start_cell_has_no_plan() -> None:
    table = ReservationTable()
    table.commit(Plan.from_steps("R1", [PlanStep(Cell(0, 0), 0)]))
    steps = _search(WarehouseMap(3, 1), table).plan(
        "R2", Cell(0, 0), Cell(2, 0), start_tick=0, max_tick=5
    )

    assert steps is None


def test_unreachable_goal_has_no_plan() -> None:
    wall = frozenset({Cell(1, 0), Cell(1, 1), Cell(1, 2)})
    steps = _search(WarehouseMap(3, 3, wall), ReservationTable()).plan(
        "R1", Cell(0, 0), Cell(2, 2), start_tick=0, max_tick=20
    )

    assert steps is None


def test_horizon_too_short_has_no_plan() -> None:
    steps = _search(WarehouseMap(8, 1), ReservationTable()).plan(
        "R1", Cell(0, 0), Cell(7, 0), start_tick=0, max_tick=3
    )

    assert steps is None


def test_matches_the_time_expanded_search_on_random_instances() -> None:
    """The two searches must agree on every optimal arrival tick.

    Safe-interval search is only worth having if it is the same planner with a
    smaller state space, so this compares it against the reference search over
    randomised maps, reservations and horizons rather than trusting a handful
    of hand-written cases.
    """
    generator = random.Random(12345)
    compared = 0
    for _ in range(400):
        width, height = generator.randint(3, 8), generator.randint(2, 6)
        blocked = frozenset(
            Cell(generator.randrange(width), generator.randrange(height))
            for _ in range(generator.randint(0, (width * height) // 4))
        )
        warehouse = WarehouseMap(width, height, blocked)
        free = [
            Cell(x, y)
            for y in range(height)
            for x in range(width)
            if warehouse.traversable(Cell(x, y))
        ]
        if len(free) < 2:
            continue
        table = ReservationTable()
        for index in range(generator.randint(0, 4)):
            cell = generator.choice(free)
            first = generator.randint(0, 6)
            steps = [PlanStep(cell, first)]
            for tick in range(first + 1, first + generator.randint(1, 8)):
                cell = generator.choice(warehouse.neighbors(cell, include_wait=True))
                steps.append(PlanStep(cell, tick))
            table.commit(Plan.from_steps(f"other{index}", steps))

        start, goal = generator.sample(free, 2)
        start_tick = generator.randint(0, 4)
        max_tick = start_tick + generator.randint(1, 25)
        oracle = DistanceOracle(warehouse)
        reference = SpaceTimeAStar(warehouse, table, distances=oracle)
        # The reference planner must run its own time-expanded search here.
        reference._safe_intervals = None  # noqa: SLF001 - differential test
        try:
            expected = reference.plan(
                "ME", start, goal, start_tick=start_tick, max_tick=max_tick
            ).end.tick
        except NoPathError:
            expected = None
        found = SafeIntervalSearch(warehouse, table, oracle).plan(
            "ME", start, goal, start_tick=start_tick, max_tick=max_tick
        )
        actual = found[-1].tick if found else None

        assert actual == expected, (start, goal, start_tick, max_tick)
        if found is not None:
            plan = Plan.from_steps("ME", found)
            assert plan.start.tick == start_tick
            assert plan.end.cell == goal
            assert table.conflicts_for(plan) == ()
            compared += 1
    assert compared > 100
