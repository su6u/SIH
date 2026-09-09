from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .domain import Cell, RobotState, Task
from .graph import WarehouseMap
from .operations import ConflictZone, Intervention, InterventionKind


class ScenarioError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Scenario:
    name: str
    warehouse_map: WarehouseMap
    robots: tuple[RobotState, ...]
    tasks: tuple[Task, ...]
    seed: int
    conflict_zones: tuple[ConflictZone, ...] = ()
    interventions: tuple[Intervention, ...] = ()


def load_scenario(path: str | Path) -> Scenario:
    source = Path(path)
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ScenarioError(f"cannot read scenario {source}: {error}") from error
    if not isinstance(raw, dict):
        raise ScenarioError("scenario root must be an object")
    return parse_scenario(raw)


def parse_scenario(raw: Mapping[str, Any]) -> Scenario:
    try:
        if raw["schema_version"] != "1.0":
            raise ScenarioError("unsupported scenario schema_version")
        name = _nonempty_string(raw["name"], "name")
        seed = _integer(raw.get("seed", 0), "seed")
        map_data = _mapping(raw["map"], "map")
        robot_data = _list(raw["robots"], "robots")
        task_data = _list(raw["tasks"], "tasks")
        zone_data = _list(raw.get("conflict_zones", []), "conflict_zones")
        intervention_data = _list(raw.get("interventions", []), "interventions")

        blocked = {
            _cell(value, "map.blocked")
            for value in _list(map_data.get("blocked", []), "map.blocked")
        }
        for value in _list(
            map_data.get("blocked_rectangles", []), "map.blocked_rectangles"
        ):
            rectangle = _list(value, "map.blocked_rectangles[]")
            if len(rectangle) != 4:
                raise ScenarioError(
                    "map.blocked_rectangles[] must contain [x1, y1, x2, y2]"
                )
            x1, y1, x2, y2 = (
                _integer(item, "map.blocked_rectangles[]") for item in rectangle
            )
            if x2 < x1 or y2 < y1:
                raise ScenarioError(
                    "blocked rectangle maximums must not precede minimums"
                )
            blocked.update(
                Cell(x, y) for x in range(x1, x2 + 1) for y in range(y1, y2 + 1)
            )
        warehouse = WarehouseMap(
            width=_integer(map_data["width"], "map.width"),
            height=_integer(map_data["height"], "map.height"),
            blocked=frozenset(blocked),
            version=_nonempty_string(map_data["version"], "map.version"),
        )
        robots = tuple(
            RobotState(
                robot_id=_nonempty_string(_mapping(item, "robot")["id"], "robot.id"),
                cell=_cell(_mapping(item, "robot")["cell"], "robot.cell"),
                battery_soc=_number(
                    _mapping(item, "robot")["battery_soc"], "robot.battery_soc"
                ),
                available_tick=_integer(
                    _mapping(item, "robot").get("available_tick", 0),
                    "robot.available_tick",
                ),
                completed_tasks=_integer(
                    _mapping(item, "robot").get("completed_tasks", 0),
                    "robot.completed_tasks",
                ),
                boot_id=_nonempty_string(
                    _mapping(item, "robot").get("boot_id", "boot-0"), "robot.boot_id"
                ),
                payload_capacity_kg=_number(
                    _mapping(item, "robot").get("payload_capacity_kg", 1_000.0),
                    "robot.payload_capacity_kg",
                ),
                reserve_soc=_number(
                    _mapping(item, "robot").get("reserve_soc", 0.25),
                    "robot.reserve_soc",
                ),
            )
            for item in robot_data
        )
        tasks = tuple(
            Task(
                task_id=_nonempty_string(_mapping(item, "task")["id"], "task.id"),
                pickup=_cell(_mapping(item, "task")["pickup"], "task.pickup"),
                dropoff=_cell(_mapping(item, "task")["dropoff"], "task.dropoff"),
                release_tick=_integer(
                    _mapping(item, "task")["release_tick"], "task.release_tick"
                ),
                deadline_tick=_integer(
                    _mapping(item, "task")["deadline_tick"], "task.deadline_tick"
                ),
                payload_kg=_number(
                    _mapping(item, "task").get("payload_kg", 0.0), "task.payload_kg"
                ),
                service_ticks=_integer(
                    _mapping(item, "task").get("service_ticks", 1), "task.service_ticks"
                ),
            )
            for item in task_data
        )
        conflict_zones = tuple(
            ConflictZone(
                zone_id=_nonempty_string(
                    _mapping(item, "conflict_zone")["id"], "conflict_zone.id"
                ),
                cells=frozenset(
                    _cell(cell, "conflict_zone.cells[]")
                    for cell in _list(
                        _mapping(item, "conflict_zone")["cells"],
                        "conflict_zone.cells",
                    )
                ),
                lease_ttl_ticks=_integer(
                    _mapping(item, "conflict_zone").get("lease_ttl_ticks", 3),
                    "conflict_zone.lease_ttl_ticks",
                ),
            )
            for item in zone_data
        )
        interventions = tuple(
            _intervention(_mapping(item, "intervention"))
            for item in intervention_data
        )
    except KeyError as error:
        raise ScenarioError(f"missing required field: {error.args[0]}") from error
    except (TypeError, ValueError) as error:
        if isinstance(error, ScenarioError):
            raise
        raise ScenarioError(str(error)) from error

    if not robots:
        raise ScenarioError("scenario must contain at least one robot")
    if len({robot.robot_id for robot in robots}) != len(robots):
        raise ScenarioError("robot identifiers must be unique")
    if len({robot.cell for robot in robots}) != len(robots):
        raise ScenarioError("robot starting cells must be unique")
    if len({task.task_id for task in tasks}) != len(tasks):
        raise ScenarioError("task identifiers must be unique")
    if len({zone.zone_id for zone in conflict_zones}) != len(conflict_zones):
        raise ScenarioError("conflict zone identifiers must be unique")
    if len({item.intervention_id for item in interventions}) != len(interventions):
        raise ScenarioError("intervention identifiers must be unique")
    for robot in robots:
        if not warehouse.traversable(robot.cell):
            raise ScenarioError(
                f"robot {robot.robot_id} starts in a blocked or out-of-bounds cell"
            )
    for task in tasks:
        if not warehouse.traversable(task.pickup) or not warehouse.traversable(
            task.dropoff
        ):
            raise ScenarioError(
                f"task {task.task_id} uses a blocked or out-of-bounds cell"
            )
    for zone in conflict_zones:
        if any(not warehouse.traversable(cell) for cell in zone.cells):
            raise ScenarioError(f"conflict zone {zone.zone_id} contains an invalid cell")
    robot_ids = {robot.robot_id for robot in robots}
    for item in interventions:
        if item.robot_id is not None and item.robot_id not in robot_ids:
            raise ScenarioError(
                f"intervention {item.intervention_id} references an unknown robot"
            )
        if any(not warehouse.traversable(cell) for cell in item.cells):
            raise ScenarioError(
                f"intervention {item.intervention_id} blocks an invalid cell"
            )
    return Scenario(
        name,
        warehouse,
        robots,
        tasks,
        seed,
        conflict_zones,
        tuple(sorted(interventions, key=lambda item: (item.tick, item.intervention_id))),
    )


def _intervention(raw: Mapping[str, Any]) -> Intervention:
    try:
        kind = InterventionKind(_nonempty_string(raw["kind"], "intervention.kind"))
    except ValueError as error:
        raise ScenarioError(str(error)) from error
    return Intervention(
        intervention_id=_nonempty_string(raw["id"], "intervention.id"),
        tick=_integer(raw["tick"], "intervention.tick"),
        kind=kind,
        robot_id=(
            _nonempty_string(raw["robot_id"], "intervention.robot_id")
            if "robot_id" in raw
            else None
        ),
        cells=tuple(
            _cell(cell, "intervention.cells[]")
            for cell in _list(raw.get("cells", []), "intervention.cells")
        ),
        battery_soc=(
            _number(raw["battery_soc"], "intervention.battery_soc")
            if "battery_soc" in raw
            else None
        ),
        recover_tick=(
            _integer(raw["recover_tick"], "intervention.recover_tick")
            if "recover_tick" in raw
            else None
        ),
        recovered_soc=_number(
            raw.get("recovered_soc", 0.85), "intervention.recovered_soc"
        ),
    )


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ScenarioError(f"{field} must be an object")
    return value


def _list(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise ScenarioError(f"{field} must be an array")
    return value


def _integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ScenarioError(f"{field} must be an integer")
    return value


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ScenarioError(f"{field} must be a number")
    return float(value)


def _nonempty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ScenarioError(f"{field} must be a non-empty string")
    return value


def _cell(value: Any, field: str) -> Cell:
    items = _list(value, field)
    if len(items) != 2:
        raise ScenarioError(f"{field} must contain exactly [x, y]")
    return Cell(_integer(items[0], f"{field}[0]"), _integer(items[1], f"{field}[1]"))
