from __future__ import annotations

from collections import deque

from .domain import Cell
from .graph import WarehouseMap

UNREACHABLE = -1


class DistanceOracle:
    """Exact obstacle-aware cost-to-go on a static map.

    A backward breadth-first search from a goal labels every cell with the true
    number of moves needed to reach that goal. The label is an admissible and
    consistent heuristic for :class:`~kinesis.planner.SpaceTimeAStar`, so the
    planner keeps returning time-optimal plans while expanding far fewer states
    than the Manhattan estimate does around rack blocks. The same field doubles
    as an O(1) route-cost estimate for allocation screening.

    Fields are computed once per goal and cached. The oracle is bound to one
    map version; build a new oracle when the map changes.
    """

    __slots__ = ("_map", "_width", "_height", "_fields")

    def __init__(self, warehouse_map: WarehouseMap) -> None:
        self._map = warehouse_map
        self._width = warehouse_map.width
        self._height = warehouse_map.height
        self._fields: dict[Cell, tuple[int, ...]] = {}

    @property
    def warehouse_map(self) -> WarehouseMap:
        return self._map

    @property
    def cached_goals(self) -> int:
        return len(self._fields)

    def field(self, goal: Cell) -> tuple[int, ...]:
        """Cost-to-go for every cell, indexed by ``y * width + x``."""
        cached = self._fields.get(goal)
        if cached is not None:
            return cached
        if not self._map.traversable(goal):
            raise ValueError(f"goal {goal} is not traversable")
        width, height = self._width, self._height
        labels = [UNREACHABLE] * (width * height)
        labels[goal.y * width + goal.x] = 0
        frontier = deque([goal])
        blocked = self._map.blocked
        while frontier:
            cell = frontier.popleft()
            next_cost = labels[cell.y * width + cell.x] + 1
            for neighbour in (
                Cell(cell.x, cell.y - 1),
                Cell(cell.x - 1, cell.y),
                Cell(cell.x + 1, cell.y),
                Cell(cell.x, cell.y + 1),
            ):
                if not (0 <= neighbour.x < width and 0 <= neighbour.y < height):
                    continue
                if neighbour in blocked:
                    continue
                index = neighbour.y * width + neighbour.x
                if labels[index] != UNREACHABLE:
                    continue
                labels[index] = next_cost
                frontier.append(neighbour)
        field = tuple(labels)
        self._fields[goal] = field
        return field

    def distance(self, start: Cell, goal: Cell) -> int | None:
        """Exact move count from ``start`` to ``goal``, or ``None`` if separated."""
        if not self._map.traversable(start):
            return None
        cost = self.field(goal)[start.y * self._width + start.x]
        return None if cost == UNREACHABLE else cost

    def reachable(self, start: Cell, goal: Cell) -> bool:
        return self.distance(start, goal) is not None
