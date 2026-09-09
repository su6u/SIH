from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from swarmroute.allocation import Bid, BidComponents
from swarmroute.distributed import DistributedRobotNode, RobotIntent, unix_time_ms
from swarmroute.domain import Cell
from swarmroute.durable import JsonPeerStateStore
from swarmroute.peer_transport import PeerEndpoint, UdpPeerTransport
from swarmroute.protocol import MessageEnvelope


ROBOT_IDS = ("R1", "R2", "R3")
BOOT_IDS = {robot_id: f"BOOT-{robot_id}" for robot_id in ROBOT_IDS}
KEYS = {robot_id: (f"distributed-test-key-{robot_id}".encode() * 2) for robot_id in ROBOT_IDS}


def _free_udp_port() -> int:
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])
    finally:
        probe.close()


def _endpoints() -> dict[str, PeerEndpoint]:
    ports: set[int] = set()
    while len(ports) < len(ROBOT_IDS):
        ports.add(_free_udp_port())
    return {
        robot_id: PeerEndpoint("127.0.0.1", port)
        for robot_id, port in zip(ROBOT_IDS, sorted(ports), strict=True)
    }


def _bid(robot_id: str) -> Bid:
    return Bid(
        robot_id=robot_id,
        task_id="T1",
        auction_epoch=3,
        feasible=True,
        score={"R1": 0.8, "R2": 0.4, "R3": 0.6}[robot_id],
        components=BidComponents(0.0, 0.0, 0.0, 0.0),
        expected_finish_tick=None,
        expected_soc=0.8,
        workload=0,
    )


def _intent(robot_id: str) -> RobotIntent:
    start = Cell(int(robot_id[-1]), 0)
    return RobotIntent(
        robot_id=robot_id,
        boot_id=BOOT_IDS[robot_id],
        revision=1,
        plan_epoch=1,
        step_duration_ms=100,
        cell=start,
        path=(start, Cell(start.x, 1)),
        task_id="T1",
        battery_soc=0.8,
        position_uncertainty_m=0.05,
        mode="moving",
    )


def test_message_envelope_has_a_strict_wire_round_trip() -> None:
    message = MessageEnvelope.create(
        kind="robot_heartbeat",
        sender_id="R1",
        boot_id="BOOT-R1",
        sequence=4,
        sent_tick=100,
        ttl_ticks=50,
        map_version="M1",
        payload={"robot_id": "R1", "boot_id": "BOOT-R1"},
        signing_key=KEYS["R1"],
    )

    decoded = MessageEnvelope.from_bytes(message.to_bytes())

    assert decoded == message
    decoded.validate_integrity(KEYS["R1"])


def test_three_udp_peers_exchange_intent_and_converge_without_a_coordinator() -> None:
    endpoints = _endpoints()
    nodes: dict[str, DistributedRobotNode] = {}
    try:
        for robot_id in ROBOT_IDS:
            nodes[robot_id] = DistributedRobotNode(
                robot_id=robot_id,
                boot_id=BOOT_IDS[robot_id],
                members=BOOT_IDS,
                authentication_keys=KEYS,
                map_version="M1",
                transport=UdpPeerTransport(
                    local_id=robot_id,
                    endpoints=endpoints,
                ),
                neighbors=tuple(item for item in ROBOT_IDS if item != robot_id),
                message_ttl_ms=500,
            )
        now = unix_time_ms()
        for robot_id, node in nodes.items():
            node.publish_intent(_intent(robot_id), current_time_ms=now)
            node.publish_bid(_bid(robot_id), revision=1, current_time_ms=now)

        for round_index in range(4):
            time.sleep(0.01)
            current = unix_time_ms()
            for node in nodes.values():
                node.poll(current_time_ms=current)
            for node in nodes.values():
                node.gossip_bid_view(current_time_ms=current + round_index + 1)

        current = unix_time_ms()
        for node in nodes.values():
            node.poll(current_time_ms=current)

        assert {
            node.claim_candidate("T1", 3, current_time_ms=current).robot_id
            for node in nodes.values()
        } == {"R2"}
        assert all(
            {intent.robot_id for intent in node.fresh_intents(current_time_ms=current)}
            == set(ROBOT_IDS) - {node.robot_id}
            for node in nodes.values()
        )
    finally:
        for node in nodes.values():
            node.close()


def test_peers_detect_a_time_overlapping_reverse_edge_from_received_intent() -> None:
    robot_ids = ("R1", "R2")
    boot_ids = {robot_id: BOOT_IDS[robot_id] for robot_id in robot_ids}
    keys = {robot_id: KEYS[robot_id] for robot_id in robot_ids}
    all_endpoints = _endpoints()
    endpoints = {robot_id: all_endpoints[robot_id] for robot_id in robot_ids}
    nodes: dict[str, DistributedRobotNode] = {}
    try:
        for robot_id in robot_ids:
            nodes[robot_id] = DistributedRobotNode(
                robot_id=robot_id,
                boot_id=boot_ids[robot_id],
                members=boot_ids,
                authentication_keys=keys,
                map_version="M1",
                transport=UdpPeerTransport(
                    local_id=robot_id,
                    endpoints=endpoints,
                ),
                neighbors=tuple(item for item in robot_ids if item != robot_id),
                message_ttl_ms=500,
            )
        now = unix_time_ms()
        nodes["R1"].publish_intent(
            RobotIntent(
                "R1",
                boot_ids["R1"],
                1,
                1,
                100,
                Cell(1, 0),
                (Cell(1, 0), Cell(2, 0)),
                "T1",
                0.8,
                0.05,
                "moving",
            ),
            current_time_ms=now,
        )
        nodes["R2"].publish_intent(
            RobotIntent(
                "R2",
                boot_ids["R2"],
                1,
                1,
                100,
                Cell(2, 0),
                (Cell(2, 0), Cell(1, 0)),
                "T1",
                0.8,
                0.05,
                "moving",
            ),
            current_time_ms=now,
        )
        time.sleep(0.01)
        current = unix_time_ms()
        for node in nodes.values():
            node.poll(current_time_ms=current)

        conflicts = nodes["R1"].intent_conflicts(current_time_ms=current)
        assert conflicts, (
            nodes["R1"].events,
            nodes["R1"].fresh_intents(current_time_ms=current),
        )
        assert [item.kind for item in conflicts] == ["reverse_edge"]
        assert [item.peer_id for item in conflicts] == ["R2"]
    finally:
        for node in nodes.values():
            node.close()


def test_authorization_fails_closed_after_membership_freshness_expires() -> None:
    endpoints = _endpoints()
    nodes: dict[str, DistributedRobotNode] = {}
    try:
        for robot_id in ROBOT_IDS:
            nodes[robot_id] = DistributedRobotNode(
                robot_id=robot_id,
                boot_id=BOOT_IDS[robot_id],
                members=BOOT_IDS,
                authentication_keys=KEYS,
                map_version="M1",
                transport=UdpPeerTransport(
                    local_id=robot_id,
                    endpoints=endpoints,
                ),
                neighbors=tuple(item for item in ROBOT_IDS if item != robot_id),
                message_ttl_ms=60,
            )
        now = unix_time_ms()
        for robot_id, node in nodes.items():
            node.publish_intent(_intent(robot_id), current_time_ms=now)
            node.publish_bid(_bid(robot_id), revision=1, current_time_ms=now)
        for _ in range(3):
            time.sleep(0.01)
            current = unix_time_ms()
            for node in nodes.values():
                node.poll(current_time_ms=current)
            for node in nodes.values():
                node.gossip_bid_view(current_time_ms=current)

        assert nodes["R1"].claim_candidate(
            "T1", 3, current_time_ms=unix_time_ms()
        ) is not None
        assert nodes["R1"].has_live_quorum(current_time_ms=unix_time_ms())

        time.sleep(0.08)
        expired = unix_time_ms()

        assert nodes["R1"].has_complete_bid_view("T1", 3)
        assert not nodes["R1"].has_fresh_membership(current_time_ms=expired)
        assert not nodes["R1"].has_live_quorum(current_time_ms=expired)
        assert nodes["R1"].claim_candidate(
            "T1", 3, current_time_ms=expired
        ) is None
    finally:
        for node in nodes.values():
            node.close()


def test_task_completion_is_originated_by_winner_and_replicates() -> None:
    endpoints = _endpoints()
    nodes: dict[str, DistributedRobotNode] = {}
    try:
        for robot_id in ROBOT_IDS:
            nodes[robot_id] = DistributedRobotNode(
                robot_id=robot_id,
                boot_id=BOOT_IDS[robot_id],
                members=BOOT_IDS,
                authentication_keys=KEYS,
                map_version="M1",
                transport=UdpPeerTransport(
                    local_id=robot_id,
                    endpoints=endpoints,
                ),
                neighbors=tuple(item for item in ROBOT_IDS if item != robot_id),
                message_ttl_ms=500,
            )
        now = unix_time_ms()
        nodes["R2"].publish_task_claim(
            "T1", 3, claim_revision=1, current_time_ms=now
        )
        nodes["R2"].publish_task_done(
            "T1", 3, completion_revision=1, current_time_ms=now
        )
        time.sleep(0.01)
        current = unix_time_ms()
        for node in nodes.values():
            node.poll(current_time_ms=current)

        assert all(node.task_completed("T1", 3) for node in nodes.values())
        assert all(node.task_claimed("T1", 3) for node in nodes.values())
        assert all(node.claim_winner("T1", 3) == "R2" for node in nodes.values())
        assert all(
            node.completion_winner("T1", 3) == "R2" for node in nodes.values()
        )
    finally:
        for node in nodes.values():
            node.close()


def test_majority_membership_removal_fences_the_removed_peer() -> None:
    endpoints = _endpoints()
    nodes: dict[str, DistributedRobotNode] = {}
    try:
        for robot_id in ROBOT_IDS:
            nodes[robot_id] = DistributedRobotNode(
                robot_id=robot_id,
                boot_id=BOOT_IDS[robot_id],
                members=BOOT_IDS,
                authentication_keys=KEYS,
                map_version="M1",
                transport=UdpPeerTransport(local_id=robot_id, endpoints=endpoints),
                neighbors=tuple(item for item in ROBOT_IDS if item != robot_id),
                message_ttl_ms=500,
            )
        now = unix_time_ms()
        nodes["R1"].publish_task_claim(
            "T-before-reconfiguration", 0, claim_revision=1, current_time_ms=now
        )
        nodes["R1"].publish_membership_vote(
            {"R1", "R2"}, current_time_ms=now + 1
        )
        nodes["R2"].publish_membership_vote(
            {"R1", "R2"}, current_time_ms=now + 2
        )
        time.sleep(0.01)
        for node in nodes.values():
            node.poll(current_time_ms=unix_time_ms())

        assert nodes["R1"].active_members == ("R1", "R2")
        assert nodes["R2"].active_members == ("R1", "R2")
        assert nodes["R1"].membership_epoch == 1
        assert nodes["R2"].membership_epoch == 1
        assert nodes["R1"].claim_winner("T-before-reconfiguration", 0) is None
        with pytest.raises(ValueError, match="active fence"):
            nodes["R1"].publish_task_done(
                "T-before-reconfiguration",
                0,
                completion_revision=1,
                current_time_ms=unix_time_ms(),
            )
        assert not nodes["R3"].is_active_member
        with pytest.raises(ValueError, match="fenced"):
            nodes["R3"].publish_heartbeat()
    finally:
        for node in nodes.values():
            node.close()


def test_durable_state_restores_fences_and_never_reuses_sequence(
    tmp_path: Path,
) -> None:
    robot_ids = ("R1", "R2")
    endpoints = {key: value for key, value in _endpoints().items() if key in robot_ids}
    boot_ids = {key: BOOT_IDS[key] for key in robot_ids}
    keys = {key: KEYS[key] for key in robot_ids}
    store = JsonPeerStateStore(tmp_path / "R1-state.json")
    observer = DistributedRobotNode(
        robot_id="R2",
        boot_id=boot_ids["R2"],
        members=boot_ids,
        authentication_keys=keys,
        map_version="M1",
        transport=UdpPeerTransport(local_id="R2", endpoints=endpoints),
        neighbors=("R1",),
        message_ttl_ms=500,
    )
    first = DistributedRobotNode(
        robot_id="R1",
        boot_id=boot_ids["R1"],
        members=boot_ids,
        authentication_keys=keys,
        map_version="M1",
        transport=UdpPeerTransport(local_id="R1", endpoints=endpoints),
        neighbors=("R2",),
        message_ttl_ms=500,
        state_store=store,
    )
    try:
        now = unix_time_ms()
        first_intent_revision = first.next_local_revision("intent")
        first.publish_task_claim("T1", 3, claim_revision=1, current_time_ms=now)
        first.publish_task_done(
            "T1", 3, completion_revision=1, current_time_ms=now + 1
        )
        first.close()
        restored = DistributedRobotNode(
            robot_id="R1",
            boot_id=boot_ids["R1"],
            members=boot_ids,
            authentication_keys=keys,
            map_version="M1",
            transport=UdpPeerTransport(local_id="R1", endpoints=endpoints),
            neighbors=("R2",),
            message_ttl_ms=500,
            state_store=store,
        )
        try:
            assert restored.claim_winner("T1", 3) == "R1"
            assert restored.completion_winner("T1", 3) == "R1"
            assert (
                restored.next_local_revision("intent") > first_intent_revision
            )
            restored.publish_heartbeat(current_time_ms=now + 2)
            time.sleep(0.01)
            received = observer.poll(current_time_ms=unix_time_ms())
            assert received >= 1
            accepted = [event for event in observer.events if event.kind == "accepted"]
            assert accepted
        finally:
            restored.close()
    finally:
        observer.close()


def test_peer_cli_runs_three_independent_processes(tmp_path: Path) -> None:
    endpoints = _endpoints()
    config = {
        "schema_version": "1.0",
        "map_version": "M1",
        "message_ttl_ms": 700,
        "maximum_clock_skew_ms": 250,
        "members": {
            robot_id: {
                "boot_id": BOOT_IDS[robot_id],
                "host": endpoints[robot_id].host,
                "port": endpoints[robot_id].port,
                "authentication_key_hex": KEYS[robot_id].hex(),
            }
            for robot_id in ROBOT_IDS
        },
    }
    config_path = tmp_path / "peers.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    start_at = unix_time_ms() + 600
    processes: list[subprocess.Popen[str]] = []
    for index, robot_id in enumerate(ROBOT_IDS, start=1):
        command = [
            sys.executable,
            "-m",
            "swarmroute.peer_cli",
            str(config_path),
            "--robot-id",
            robot_id,
            "--cell",
            f"{index},0",
            "--path",
            f"{index},0;{index},1",
            "--task-id",
            "T1",
            "--bid-score",
            str({"R1": 0.8, "R2": 0.4, "R3": 0.6}[robot_id]),
            "--auction-epoch",
            "3",
            "--duration-ms",
            "1400",
            "--period-ms",
            "60",
            "--start-at-ms",
            str(start_at),
        ]
        processes.append(
            subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env={**os.environ, "PYTHONPATH": "src"},
            )
        )

    results: list[dict[str, object]] = []
    for process in processes:
        stdout, stderr = process.communicate(timeout=6)
        assert process.returncode == 0, stderr
        results.append(json.loads(stdout))

    assert len({result["process_id"] for result in results}) == 3
    assert {result["robot_id"] for result in results} == set(ROBOT_IDS)
    assert {result["authorized_winner"] for result in results} == {"R2"}
    assert all(result["complete_bid_view"] for result in results)
    assert all(result["fresh_membership"] for result in results)
    assert all(len(result["peer_intents"]) == 2 for result in results)
