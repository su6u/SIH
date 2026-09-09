import pytest

from swarmroute.allocation import Bid, BidComponents
from swarmroute.auction import ReplicatedAuction
from swarmroute.domain import Cell, RobotState, Task
from swarmroute.fleet import FleetSimulation, SimulationConfig
from swarmroute.graph import WarehouseMap


BOOT_IDS = {"R1": "B1", "R2": "B2"}
KEYS = {"R1": b"r1-test-key", "R2": b"r2-test-key"}


def _bid(robot_id: str, score: float) -> Bid:
    return Bid(
        robot_id=robot_id,
        task_id="T1",
        auction_epoch=1,
        feasible=True,
        score=score,
        components=BidComponents(0.0, 0.0, 0.0, 0.0),
        expected_finish_tick=10,
        expected_soc=0.8,
        workload=0,
    )


def test_replicated_auction_returns_the_common_winner() -> None:
    auction = ReplicatedAuction(
        map_version="M1",
        boot_ids=BOOT_IDS,
        authentication_keys=KEYS,
    )

    winner = auction.select((_bid("R1", 0.8), _bid("R2", 0.4)), fairness_tolerance=0.05)

    assert winner.robot_id == "R2"


def test_replicated_auction_fails_closed_during_a_partition() -> None:
    auction = ReplicatedAuction(
        map_version="M1",
        boot_ids=BOOT_IDS,
        authentication_keys=KEYS,
        isolated=frozenset({"R2"}),
    )

    with pytest.raises(ValueError, match="complete view"):
        auction.select((_bid("R1", 0.8), _bid("R2", 0.4)), fairness_tolerance=0.05)


def test_fleet_can_use_replicated_auction_state() -> None:
    robots = (
        RobotState("R1", Cell(0, 0), 1.0, boot_id="B1"),
        RobotState("R2", Cell(0, 1), 1.0, boot_id="B2"),
    )
    auction = ReplicatedAuction(
        map_version="M1",
        boot_ids=BOOT_IDS,
        authentication_keys=KEYS,
    )
    result = FleetSimulation(
        WarehouseMap(4, 2, version="M1"),
        robots,
        config=SimulationConfig(max_ticks=20, planning_horizon_ticks=20),
        auction=auction,
    ).run((Task("T1", Cell(1, 0), Cell(3, 0), 0, 20),))

    assert result.metrics.completed_tasks == 1
