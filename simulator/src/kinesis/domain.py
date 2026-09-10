from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable


@dataclass(frozen=True, slots=True, order=True)
class Cell:
    x: int
    y: int

    def manhattan_distance(self, other: "Cell") -> int:
        return abs(self.x - other.x) + abs(self.y - other.y)


class RobotMode(StrEnum):
    IDLE = "idle"
    PLANNING = "planning"
    COMMITTED = "committed"
    MOVING = "moving"
    SAFE_STOP = "safe_stop"
    RECONCILING = "reconciling"


@dataclass(frozen=True, slots=True)
class RobotState:
    robot_id: str
    cell: Cell
    battery_soc: float
    available_tick: int = 0
    completed_tasks: int = 0
    mode: RobotMode = RobotMode.IDLE
    boot_id: str = "boot-0"
    payload_capacity_kg: float = 1_000.0
    reserve_soc: float = 0.25

    def __post_init__(self) -> None:
        if not self.robot_id:
            raise ValueError("robot_id must not be empty")
        if not math.isfinite(self.battery_soc) or not 0.0 <= self.battery_soc <= 1.0:
            raise ValueError("battery_soc must be in [0, 1]")
        if not math.isfinite(self.payload_capacity_kg) or self.payload_capacity_kg <= 0:
            raise ValueError("payload_capacity_kg must be positive")
        if not math.isfinite(self.reserve_soc) or not 0.0 <= self.reserve_soc <= 1.0:
            raise ValueError("reserve_soc must be in [0, 1]")
        if self.available_tick < 0 or self.completed_tasks < 0:
            raise ValueError("ticks and task counts must be non-negative")


@dataclass(frozen=True, slots=True)
class Task:
    task_id: str
    pickup: Cell
    dropoff: Cell
    release_tick: int
    deadline_tick: int
    payload_kg: float = 0.0
    service_ticks: int = 1

    def __post_init__(self) -> None:
        if not self.task_id:
            raise ValueError("task_id must not be empty")
        if self.release_tick < 0 or self.deadline_tick < self.release_tick:
            raise ValueError("deadline must not precede release")
        if (
            not math.isfinite(self.payload_kg)
            or self.payload_kg < 0
            or self.service_ticks < 0
        ):
            raise ValueError("payload and service time must be non-negative")


@dataclass(frozen=True, slots=True)
class PlanStep:
    cell: Cell
    tick: int

    def __post_init__(self) -> None:
        if self.tick < 0:
            raise ValueError("tick must be non-negative")


@dataclass(frozen=True, slots=True)
class Plan:
    robot_id: str
    steps: tuple[PlanStep, ...]

    @classmethod
    def from_steps(cls, robot_id: str, steps: Iterable[PlanStep]) -> "Plan":
        return cls(robot_id=robot_id, steps=tuple(steps))

    def __post_init__(self) -> None:
        if not self.robot_id:
            raise ValueError("robot_id must not be empty")
        if not self.steps:
            raise ValueError("plan must contain at least one step")
        for previous, current in zip(self.steps, self.steps[1:], strict=False):
            if current.tick != previous.tick + 1:
                raise ValueError("plan ticks must be consecutive")
            if previous.cell.manhattan_distance(current.cell) > 1:
                raise ValueError("plan moves must be cardinal or wait actions")

    @property
    def start(self) -> PlanStep:
        return self.steps[0]

    @property
    def end(self) -> PlanStep:
        return self.steps[-1]

    @property
    def move_count(self) -> int:
        return sum(
            a.cell != b.cell for a, b in zip(self.steps, self.steps[1:], strict=False)
        )
