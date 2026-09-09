from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .domain import Cell, Plan


class ConflictKind(StrEnum):
    VERTEX = "vertex"
    REVERSE_EDGE = "reverse_edge"
    EDGE = "edge"


@dataclass(frozen=True, slots=True)
class ReservationConflict:
    kind: ConflictKind
    tick: int
    owner_id: str
    cell: Cell | None = None
    edge: tuple[Cell, Cell] | None = None


class ReservationTable:
    def __init__(self, *, clearance_cells: float = 0.0) -> None:
        if not 0 <= clearance_cells <= 1:
            raise ValueError("clearance_cells must be in [0, 1]")
        self.clearance_cells = clearance_cells
        self._motions: dict[int, dict[str, tuple[Cell, Cell]]] = {}
        self._vertices: dict[tuple[Cell, int], str] = {}
        self._edges: dict[tuple[Cell, Cell, int], str] = {}

    def vertex_owner(self, cell: Cell, tick: int) -> str | None:
        return self._vertices.get((cell, tick))

    def edge_owner(self, start: Cell, end: Cell, tick: int) -> str | None:
        return self._edges.get((start, end, tick))

    def conflicts_for(self, plan: Plan) -> tuple[ReservationConflict, ...]:
        conflicts: list[ReservationConflict] = []
        for step in plan.steps:
            owner = self.vertex_owner(step.cell, step.tick)
            if owner is not None and owner != plan.robot_id:
                conflicts.append(
                    ReservationConflict(
                        ConflictKind.VERTEX, step.tick, owner, cell=step.cell
                    )
                )

        for previous, current in zip(plan.steps, plan.steps[1:], strict=False):
            owner = self.swept_owner(plan.robot_id, previous.cell, current.cell, previous.tick)
            if owner is not None:
                conflicts.append(ReservationConflict(
                    ConflictKind.EDGE, previous.tick, owner,
                    edge=(previous.cell, current.cell),
                ))
            if previous.cell == current.cell:
                continue
            tick = previous.tick
            owner = self.edge_owner(previous.cell, current.cell, tick)
            if owner is not None and owner != plan.robot_id:
                conflicts.append(
                    ReservationConflict(
                        ConflictKind.EDGE,
                        tick,
                        owner,
                        edge=(previous.cell, current.cell),
                    )
                )
            reverse_owner = self.edge_owner(current.cell, previous.cell, tick)
            if reverse_owner is not None and reverse_owner != plan.robot_id:
                conflicts.append(
                    ReservationConflict(
                        ConflictKind.REVERSE_EDGE,
                        tick,
                        reverse_owner,
                        edge=(previous.cell, current.cell),
                    )
                )
        return tuple(conflicts)

    def commit(self, plan: Plan) -> tuple[ReservationConflict, ...]:
        conflicts = self.conflicts_for(plan)
        if conflicts:
            return conflicts

        for step in plan.steps:
            self._vertices[(step.cell, step.tick)] = plan.robot_id
        for previous, current in zip(plan.steps, plan.steps[1:], strict=False):
            self._motions.setdefault(previous.tick, {})[plan.robot_id] = (previous.cell, current.cell)
            if previous.cell != current.cell:
                self._edges[(previous.cell, current.cell, previous.tick)] = (
                    plan.robot_id
                )
        return ()

    def can_occupy(self, robot_id: str, cell: Cell, tick: int) -> bool:
        owner = self.vertex_owner(cell, tick)
        return owner is None or owner == robot_id

    def can_traverse(self, robot_id: str, start: Cell, end: Cell, tick: int) -> bool:
        if self.swept_owner(robot_id, start, end, tick) is not None:
            return False
        if start == end:
            return self.can_occupy(robot_id, end, tick + 1)
        direct = self.edge_owner(start, end, tick)
        reverse = self.edge_owner(end, start, tick)
        return (
            (direct is None or direct == robot_id)
            and (reverse is None or reverse == robot_id)
            and self.can_occupy(robot_id, end, tick + 1)
        )

    def release(self, robot_id: str, *, from_tick: int = 0) -> None:
        for tick, motions in self._motions.items():
            if tick >= from_tick:
                motions.pop(robot_id, None)
        self._vertices = {
            key: owner
            for key, owner in self._vertices.items()
            if not (owner == robot_id and key[1] >= from_tick)
        }
        self._edges = {
            key: owner
            for key, owner in self._edges.items()
            if not (owner == robot_id and key[2] >= from_tick)
        }

    def swept_owner(self, robot_id: str, start: Cell, end: Cell, tick: int) -> str | None:
        if not self.clearance_cells:
            return None
        for owner, (a, b) in self._motions.get(tick, {}).items():
            if owner == robot_id:
                continue
            x, y = start.x - a.x, start.y - a.y
            vx, vy = end.x - b.x - x, end.y - b.y - y
            speed2 = vx * vx + vy * vy
            u = max(0.0, min(1.0, -(x * vx + y * vy) / speed2)) if speed2 else 0.0
            if (x + u * vx) ** 2 + (y + u * vy) ** 2 < self.clearance_cells ** 2 - 1e-9:
                return owner
        return None

    def pressure(self, plan: Plan, *, radius_ticks: int = 1) -> float:
        if radius_ticks < 0:
            raise ValueError("radius_ticks must be non-negative")
        samples = 0
        occupied = 0
        for step in plan.steps:
            for tick in range(
                max(0, step.tick - radius_ticks), step.tick + radius_ticks + 1
            ):
                samples += 1
                owner = self.vertex_owner(step.cell, tick)
                if owner is not None and owner != plan.robot_id:
                    occupied += 1
        return occupied / samples if samples else 0.0

    def blocked_ticks_by_cell(self, robot_id: str) -> dict[Cell, list[int]]:
        """Ticks at which each cell is owned by somebody other than ``robot_id``.

        The table is sparse — a few thousand entries for a whole run — so one
        pass over it is far cheaper than asking about every cell at every tick.
        Safe-interval planning uses this to collapse the time axis.
        """
        blocked: dict[Cell, list[int]] = {}
        for (cell, tick), owner in self._vertices.items():
            if owner != robot_id:
                blocked.setdefault(cell, []).append(tick)
        for ticks in blocked.values():
            ticks.sort()
        return blocked

    @property
    def vertex_count(self) -> int:
        return len(self._vertices)

    @property
    def edge_count(self) -> int:
        return len(self._edges)
