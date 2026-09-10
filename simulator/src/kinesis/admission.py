from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .domain import Cell, RobotState


class AdmissionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CellClaim:
    robot_id: str
    source: Cell
    target: Cell


class CellAdmission:
    def __init__(self, robots: Iterable[RobotState]) -> None:
        states = tuple(robots)
        if not states:
            raise ValueError("at least one robot is required")
        if len({robot.robot_id for robot in states}) != len(states):
            raise ValueError("robot identifiers must be unique")
        if len({robot.cell for robot in states}) != len(states):
            raise ValueError("confirmed cells must be unique")
        self._confirmed = {robot.robot_id: robot.cell for robot in states}
        self._inflight: dict[str, CellClaim] = {}

    def can_enter(self, robot_id: str, target: Cell) -> bool:
        self._require_robot(robot_id)
        for other_id, cell in self._confirmed.items():
            if other_id != robot_id and cell == target:
                return False
        return all(
            claim.robot_id == robot_id or claim.target != target
            for claim in self._inflight.values()
        )

    def reserve(self, robot_id: str, target: Cell) -> CellClaim:
        source = self._require_robot(robot_id)
        if robot_id in self._inflight:
            raise AdmissionError(f"robot {robot_id} already has an admitted transition")
        if source == target:
            raise AdmissionError("stationary steps do not require admission")
        if source.manhattan_distance(target) != 1:
            raise AdmissionError("admitted transitions must move to an adjacent cell")
        if not self.can_enter(robot_id, target):
            raise AdmissionError(f"cell {target} is not available")
        claim = CellClaim(robot_id, source, target)
        self._inflight[robot_id] = claim
        return claim

    def confirm(self, robot_id: str, target: Cell) -> None:
        claim = self._inflight.get(robot_id)
        if claim is None:
            raise AdmissionError(f"robot {robot_id} has no admitted transition")
        if claim.target != target:
            raise AdmissionError(f"robot {robot_id} confirmed an unexpected cell")
        self._confirmed[robot_id] = target
        del self._inflight[robot_id]

    def confirmed_cell(self, robot_id: str) -> Cell:
        return self._require_robot(robot_id)

    def inflight_claim(self, robot_id: str) -> CellClaim | None:
        self._require_robot(robot_id)
        return self._inflight.get(robot_id)

    def _require_robot(self, robot_id: str) -> Cell:
        try:
            return self._confirmed[robot_id]
        except KeyError as error:
            raise AdmissionError(f"unknown robot {robot_id}") from error
