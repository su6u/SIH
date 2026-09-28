import pytest

from kinesis.domain import Cell
from kinesis.scenario import ScenarioError, parse_scenario


def _raw_scenario() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "name": "test",
        "seed": 9,
        "map": {"version": "M1", "width": 3, "height": 2, "blocked": [[1, 1]]},
        "robots": [{"id": "R1", "cell": [0, 0], "battery_soc": 0.8}],
        "tasks": [
            {
                "id": "T1",
                "pickup": [1, 0],
                "dropoff": [2, 0],
                "release_tick": 0,
                "deadline_tick": 5,
            }
        ],
    }


def test_scenario_parser_builds_typed_domain_values() -> None:
    scenario = parse_scenario(_raw_scenario())
    assert scenario.seed == 9
    assert scenario.warehouse_map.blocked == frozenset({Cell(1, 1)})
    assert scenario.robots[0].robot_id == "R1"
    assert scenario.tasks[0].dropoff == Cell(2, 0)


def test_scenario_parser_rejects_unknown_schema_version() -> None:
    raw = _raw_scenario()
    raw["schema_version"] = "2.0"
    with pytest.raises(ScenarioError, match="unsupported"):
        parse_scenario(raw)


def test_scenario_parser_rejects_boolean_as_integer() -> None:
    raw = _raw_scenario()
    raw["seed"] = True
    with pytest.raises(ScenarioError, match="must be an integer"):
        parse_scenario(raw)


def test_parse_expands_blocked_rectangles() -> None:
    raw = _raw_scenario()
    raw["map"] = {
        "version": "M2",
        "width": 4,
        "height": 4,
        "blocked_rectangles": [[1, 1, 2, 2]],
    }
    raw["tasks"] = []

    scenario = parse_scenario(raw)

    assert scenario.warehouse_map.blocked == frozenset(
        {Cell(1, 1), Cell(1, 2), Cell(2, 1), Cell(2, 2)}
    )


def test_parse_conflict_zones_and_operational_interventions() -> None:
    raw = _raw_scenario()
    raw["conflict_zones"] = [
        {"id": "Z1", "cells": [[1, 0]], "lease_ttl_ticks": 4}
    ]
    raw["interventions"] = [
        {
            "id": "battery-r1",
            "tick": 2,
            "kind": "battery_low",
            "robot_id": "R1",
            "battery_soc": 0.15,
            "recover_tick": 4,
        }
    ]

    scenario = parse_scenario(raw)

    assert scenario.conflict_zones[0].cells == frozenset({Cell(1, 0)})
    assert scenario.interventions[0].robot_id == "R1"
    assert scenario.interventions[0].recover_tick == 4
