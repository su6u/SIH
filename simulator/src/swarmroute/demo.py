from __future__ import annotations

from dataclasses import asdict

from .allocation import Bid, BidComponents, Bidder, select_winner
from .consensus import AuctionReplica
from .domain import Cell, RobotState, Task
from .graph import WarehouseMap
from .leases import ZoneLeaseRegistry
from .network import DeterministicNetwork, NetworkConfig
from .planner import SpaceTimeAStar
from .protocol import MessageEnvelope, ReplayGuard
from .reservations import ReservationTable


def run_demo(seed: int = 7) -> dict[str, object]:
    authentication_keys = {
        "R1": b"demo-r1-key",
        "R2": b"demo-r2-key",
        "R3": b"demo-r3-key",
    }
    warehouse = WarehouseMap(
        width=9,
        height=5,
        blocked=frozenset(
            {
                Cell(2, 0),
                Cell(3, 0),
                Cell(5, 0),
                Cell(6, 0),
                Cell(2, 1),
                Cell(3, 1),
                Cell(5, 1),
                Cell(6, 1),
                Cell(2, 3),
                Cell(3, 3),
                Cell(5, 3),
                Cell(6, 3),
                Cell(2, 4),
                Cell(3, 4),
                Cell(5, 4),
                Cell(6, 4),
            }
        ),
        version="warehouse-demo-v1",
    )
    reservations = ReservationTable()
    planner = SpaceTimeAStar(warehouse, reservations)
    bidder = Bidder(planner, reservations)
    robots = (
        RobotState("R1", Cell(0, 2), 0.82, completed_tasks=4),
        RobotState("R2", Cell(4, 4), 0.68, completed_tasks=1),
        RobotState("R3", Cell(8, 2), 0.91, completed_tasks=3),
    )
    task = Task("T-100", Cell(4, 2), Cell(7, 2), 0, 30, payload_kg=600.0)
    bids = tuple(
        bidder.bid(robot, task, current_tick=0, auction_epoch=1) for robot in robots
    )
    winner = select_winner(bids)
    assert winner.execution_plan is not None
    plan_conflicts = reservations.commit(winner.execution_plan)
    if plan_conflicts:
        raise RuntimeError("winning plan failed its reservation commit")

    leases = ZoneLeaseRegistry()
    lease = leases.grant(
        "ZONE-A",
        winner.robot_id,
        plan_id=f"{task.task_id}:{winner.auction_epoch}",
        map_version=warehouse.version,
        current_tick=0,
        ttl_ticks=5,
    )

    network = DeterministicNetwork(
        NetworkConfig(
            minimum_latency_ticks=1, maximum_latency_ticks=3, duplicate_rate=0.25
        ),
        seed=seed,
    )
    for robot in robots:
        network.register(robot.robot_id)
    message = MessageEnvelope.create(
        kind="task_claim",
        sender_id=winner.robot_id,
        boot_id="boot-0",
        sequence=1,
        sent_tick=0,
        ttl_ticks=5,
        map_version=warehouse.version,
        payload={"task_id": task.task_id, "epoch": 1, "score": winner.score},
        signing_key=authentication_keys[winner.robot_id],
    )
    network.send(message, [robot.robot_id for robot in robots])
    network.advance(3)
    accepted_by: list[str] = []
    rejected_by: list[str] = []
    for robot in robots:
        if robot.robot_id == winner.robot_id:
            continue
        guard = ReplayGuard(
            schema_version="1.0",
            map_version=warehouse.version,
            authentication_keys=authentication_keys,
        )
        for received in network.receive(robot.robot_id):
            try:
                guard.accept(received, current_tick=3)
                accepted_by.append(robot.robot_id)
            except ValueError:
                rejected_by.append(robot.robot_id)

    return {
        "seed": seed,
        "map_version": warehouse.version,
        "task": task.task_id,
        "winner": winner.robot_id,
        "bids": [
            {
                "robot_id": bid.robot_id,
                "feasible": bid.feasible,
                "score": bid.score,
                "expected_finish_tick": bid.expected_finish_tick,
                "expected_soc": bid.expected_soc,
                "components": asdict(bid.components),
                "reason": bid.reason,
            }
            for bid in bids
        ],
        "reservations": {
            "vertices": reservations.vertex_count,
            "edges": reservations.edge_count,
        },
        "zone_lease": asdict(lease),
        "claim": {
            "message_id": message.message_id,
            "accepted_by": accepted_by,
            "rejected_duplicates_by": rejected_by,
        },
        "network_events": [asdict(event) for event in network.events],
    }


def run_consensus_demo(*, partition: bool = False) -> dict[str, object]:
    network = DeterministicNetwork(NetworkConfig(), seed=11)
    members = {"R1": "boot-r1", "R2": "boot-r2", "R3": "boot-r3"}
    authentication_keys = {
        "R1": b"demo-r1-key",
        "R2": b"demo-r2-key",
        "R3": b"demo-r3-key",
    }
    for robot_id in members:
        network.register(robot_id)
    if partition:
        network.isolate("R3")

    topology = {"R1": ("R2",), "R2": ("R1", "R3"), "R3": ("R2",)}
    replicas = {
        robot_id: AuctionReplica(
            robot_id=robot_id,
            boot_id=boot_id,
            members=members,
            authentication_keys=authentication_keys,
            map_version="warehouse-demo-v1",
            network=network,
            neighbors=topology[robot_id],
        )
        for robot_id, boot_id in members.items()
    }
    scores = {"R1": 0.82, "R2": 0.54, "R3": 0.67}
    workloads = {"R1": 4, "R2": 1, "R3": 3}
    for robot_id, replica in replicas.items():
        replica.observe_local_bid(
            Bid(
                robot_id=robot_id,
                task_id="T-100",
                auction_epoch=1,
                feasible=True,
                score=scores[robot_id],
                components=BidComponents(0.0, 0.0, 0.0, 0.0),
                expected_finish_tick=None,
                expected_soc=None,
                workload=workloads[robot_id],
            ),
            revision=1,
            current_tick=0,
        )

    for tick in range(3):
        for replica in replicas.values():
            replica.broadcast(current_tick=tick)
        network.advance(tick)
        for replica in replicas.values():
            replica.receive(current_tick=tick)

    return {
        "partitioned_robot": "R3" if partition else None,
        "replicas": {
            robot_id: {
                "known_bid_origins": [
                    record.robot_id for record in replica.records_for("T-100", 1)
                ],
                "complete_view": replica.has_complete_view("T-100", 1),
                "local_winner": (
                    replica.local_winner("T-100", 1).robot_id
                    if replica.local_winner("T-100", 1) is not None
                    else None
                ),
                "claim_candidate": (
                    replica.claim_candidate("T-100", 1).robot_id
                    if replica.claim_candidate("T-100", 1) is not None
                    else None
                ),
                "rejected_messages": sum(
                    event.kind == "rejected" for event in replica.events
                ),
            }
            for robot_id, replica in replicas.items()
        },
        "network_events": [asdict(event) for event in network.events],
    }
