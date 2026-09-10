from kinesis.domain import Cell, Plan, PlanStep
from kinesis.graph import WarehouseMap
from kinesis.planner import SpaceTimeAStar
from kinesis.reservations import ConflictKind, ReservationTable


def test_space_time_astar_returns_shortest_unblocked_path() -> None:
    warehouse = WarehouseMap(4, 3, frozenset({Cell(1, 1)}))
    planner = SpaceTimeAStar(warehouse, ReservationTable())

    plan = planner.plan("R1", Cell(0, 1), Cell(3, 1), start_tick=0, max_tick=10)

    assert plan.start == PlanStep(Cell(0, 1), 0)
    assert plan.end.cell == Cell(3, 1)
    assert plan.move_count == 5


def test_planner_waits_to_avoid_a_reserved_vertex() -> None:
    reservations = ReservationTable()
    reservations.commit(
        Plan.from_steps("R1", [PlanStep(Cell(1, 0), 1), PlanStep(Cell(2, 0), 2)])
    )
    planner = SpaceTimeAStar(WarehouseMap(3, 1), reservations)

    plan = planner.plan("R2", Cell(0, 0), Cell(2, 0), start_tick=0, max_tick=5)

    assert plan.steps[:2] == (PlanStep(Cell(0, 0), 0), PlanStep(Cell(0, 0), 1))
    assert plan.end.tick == 3


def test_reverse_edge_traversal_is_rejected() -> None:
    reservations = ReservationTable()
    committed = Plan.from_steps(
        "R1", [PlanStep(Cell(0, 0), 0), PlanStep(Cell(1, 0), 1)]
    )
    assert reservations.commit(committed) == ()

    opposing = Plan.from_steps("R2", [PlanStep(Cell(1, 0), 0), PlanStep(Cell(0, 0), 1)])
    conflicts = reservations.conflicts_for(opposing)

    assert any(conflict.kind is ConflictKind.REVERSE_EDGE for conflict in conflicts)


def test_failed_plan_commit_is_atomic() -> None:
    reservations = ReservationTable()
    reservations.commit(Plan.from_steps("R1", [PlanStep(Cell(1, 0), 1)]))
    before = reservations.vertex_count
    conflicting = Plan.from_steps(
        "R2",
        [PlanStep(Cell(0, 0), 0), PlanStep(Cell(1, 0), 1), PlanStep(Cell(2, 0), 2)],
    )

    assert reservations.commit(conflicting)
    assert reservations.vertex_count == before
    assert reservations.vertex_owner(Cell(0, 0), 0) is None


def test_multi_tick_moves_hold_the_source_until_the_transition_tick() -> None:
    planner = SpaceTimeAStar(WarehouseMap(2, 1), ReservationTable(), move_ticks=3)

    plan = planner.plan("R1", Cell(0, 0), Cell(1, 0), start_tick=0, max_tick=3)

    assert plan.steps == (
        PlanStep(Cell(0, 0), 0),
        PlanStep(Cell(0, 0), 1),
        PlanStep(Cell(0, 0), 2),
        PlanStep(Cell(1, 0), 3),
    )


def test_swept_clearance_rejects_corner_cut_between_distinct_vertices() -> None:
    reservations = ReservationTable(clearance_cells=1.4 / 1.5)
    leader = Plan.from_steps("R1", [PlanStep(Cell(0, 0), 0), PlanStep(Cell(1, 0), 1)])
    assert not reservations.commit(leader)
    follower = Plan.from_steps("R2", [PlanStep(Cell(0, 1), 0), PlanStep(Cell(0, 0), 1)])
    assert reservations.conflicts_for(follower)
    planner = SpaceTimeAStar(WarehouseMap(3, 3), reservations)
    result = planner.plan("R2", Cell(0, 1), Cell(0, 0), start_tick=0, max_tick=5)
    assert result.end.tick > 1
    assert not reservations.commit(result)
    reservations.release("R1")
    assert reservations.can_traverse("R2", Cell(0, 1), Cell(0, 0), 0)


def test_swept_clearance_preserves_parallel_motion() -> None:
    reservations = ReservationTable(clearance_cells=1.4 / 1.5)
    assert not reservations.commit(Plan.from_steps("R1", [PlanStep(Cell(0, 0), 0), PlanStep(Cell(1, 0), 1)]))
    assert reservations.can_traverse("R2", Cell(0, 1), Cell(1, 1), 0)
