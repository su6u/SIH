from __future__ import annotations

from dataclasses import dataclass

from .domain import Cell


@dataclass(frozen=True, slots=True)
class WarehouseMap:
    width: int
    height: int
    blocked: frozenset[Cell] = frozenset()
    version: str = "map-v1"

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("map dimensions must be positive")
        if not self.version:
            raise ValueError("map version must not be empty")
        invalid = [cell for cell in self.blocked if not self.contains(cell)]
        if invalid:
            raise ValueError(f"blocked cells outside map: {invalid}")

    def contains(self, cell: Cell) -> bool:
        return 0 <= cell.x < self.width and 0 <= cell.y < self.height

    def traversable(self, cell: Cell) -> bool:
        return self.contains(cell) and cell not in self.blocked

    def neighbors(self, cell: Cell, *, include_wait: bool = False) -> tuple[Cell, ...]:
        candidates = (
            Cell(cell.x, cell.y - 1),
            Cell(cell.x - 1, cell.y),
            Cell(cell.x + 1, cell.y),
            Cell(cell.x, cell.y + 1),
        )
        result = tuple(
            candidate for candidate in candidates if self.traversable(candidate)
        )
        return result + ((cell,) if include_wait else ())
