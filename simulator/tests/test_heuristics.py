import pytest

from kinesis.domain import Cell
from kinesis.graph import WarehouseMap
from kinesis.heuristics import DistanceOracle


def test_distance_follows_the_map_not_the_straight_line() -> None:
    warehouse = WarehouseMap(5, 3, frozenset({Cell(2, 0), Cell(2, 1)}))
    oracle = DistanceOracle(warehouse)

    assert Cell(0, 0).manhattan_distance(Cell(4, 0)) == 4
    assert oracle.distance(Cell(0, 0), Cell(4, 0)) == 8


def test_distance_is_zero_at_the_goal_and_symmetric_on_open_maps() -> None:
    oracle = DistanceOracle(WarehouseMap(4, 4))

    assert oracle.distance(Cell(2, 2), Cell(2, 2)) == 0
    assert oracle.distance(Cell(0, 0), Cell(3, 3)) == 6
    assert oracle.distance(Cell(3, 3), Cell(0, 0)) == 6


def test_separated_regions_report_no_distance() -> None:
    wall = frozenset({Cell(1, 0), Cell(1, 1), Cell(1, 2)})
    oracle = DistanceOracle(WarehouseMap(3, 3, wall))

    assert oracle.distance(Cell(0, 0), Cell(2, 2)) is None
    assert not oracle.reachable(Cell(0, 0), Cell(2, 2))


def test_fields_are_cached_per_goal() -> None:
    oracle = DistanceOracle(WarehouseMap(4, 4))

    first = oracle.field(Cell(1, 1))
    assert oracle.cached_goals == 1
    assert oracle.field(Cell(1, 1)) is first
    oracle.field(Cell(2, 2))
    assert oracle.cached_goals == 2


def test_blocked_goal_is_rejected() -> None:
    oracle = DistanceOracle(WarehouseMap(3, 3, frozenset({Cell(1, 1)})))

    with pytest.raises(ValueError, match="not traversable"):
        oracle.field(Cell(1, 1))


def test_distance_from_a_blocked_start_is_undefined() -> None:
    oracle = DistanceOracle(WarehouseMap(3, 3, frozenset({Cell(1, 1)})))

    assert oracle.distance(Cell(1, 1), Cell(0, 0)) is None
