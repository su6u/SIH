from __future__ import annotations

import heapq
from dataclasses import dataclass

from .domain import Cell, Plan, PlanStep
from .graph import WarehouseMap
from .heuristics import DistanceOracle
from .reservations import ReservationTable
from .sipp import SafeIntervalSearch


class NoPathError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True, order=True)
class _State:
    tick: int
    cell: Cell


class SpaceTimeAStar:
    def __init__(
        self,
        warehouse_map: WarehouseMap,
        reservations: ReservationTable,
        *,
        move_ticks: int = 1,
        distances: DistanceOracle | None = None,
    ) -> None:
        if move_ticks <= 0:
            raise ValueError("move_ticks must be positive")
        if distances is not None and distances.warehouse_map != warehouse_map:
            raise ValueError("distance oracle belongs to a different map")
        self._map = warehouse_map
        self._reservations = reservations
        self._move_ticks = move_ticks
        self._distances = (
            distances if distances is not None else DistanceOracle(warehouse_map)
        )
        # Safe-interval search returns the same time-optimal plan without
        # storing a state per tick, but it is written for unit-duration moves
        # over point robots. Anything else keeps the time-expanded search.
        self._safe_intervals = (
            SafeIntervalSearch(warehouse_map, reservations, self._distances)
            if move_ticks == 1 and not reservations.clearance_cells
            else None
        )

    @property
    def distances(self) -> DistanceOracle:
        return self._distances

    @property
    def move_ticks(self) -> int:
        return self._move_ticks

    def plan(
        self,
        robot_id: str,
        start: Cell,
        goal: Cell,
        *,
        start_tick: int,
        max_tick: int,
    ) -> Plan:
        if not self._map.traversable(start) or not self._map.traversable(goal):
            raise ValueError("start and goal must be traversable")
        if start_tick < 0 or max_tick < start_tick:
            raise ValueError("invalid planning horizon")
        if not self._reservations.can_occupy(robot_id, start, start_tick):
            raise NoPathError("start cell is reserved by another robot")

        if self._safe_intervals is not None:
            steps = self._safe_intervals.plan(
                robot_id, start, goal, start_tick=start_tick, max_tick=max_tick
            )
            if steps is None:
                raise NoPathError(f"no path to {goal} by tick {max_tick}")
            return Plan.from_steps(robot_id, steps)

        goal_field = self._distances.field(goal)
        width = self._map.width

        def cost_to_go(cell: Cell) -> int | None:
            moves = goal_field[cell.y * width + cell.x]
            return None if moves < 0 else moves * self._move_ticks

        initial = _State(start_tick, start)
        frontier: list[tuple[int, int, int, int, int, _State]] = []
        initial_h = cost_to_go(start)
        if initial_h is None:
            raise NoPathError(f"no route from {start} to {goal} on this map")
        heapq.heappush(
            frontier, (initial_h, initial_h, start_tick, start.y, start.x, initial)
        )
        cost: dict[_State, int] = {initial: 0}
        parent: dict[_State, _State] = {}

        while frontier:
            _, _, _, _, _, current = heapq.heappop(frontier)
            if current.cell == goal:
                return self._reconstruct(robot_id, current, parent)
            if current.tick >= max_tick:
                continue

            candidates = tuple(
                sorted(
                    (
                        cell
                        for cell in self._map.neighbors(current.cell, include_wait=True)
                        if goal_field[cell.y * width + cell.x] >= 0
                    ),
                    key=lambda cell: (
                        goal_field[cell.y * width + cell.x],
                        cell.y,
                        cell.x,
                    ),
                )
            )
            for next_cell in candidates:
                action_ticks = 1 if next_cell == current.cell else self._move_ticks
                next_tick = current.tick + action_ticks
                if next_tick > max_tick:
                    continue
                if next_cell == current.cell:
                    available = self._reservations.can_traverse(
                        robot_id, current.cell, next_cell, current.tick
                    )
                else:
                    available = all(
                        self._reservations.can_occupy(robot_id, current.cell, tick)
                        for tick in range(current.tick + 1, next_tick)
                    ) and self._reservations.can_traverse(
                        robot_id,
                        current.cell,
                        next_cell,
                        next_tick - 1,
                    )
                if not available:
                    continue
                next_state = _State(next_tick, next_cell)
                next_cost = cost[current] + action_ticks
                if next_cost >= cost.get(next_state, 2**63 - 1):
                    continue
                cost[next_state] = next_cost
                parent[next_state] = current
                heuristic = goal_field[next_cell.y * width + next_cell.x] * (
                    self._move_ticks
                )
                heapq.heappush(
                    frontier,
                    (
                        next_cost + heuristic,
                        heuristic,
                        next_state.tick,
                        next_cell.y,
                        next_cell.x,
                        next_state,
                    ),
                )

        raise NoPathError(f"no path to {goal} by tick {max_tick}")

    @staticmethod
    def _reconstruct(robot_id: str, end: _State, parent: dict[_State, _State]) -> Plan:
        states = [end]
        while states[-1] in parent:
            states.append(parent[states[-1]])
        states.reverse()
        steps = [PlanStep(cell=states[0].cell, tick=states[0].tick)]
        for previous, current in zip(states, states[1:], strict=False):
            steps.extend(
                PlanStep(cell=previous.cell, tick=tick)
                for tick in range(previous.tick + 1, current.tick)
            )
            steps.append(PlanStep(cell=current.cell, tick=current.tick))
        return Plan.from_steps(robot_id, steps)
