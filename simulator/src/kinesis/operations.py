from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from .domain import Cell


class InterventionKind(StrEnum):
    BLOCK_CELLS = "block_cells"
    ROBOT_FAILURE = "robot_failure"
    BATTERY_LOW = "battery_low"
    PRIORITY_TASK = "priority_task"


@dataclass(frozen=True, slots=True)
class Intervention:
    """A deterministic operational change applied at an exact simulation tick."""

    intervention_id: str
    tick: int
    kind: InterventionKind
    robot_id: str | None = None
    cells: tuple[Cell, ...] = ()
    battery_soc: float | None = None
    recover_tick: int | None = None
    recovered_soc: float = 0.85

    def __post_init__(self) -> None:
        if not self.intervention_id or self.tick < 0:
            raise ValueError("intervention identity and tick are required")
        if self.kind is InterventionKind.BLOCK_CELLS and not self.cells:
            raise ValueError("block_cells requires at least one cell")
        if self.kind in {InterventionKind.ROBOT_FAILURE, InterventionKind.BATTERY_LOW}:
            if not self.robot_id:
                raise ValueError(f"{self.kind} requires robot_id")
        if self.kind is InterventionKind.BATTERY_LOW:
            if self.battery_soc is None or not math.isfinite(self.battery_soc):
                raise ValueError("battery_low requires a finite battery_soc")
            if not 0.0 <= self.battery_soc <= 1.0:
                raise ValueError("battery_soc must be in [0, 1]")
            if self.recover_tick is not None and self.recover_tick <= self.tick:
                raise ValueError("recover_tick must be after the intervention tick")
            if not 0.0 <= self.recovered_soc <= 1.0:
                raise ValueError("recovered_soc must be in [0, 1]")


@dataclass(frozen=True, slots=True)
class ConflictZone:
    zone_id: str
    cells: frozenset[Cell]
    lease_ttl_ticks: int = 3

    def __post_init__(self) -> None:
        if not self.zone_id or not self.cells:
            raise ValueError("conflict zone identity and cells are required")
        if self.lease_ttl_ticks <= 0:
            raise ValueError("lease_ttl_ticks must be positive")
