from dataclasses import replace

import pytest

from kinesis.allocation import Bid, BidComponents
from kinesis.consensus import AuctionProtocolError, AuctionReplica
from kinesis.network import DeterministicNetwork, NetworkConfig
from kinesis.protocol import MessageEnvelope


KEYS = {"R1": b"r1-test-key", "R2": b"r2-test-key", "R3": b"r3-test-key"}


def _bid(robot_id: str, score: float, workload: int = 0) -> Bid:
    return Bid(
        robot_id=robot_id,
        task_id="T1",
        auction_epoch=1,
        feasible=True,
        score=score,
        components=BidComponents(0.0, 0.0, 0.0, 0.0),
        expected_finish_tick=10,
        expected_soc=0.8,
        workload=workload,
    )


def _line_cluster(
    *, isolated: str | None = None
) -> tuple[DeterministicNetwork, dict[str, AuctionReplica]]:
    network = DeterministicNetwork(NetworkConfig(), seed=4)
    members = {"R1": "B1", "R2": "B2", "R3": "B3"}
    for robot_id in members:
        network.register(robot_id)
    if isolated is not None:
        network.isolate(isolated)
    replicas = {
        "R1": AuctionReplica(
            robot_id="R1",
            boot_id="B1",
            members=members,
            authentication_keys=KEYS,
            map_version="M1",
            network=network,
            neighbors=("R2",),
        ),
        "R2": AuctionReplica(
            robot_id="R2",
            boot_id="B2",
            members=members,
            authentication_keys=KEYS,
            map_version="M1",
            network=network,
            neighbors=("R1", "R3"),
        ),
        "R3": AuctionReplica(
            robot_id="R3",
            boot_id="B3",
            members=members,
            authentication_keys=KEYS,
            map_version="M1",
            network=network,
            neighbors=("R2",),
        ),
    }
    for robot_id, replica in replicas.items():
        replica.observe_local_bid(
            _bid(robot_id, {"R1": 0.8, "R2": 0.5, "R3": 0.7}[robot_id]),
            revision=1,
            current_tick=0,
        )
    return network, replicas


def _run_rounds(
    network: DeterministicNetwork, replicas: dict[str, AuctionReplica], count: int
) -> None:
    for tick in range(count):
        for replica in replicas.values():
            replica.broadcast(current_tick=tick)
        network.advance(tick)
        for replica in replicas.values():
            replica.receive(current_tick=tick)


def test_bid_gossip_converges_across_a_multi_hop_topology() -> None:
    network, replicas = _line_cluster()

    _run_rounds(network, replicas, 2)

    assert all(replica.has_complete_view("T1", 1) for replica in replicas.values())
    assert {
        replica.claim_candidate("T1", 1).robot_id for replica in replicas.values()
    } == {"R2"}


def test_partitioned_replicas_refuse_to_authorize_partial_view_claims() -> None:
    network, replicas = _line_cluster(isolated="R3")

    _run_rounds(network, replicas, 3)

    assert replicas["R1"].local_winner("T1", 1).robot_id == "R2"
    assert replicas["R1"].claim_candidate("T1", 1) is None
    assert replicas["R3"].claim_candidate("T1", 1) is None


def test_newer_bid_revision_propagates_and_changes_the_winner() -> None:
    network, replicas = _line_cluster()
    _run_rounds(network, replicas, 2)
    replicas["R1"].observe_local_bid(_bid("R1", 0.3), revision=2, current_tick=2)

    for tick in range(2, 4):
        for replica in replicas.values():
            replica.broadcast(current_tick=tick)
        network.advance(tick)
        for replica in replicas.values():
            replica.receive(current_tick=tick)

    assert {
        replica.claim_candidate("T1", 1).robot_id for replica in replicas.values()
    } == {"R1"}


def test_replica_rejects_origin_equivocation_at_same_revision() -> None:
    network, replicas = _line_cluster()
    with pytest.raises(AuctionProtocolError, match="equivocation"):
        replicas["R1"].observe_local_bid(_bid("R1", 0.2), revision=1, current_tick=1)


def test_replica_rejects_bid_originating_for_another_robot() -> None:
    _, replicas = _line_cluster()
    with pytest.raises(AuctionProtocolError, match="only its own bid"):
        replicas["R1"].observe_local_bid(_bid("R2", 0.2), revision=2, current_tick=1)


def test_non_finite_bid_scores_are_rejected_before_protocol_serialization() -> None:
    with pytest.raises(ValueError, match="finite"):
        _bid("R1", float("inf"))


def test_invalid_gossip_envelope_rolls_back_earlier_records_from_same_message() -> None:
    network, replicas = _line_cluster()
    message = MessageEnvelope.create(
        kind="auction_bid_gossip",
        sender_id="R2",
        boot_id="B2",
        sequence=0,
        sent_tick=0,
        ttl_ticks=5,
        map_version="M1",
        payload={
            "records": [
                {
                    "task_id": "T1",
                    "auction_epoch": 1,
                    "robot_id": "R3",
                    "boot_id": "B3",
                    "revision": 2,
                    "feasible": True,
                    "score": 0.1,
                    "workload": 0,
                },
                {"malformed": True},
            ]
        },
        signing_key=KEYS["R2"],
    )
    network.send(message, ["R1"])
    network.advance(0)

    replicas["R1"].receive(current_tick=0)

    assert [record.robot_id for record in replicas["R1"].records_for("T1", 1)] == ["R1"]
    assert replicas["R1"].events[-1].kind == "rejected"


def test_rejected_high_sequence_does_not_consume_replay_state() -> None:
    network, replicas = _line_cluster()
    malformed = MessageEnvelope.create(
        kind="auction_bid_gossip",
        sender_id="R2",
        boot_id="B2",
        sequence=10,
        sent_tick=0,
        ttl_ticks=5,
        map_version="M1",
        payload={"records": [{"malformed": True}]},
        signing_key=KEYS["R2"],
    )
    valid = MessageEnvelope.create(
        kind="auction_bid_gossip",
        sender_id="R2",
        boot_id="B2",
        sequence=1,
        sent_tick=0,
        ttl_ticks=5,
        map_version="M1",
        payload={
            "records": [
                {
                    "task_id": "T1",
                    "auction_epoch": 1,
                    "robot_id": "R2",
                    "boot_id": "B2",
                    "revision": 1,
                    "feasible": True,
                    "score": 0.5,
                    "workload": 0,
                }
            ]
        },
        signing_key=KEYS["R2"],
    )
    network.send(malformed, ["R1"])
    network.send(valid, ["R1"])
    network.advance(0)

    replicas["R1"].receive(current_tick=0)

    assert [record.robot_id for record in replicas["R1"].records_for("T1", 1)] == [
        "R1",
        "R2",
    ]
