from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .allocation import Bid, BidComponents
from .distributed import DistributedRobotNode, RobotIntent, unix_time_ms
from .domain import Cell
from .peer_transport import PeerEndpoint, UdpPeerTransport


@dataclass(frozen=True, slots=True)
class PeerClusterConfig:
    map_version: str
    message_ttl_ms: int
    maximum_clock_skew_ms: int
    boot_ids: Mapping[str, str]
    authentication_keys: Mapping[str, bytes]
    endpoints: Mapping[str, PeerEndpoint]


def load_peer_cluster_config(path: str | Path) -> PeerClusterConfig:
    with Path(path).open(encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, dict) or set(raw) != {
        "schema_version",
        "map_version",
        "message_ttl_ms",
        "maximum_clock_skew_ms",
        "members",
    }:
        raise ValueError("peer cluster config fields do not match schema")
    if raw["schema_version"] != "1.0":
        raise ValueError("unsupported peer cluster config schema")
    if not isinstance(raw["map_version"], str) or not raw["map_version"]:
        raise ValueError("map_version must be a non-empty string")
    for field in ("message_ttl_ms", "maximum_clock_skew_ms"):
        if isinstance(raw[field], bool) or not isinstance(raw[field], int):
            raise ValueError(f"{field} must be an integer")
    if raw["message_ttl_ms"] <= 0 or raw["maximum_clock_skew_ms"] < 0:
        raise ValueError("peer cluster timing values are invalid")
    members = raw["members"]
    if not isinstance(members, dict) or len(members) < 2:
        raise ValueError("peer cluster requires at least two members")

    boot_ids: dict[str, str] = {}
    keys: dict[str, bytes] = {}
    endpoints: dict[str, PeerEndpoint] = {}
    for robot_id, member in members.items():
        if not isinstance(robot_id, str) or not robot_id:
            raise ValueError("robot identifiers must be non-empty strings")
        if not isinstance(member, dict) or set(member) != {
            "boot_id",
            "host",
            "port",
            "authentication_key_hex",
        }:
            raise ValueError(f"member fields are invalid for {robot_id}")
        boot_id = member["boot_id"]
        key_hex = member["authentication_key_hex"]
        if not isinstance(boot_id, str) or not boot_id:
            raise ValueError(f"boot_id is invalid for {robot_id}")
        if not isinstance(key_hex, str) or not key_hex:
            raise ValueError(f"authentication key is invalid for {robot_id}")
        try:
            key = bytes.fromhex(key_hex)
        except ValueError as error:
            raise ValueError(
                f"authentication key is not hexadecimal for {robot_id}"
            ) from error
        if len(key) < 16:
            raise ValueError(f"authentication key is too short for {robot_id}")
        boot_ids[robot_id] = boot_id
        keys[robot_id] = key
        endpoints[robot_id] = PeerEndpoint(member["host"], member["port"])
    return PeerClusterConfig(
        map_version=raw["map_version"],
        message_ttl_ms=raw["message_ttl_ms"],
        maximum_clock_skew_ms=raw["maximum_clock_skew_ms"],
        boot_ids=boot_ids,
        authentication_keys=keys,
        endpoints=endpoints,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kinesis-peer",
        description=(
            "Run exactly one Kinesis robot peer. Start one process per robot."
        ),
    )
    parser.add_argument("config", help="static peer cluster JSON")
    parser.add_argument("--robot-id", required=True)
    parser.add_argument("--cell", required=True, type=_cell)
    parser.add_argument(
        "--path",
        required=True,
        type=_path,
        help="semicolon-separated cells, for example 0,0;1,0;2,0",
    )
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--battery-soc", type=float, default=0.9)
    parser.add_argument("--position-uncertainty-m", type=float, default=0.05)
    parser.add_argument("--step-duration-ms", type=int, default=100)
    parser.add_argument("--mode", default="moving")
    parser.add_argument("--bid-score", required=True, type=float)
    parser.add_argument("--workload", type=int, default=0)
    parser.add_argument("--auction-epoch", type=int, default=1)
    parser.add_argument("--duration-ms", type=int, default=2_000)
    parser.add_argument("--period-ms", type=int, default=100)
    parser.add_argument("--start-at-ms", type=int)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.duration_ms <= 0 or args.period_ms <= 0:
        raise SystemExit("duration and period must be positive")
    config = load_peer_cluster_config(args.config)
    if args.robot_id not in config.boot_ids:
        raise SystemExit(f"robot {args.robot_id!r} is not in the peer cluster")
    if args.path[0] != args.cell:
        raise SystemExit("path must begin at --cell")

    transport = UdpPeerTransport(
        local_id=args.robot_id,
        endpoints=config.endpoints,
    )
    node = DistributedRobotNode(
        robot_id=args.robot_id,
        boot_id=config.boot_ids[args.robot_id],
        members=config.boot_ids,
        authentication_keys=config.authentication_keys,
        map_version=config.map_version,
        transport=transport,
        neighbors=tuple(
            robot_id for robot_id in config.boot_ids if robot_id != args.robot_id
        ),
        message_ttl_ms=config.message_ttl_ms,
        maximum_clock_skew_ms=config.maximum_clock_skew_ms,
    )
    intent = RobotIntent(
        robot_id=args.robot_id,
        boot_id=config.boot_ids[args.robot_id],
        revision=1,
        plan_epoch=1,
        step_duration_ms=args.step_duration_ms,
        cell=args.cell,
        path=args.path,
        task_id=args.task_id,
        battery_soc=args.battery_soc,
        position_uncertainty_m=args.position_uncertainty_m,
        mode=args.mode,
    )
    bid = Bid(
        robot_id=args.robot_id,
        task_id=args.task_id,
        auction_epoch=args.auction_epoch,
        feasible=True,
        score=args.bid_score,
        components=BidComponents(0.0, 0.0, 0.0, 0.0),
        expected_finish_tick=None,
        expected_soc=args.battery_soc,
        workload=args.workload,
    )
    start_at = args.start_at_ms or unix_time_ms()
    try:
        while unix_time_ms() < start_at:
            time.sleep(0.005)
        deadline = start_at + args.duration_ms
        next_publish = start_at
        first_publish = True
        while unix_time_ms() <= deadline:
            now = unix_time_ms()
            node.poll(current_time_ms=now)
            if now >= next_publish:
                node.publish_intent(intent, current_time_ms=now)
                if first_publish:
                    node.publish_bid(bid, revision=1, current_time_ms=now)
                    first_publish = False
                else:
                    node.gossip_bid_view(current_time_ms=now)
                next_publish += args.period_ms
            time.sleep(0.005)
        now = unix_time_ms()
        node.poll(current_time_ms=now)
        winner = node.claim_candidate(
            args.task_id,
            args.auction_epoch,
            current_time_ms=now,
        )
        payload = {
            "schema_version": "1.0",
            "process_id": os.getpid(),
            "robot_id": args.robot_id,
            "complete_bid_view": node.has_complete_bid_view(
                args.task_id, args.auction_epoch
            ),
            "fresh_membership": node.has_fresh_membership(current_time_ms=now),
            "authorized_winner": winner.robot_id if winner is not None else None,
            "peer_intents": [
                item.robot_id for item in node.fresh_intents(current_time_ms=now)
            ],
            "intent_conflicts": [
                {
                    "peer_id": item.peer_id,
                    "kind": item.kind,
                    "starts_at_ms": item.starts_at_ms,
                    "ends_at_ms": item.ends_at_ms,
                }
                for item in node.intent_conflicts(current_time_ms=now)
            ],
            "accepted_messages": sum(
                event.kind == "accepted" for event in node.events
            ),
            "rejected_messages": sum(
                event.kind == "rejected" for event in node.events
            ),
        }
        print(json.dumps(payload, allow_nan=False, sort_keys=True))
        return 0 if winner is not None else 2
    finally:
        node.close()


def _cell(raw: str) -> Cell:
    try:
        x, y = raw.split(",", maxsplit=1)
        return Cell(int(x), int(y))
    except (TypeError, ValueError) as error:
        raise argparse.ArgumentTypeError("cell must be X,Y") from error


def _path(raw: str) -> tuple[Cell, ...]:
    try:
        path = tuple(_cell(item) for item in raw.split(";"))
    except argparse.ArgumentTypeError as error:
        raise argparse.ArgumentTypeError(
            "path must be semicolon-separated X,Y cells"
        ) from error
    if not path:
        raise argparse.ArgumentTypeError("path must not be empty")
    return path


if __name__ == "__main__":
    raise SystemExit(main())
