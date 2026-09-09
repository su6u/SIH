from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from .domain import Cell
from .fleet import FleetRunResult
from .operations import Intervention, InterventionKind
from .scenario import Scenario


@dataclass(frozen=True, slots=True)
class TraceMetadata:
    trace_id: str
    title: str
    subtitle: str
    kind: str
    tick_seconds: float = 0.42

    def __post_init__(self) -> None:
        if not self.trace_id or not self.title or not self.kind:
            raise ValueError("trace identity, title, and kind are required")
        if self.tick_seconds <= 0:
            raise ValueError("tick_seconds must be positive")


def build_presentation_trace(
    scenario: Scenario,
    result: FleetRunResult,
    metadata: TraceMetadata,
    *,
    origin: tuple[float, float],
    resolution: float,
    duration: int | None = None,
    interventions: tuple[Intervention, ...] = (),
    names: Mapping[str, str] | None = None,
    colors: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Project authoritative simulator events into the read-only UI schema."""

    if resolution <= 0:
        raise ValueError("resolution must be positive")
    horizon = result.metrics.elapsed_ticks if duration is None else duration
    if horizon < 0:
        raise ValueError("duration must be non-negative")

    events_by_tick: dict[int, list[Any]] = {}
    for event in result.events.events:
        events_by_tick.setdefault(event.tick, []).append(event)
    tasks = {task.task_id: task for task in scenario.tasks}
    state = {
        robot.robot_id: {
            "cell": robot.cell,
            "battery": robot.battery_soc,
            "status": "idle",
            "task": "Available",
            "load": False,
            "yaw": 0.0,
            "frames": [],
        }
        for robot in scenario.robots
    }
    completed: set[str] = set()
    awarded: set[str] = set()
    replans = 0
    distance = 0.0
    metrics: list[dict[str, Any]] = []

    for tick in range(horizon + 1):
        moved: set[str] = set()
        for event in events_by_tick.get(tick, []):
            robot_id = str(event.data.get("robot_id", event.entity_id))
            if event.kind == "task_awarded":
                awarded.add(event.entity_id)
                if robot_id in state:
                    state[robot_id]["task"] = _task_label(tasks.get(event.entity_id))
                    state[robot_id]["status"] = "committed"
            elif event.kind == "robot_moved" and event.entity_id in state:
                item = state[event.entity_id]
                target = event.data["to"]
                previous = item["cell"]
                cell = Cell(int(target["x"]), int(target["y"]))
                dx, dy = cell.x - previous.x, cell.y - previous.y
                item["yaw"] = _yaw(dx, dy, float(item["yaw"]))
                item["cell"] = cell
                item["status"] = "moving"
                moved.add(event.entity_id)
                distance += resolution
            elif event.kind == "task_picked" and robot_id in state:
                state[robot_id]["load"] = True
            elif event.kind == "task_dropped" and robot_id in state:
                state[robot_id]["load"] = False
            elif event.kind == "task_completed":
                completed.add(event.entity_id)
                if robot_id in state:
                    state[robot_id]["battery"] = float(
                        event.data.get("battery_soc", state[robot_id]["battery"])
                    )
                    state[robot_id]["status"] = "idle"
                    state[robot_id]["task"] = "Available"
            elif event.kind == "task_requeued":
                replans += 1
                awarded.discard(event.entity_id)
                if robot_id in state:
                    state[robot_id]["load"] = False
                    state[robot_id]["task"] = "Replanning"
                    state[robot_id]["status"] = "reconciling"
            elif event.kind == "robot_safe_stopped" and event.entity_id in state:
                state[event.entity_id]["status"] = "safe-stop"
                state[event.entity_id]["task"] = "Isolated"
            elif event.kind == "robot_charge_requested" and event.entity_id in state:
                state[event.entity_id]["battery"] = float(event.data["battery_soc"])
                state[event.entity_id]["status"] = "charging"
                state[event.entity_id]["task"] = "Battery recovery"
            elif event.kind == "robot_charge_completed" and event.entity_id in state:
                state[event.entity_id]["battery"] = float(event.data["battery_soc"])
                state[event.entity_id]["status"] = "idle"
                state[event.entity_id]["task"] = "Available"

        for robot_id, item in state.items():
            if item["status"] in {"moving", "committed"} and robot_id not in moved:
                item["status"] = "waiting"
            x, z = _to_world(item["cell"], origin, resolution)
            item["frames"].append(
                {
                    "t": tick,
                    "x": x,
                    "z": z,
                    "yaw": round(float(item["yaw"]), 4),
                    "battery": round(float(item["battery"]), 3),
                    "status": item["status"],
                    "task": item["task"],
                    "load": bool(item["load"]),
                }
            )

        if tick % 3 == 0:
            active = sum(
                item["status"] in {"moving", "committed", "waiting"}
                for item in state.values()
            )
            released = sum(task.release_tick <= tick for task in scenario.tasks)
            metrics.append(
                {
                    "t": tick,
                    "completed": len(completed),
                    "active": active,
                    "queued": max(0, released - len(completed) - len(awarded)),
                    "throughput": round(len(completed) * 60 / max(1, tick), 1),
                    "avgBattery": round(
                        sum(float(item["battery"]) for item in state.values())
                        / len(state)
                        * 100
                    ),
                    "distance": round(distance, 1),
                    "conflicts": (
                        result.metrics.executed_grid_vertex_conflicts
                        + result.metrics.executed_grid_reverse_edge_conflicts
                    ),
                    "replans": replans,
                }
            )

    incident_items, obstacle_items = _intervention_overlays(interventions, horizon)
    robot_items = []
    names = names or {}
    colors = colors or {}
    for robot in scenario.robots:
        item = state[robot.robot_id]
        robot_items.append(
            {
                "id": robot.robot_id,
                "name": names.get(robot.robot_id, robot.robot_id),
                "color": colors.get(robot.robot_id, "#70e1d1"),
                "frames": item["frames"],
            }
        )
    return {
        "schemaVersion": "1.0",
        "id": metadata.trace_id,
        "title": metadata.title,
        "subtitle": metadata.subtitle,
        "kind": metadata.kind,
        "duration": horizon,
        "tickSeconds": metadata.tick_seconds,
        "seed": scenario.seed,
        "incidents": incident_items,
        "obstacles": obstacle_items,
        "robots": robot_items,
        "metrics": metrics,
        "events": [
            {
                "tick": event.tick,
                "kind": event.kind,
                "entityId": event.entity_id,
                "data": _project_event_data(event.data, origin, resolution),
            }
            for event in result.events.events
        ],
        "summary": {
            "completed": result.metrics.completed_tasks,
            "conflicts": (
                result.metrics.executed_grid_vertex_conflicts
                + result.metrics.executed_grid_reverse_edge_conflicts
            ),
            "replans": replans,
            "distance": round(distance, 1),
            "robots": len(robot_items),
        },
        "evidence": {
            "source": "swarmroute.FleetSimulation",
            "auction": "replicated",
            "eventCount": len(result.events.events),
            "metrics": asdict(result.metrics),
        },
    }


def _project_event_data(
    data: Mapping[str, Any], origin: tuple[float, float], resolution: float
) -> dict[str, Any]:
    """Keep simulator evidence intact and add browser-space conflict positions."""

    projected = dict(data)
    cell = projected.get("cell")
    if isinstance(cell, Mapping) and "x" in cell and "y" in cell:
        world_x, world_z = _to_world(
            Cell(int(cell["x"]), int(cell["y"])), origin, resolution
        )
        projected["world"] = {"x": world_x, "z": world_z}
    edge = projected.get("edge")
    if isinstance(edge, list):
        projected["worldEdge"] = [
            {"x": point[0], "z": point[1]}
            for point in (
                _to_world(Cell(int(item["x"]), int(item["y"])), origin, resolution)
                for item in edge
                if isinstance(item, Mapping) and "x" in item and "y" in item
            )
        ]
    return projected


def _task_label(task: Any | None) -> str:
    if task is None:
        return "Assigned task"
    return (
        "Priority fulfillment"
        if task.task_id.startswith("priority_")
        or task.deadline_tick - task.release_tick <= 60
        else "Fulfillment"
    )


def _to_world(cell: Cell, origin: tuple[float, float], resolution: float) -> tuple[float, float]:
    return (
        round(origin[0] + cell.x * resolution, 3),
        round(-(origin[1] + cell.y * resolution), 3),
    )


def _yaw(dx: int, dy: int, fallback: float) -> float:
    import math

    return math.atan2(-dy, dx) if dx or dy else fallback


def _intervention_overlays(
    interventions: tuple[Intervention, ...], horizon: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    incidents: list[dict[str, Any]] = []
    obstacles: list[dict[str, Any]] = []
    for item in interventions:
        cell = item.cells[0] if item.cells else Cell(0, 0)
        if item.kind is InterventionKind.BLOCK_CELLS:
            title = "Aisle obstruction detected"
            description = "Reserved routes are invalidated and recomputed around quarantined cells."
            obstacles.append(
                {
                    "fromTick": item.tick,
                    "toTick": horizon,
                    "cells": [[value.x, value.y] for value in item.cells],
                    "label": "BLOCKED AISLE",
                }
            )
        elif item.kind is InterventionKind.ROBOT_FAILURE:
            title = "Robot safe-stop"
            description = "The failed unit is fenced off and its task is returned to auction."
        elif item.kind is InterventionKind.BATTERY_LOW:
            title = "Battery reserve protection"
            description = "The robot yields its assignment until the configured recovery tick."
        else:
            title = "Priority order released"
            description = "A deadline-critical task enters the same replicated auction and wins on urgency."
        incidents.append(
            {
                "tick": item.tick,
                "type": item.kind.value,
                "title": title,
                "description": description,
                "cell": [cell.x, cell.y],
            }
        )
    return incidents, obstacles
