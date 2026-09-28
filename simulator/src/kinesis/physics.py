from __future__ import annotations

import math
from dataclasses import dataclass

from .domain import Plan


@dataclass(frozen=True, slots=True)
class MotionConfig:
    cell_size_m: float = 1.5
    tick_seconds: float = 5.0
    chassis_mass_kg: float = 150.0
    max_speed_mps: float = 1.5
    max_acceleration_mps2: float = 0.8
    rolling_resistance: float = 0.015
    drivetrain_efficiency: float = 0.82
    auxiliary_power_w: float = 65.0
    turn_duration_seconds: float = 1.5
    battery_voltage_v: float = 48.0
    battery_capacity_ah: float = 50.0
    lift_height_m: float = 0.05
    lift_efficiency: float = 0.65

    def __post_init__(self) -> None:
        positive = (
            self.cell_size_m,
            self.tick_seconds,
            self.chassis_mass_kg,
            self.max_speed_mps,
            self.max_acceleration_mps2,
            self.drivetrain_efficiency,
            self.battery_voltage_v,
            self.battery_capacity_ah,
            self.lift_efficiency,
        )
        if any(not math.isfinite(value) or value <= 0 for value in positive):
            raise ValueError("physical parameters must be positive")
        nonnegative = (
            self.rolling_resistance,
            self.auxiliary_power_w,
            self.turn_duration_seconds,
            self.lift_height_m,
        )
        if any(not math.isfinite(value) or value < 0 for value in nonnegative):
            raise ValueError(
                "physical loss and duration parameters must be non-negative"
            )
        if not 0 < self.drivetrain_efficiency <= 1 or not 0 < self.lift_efficiency <= 1:
            raise ValueError("efficiencies must be in (0, 1]")

    @property
    def battery_capacity_joules(self) -> float:
        return self.battery_voltage_v * self.battery_capacity_ah * 3600.0

    @property
    def minimum_cell_translation_seconds(self) -> float:
        return _translation_time(
            self.cell_size_m,
            self.max_speed_mps,
            self.max_acceleration_mps2,
        )

    @property
    def move_ticks(self) -> int:
        duration = self.minimum_cell_translation_seconds + self.turn_duration_seconds
        return max(1, math.ceil(duration / self.tick_seconds))


@dataclass(frozen=True, slots=True)
class MotionEstimate:
    distance_m: float
    duration_seconds: float
    energy_joules: float
    soc_delta: float
    turns: int


def _translation_time(distance_m: float, speed: float, acceleration: float) -> float:
    if distance_m <= 0:
        return 0.0
    acceleration_distance = speed * speed / acceleration
    if distance_m >= acceleration_distance:
        return 2.0 * speed / acceleration + (distance_m - acceleration_distance) / speed
    return 2.0 * math.sqrt(distance_m / acceleration)


def _directions(plan: Plan) -> list[tuple[int, int]]:
    directions: list[tuple[int, int]] = []
    for previous, current in zip(plan.steps, plan.steps[1:], strict=False):
        dx = current.cell.x - previous.cell.x
        dy = current.cell.y - previous.cell.y
        if dx or dy:
            directions.append((dx, dy))
    return directions


def estimate_motion(
    plan: Plan,
    *,
    payload_kg: float,
    config: MotionConfig = MotionConfig(),
    include_lift: bool = False,
    dwell_seconds: float = 0.0,
) -> MotionEstimate:
    if (
        not math.isfinite(payload_kg)
        or not math.isfinite(dwell_seconds)
        or payload_kg < 0
        or dwell_seconds < 0
    ):
        raise ValueError("payload_kg and dwell_seconds must be non-negative")
    directions = _directions(plan)
    turns = sum(
        before != after
        for before, after in zip(directions, directions[1:], strict=False)
    )
    distance_m = len(directions) * config.cell_size_m

    run_lengths: list[int] = []
    if directions:
        run_length = 1
        for before, after in zip(directions, directions[1:], strict=False):
            if before == after:
                run_length += 1
            else:
                run_lengths.append(run_length)
                run_length = 1
        run_lengths.append(run_length)
    translation_seconds = sum(
        _translation_time(
            length * config.cell_size_m,
            config.max_speed_mps,
            config.max_acceleration_mps2,
        )
        for length in run_lengths
    )
    physical_seconds = translation_seconds + turns * config.turn_duration_seconds
    scheduled_seconds = (len(plan.steps) - 1) * config.tick_seconds
    duration_seconds = max(physical_seconds, scheduled_seconds) + dwell_seconds

    mass = config.chassis_mass_kg + payload_kg
    gravity = 9.80665
    rolling_energy = (
        config.rolling_resistance
        * mass
        * gravity
        * distance_m
        / config.drivetrain_efficiency
    )
    acceleration_energy = 0.0
    for length in run_lengths:
        run_distance = length * config.cell_size_m
        peak_speed = min(
            config.max_speed_mps,
            math.sqrt(run_distance * config.max_acceleration_mps2),
        )
        acceleration_energy += (
            0.5 * mass * peak_speed * peak_speed / config.drivetrain_efficiency
        )
    auxiliary_energy = config.auxiliary_power_w * duration_seconds
    lift_energy = (
        payload_kg * gravity * config.lift_height_m / config.lift_efficiency
        if include_lift
        else 0.0
    )
    energy_joules = (
        rolling_energy + acceleration_energy + auxiliary_energy + lift_energy
    )
    return MotionEstimate(
        distance_m=distance_m,
        duration_seconds=duration_seconds,
        energy_joules=energy_joules,
        soc_delta=energy_joules / config.battery_capacity_joules,
        turns=turns,
    )
