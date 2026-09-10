from __future__ import annotations

import pytest

from kinesis.bench import measure_decision_latency
from kinesis.domain import Cell, RobotState, Task
from kinesis.fleet import SimulationConfig
from kinesis.graph import WarehouseMap
from kinesis.scenario import Scenario


def _scenario() -> Scenario:
    return Scenario(
        "latency-fixture",
        WarehouseMap(10, 4),
        (RobotState("R1", Cell(0, 0), 1.0), RobotState("R2", Cell(0, 3), 1.0)),
        (
            Task("T1", Cell(2, 1), Cell(8, 2), 0, 90),
            Task("T2", Cell(3, 2), Cell(7, 0), 0, 90),
        ),
        13,
    )


def test_latency_report_covers_both_decision_stages() -> None:
    report = measure_decision_latency(
        _scenario(),
        SimulationConfig(max_ticks=90, planning_horizon_ticks=90),
        repetitions=3,
    )

    assert report.robots == 2
    assert report.tasks == 2
    bid = report.stage("bid")
    schedule = report.stage("schedule")
    assert bid is not None and schedule is not None
    assert bid.count == 3 * 2 * 2
    assert schedule.count == 3


def test_percentiles_are_ordered_and_bounded_by_the_maximum() -> None:
    report = measure_decision_latency(
        _scenario(),
        SimulationConfig(max_ticks=90, planning_horizon_ticks=90),
        repetitions=5,
    )

    for stage in report.stages:
        assert 0.0 < stage.p50_ms <= stage.p95_ms <= stage.p99_ms <= stage.max_ms
        assert 0.0 < stage.mean_ms <= stage.max_ms


def test_repetitions_are_validated() -> None:
    with pytest.raises(ValueError, match="repetitions must be positive"):
        measure_decision_latency(_scenario(), repetitions=0)
