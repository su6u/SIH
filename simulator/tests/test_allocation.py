from dataclasses import replace

import pytest

from kinesis.allocation import Bid, BidComponents, Bidder, select_winner
from kinesis.domain import Cell, RobotState, Task
from kinesis.graph import WarehouseMap
from kinesis.physics import MotionConfig
from kinesis.planner import SpaceTimeAStar
from kinesis.reservations import ReservationTable


def _bid(robot_id: str, score: float, workload: int, *, feasible: bool = True) -> Bid:
    return Bid(
        robot_id=robot_id,
        task_id="T1",
        auction_epoch=2,
        feasible=feasible,
        score=score,
        components=BidComponents(0.1, 0.1, 0.1, 0.1),
        expected_finish_tick=10,
        expected_soc=0.8,
        workload=workload,
    )


def test_battery_capacity_uses_watt_hours_converted_to_joules() -> None:
    assert MotionConfig().battery_capacity_joules == pytest.approx(8_640_000.0)


def test_fairness_breaks_ties_inside_five_percent_cost_envelope() -> None:
    winner = select_winner([_bid("busy", 1.0, 8), _bid("idle", 1.04, 0)])
    assert winner.robot_id == "idle"


def test_fairness_cannot_override_materially_cheaper_bid() -> None:
    winner = select_winner([_bid("busy", 1.0, 8), _bid("idle", 1.06, 0)])
    assert winner.robot_id == "busy"


def test_infeasible_bids_are_never_selected() -> None:
    winner = select_winner(
        [_bid("safe", 2.0, 4), replace(_bid("unsafe", 0.1, 0), feasible=False)]
    )
    assert winner.robot_id == "safe"


def test_mixed_task_epochs_are_rejected() -> None:
    with pytest.raises(ValueError, match="same task and epoch"):
        select_winner(
            [_bid("R1", 1.0, 0), replace(_bid("R2", 1.0, 0), auction_epoch=3)]
        )


def _bidder() -> Bidder:
    reservations = ReservationTable()
    motion = MotionConfig()
    planner = SpaceTimeAStar(
        WarehouseMap(3, 1),
        reservations,
        move_ticks=motion.move_ticks,
    )
    return Bidder(planner, reservations, motion=motion)


def test_zero_service_duration_produces_a_consecutive_execution_plan() -> None:
    bid = _bidder().bid(
        RobotState("R1", Cell(0, 0), 1.0),
        Task("T1", Cell(1, 0), Cell(2, 0), 0, 20, service_ticks=0),
        current_tick=0,
        auction_epoch=1,
    )

    assert bid.feasible
    assert bid.execution_plan is not None
    assert bid.execution_plan.end.tick == 2


def test_service_duration_consumes_auxiliary_energy() -> None:
    robot = RobotState("R1", Cell(0, 0), 1.0)
    immediate = _bidder().bid(
        robot,
        Task("T1", Cell(1, 0), Cell(2, 0), 0, 30, service_ticks=0),
        current_tick=0,
        auction_epoch=1,
    )
    serviced = _bidder().bid(
        robot,
        Task("T1", Cell(1, 0), Cell(2, 0), 0, 30, service_ticks=2),
        current_tick=0,
        auction_epoch=1,
    )

    assert immediate.expected_soc is not None
    assert serviced.expected_soc is not None
    assert serviced.expected_soc < immediate.expected_soc
    assert serviced.expected_finish_tick == immediate.expected_finish_tick + 4


def test_payload_capacity_is_a_hard_feasibility_constraint() -> None:
    bid = _bidder().bid(
        RobotState("R1", Cell(0, 0), 1.0, payload_capacity_kg=100.0),
        Task("T1", Cell(1, 0), Cell(2, 0), 0, 20, payload_kg=101.0),
        current_tick=0,
        auction_epoch=1,
    )

    assert not bid.feasible
    assert bid.reason == "payload capacity exceeded"
