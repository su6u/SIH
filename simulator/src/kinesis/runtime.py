from __future__ import annotations

import hashlib

from .auction import EmulatedReplicatedAuction
from .network import NetworkConfig
from .scenario import Scenario


def replicated_auction_for(
    scenario: Scenario,
    *,
    network: NetworkConfig = NetworkConfig(),
    isolated: frozenset[str] = frozenset(),
) -> EmulatedReplicatedAuction:
    """Build the deterministic research transport used by a scenario run.

    Keys are derived test credentials, not deployment secrets. This keeps replay
    deterministic while exercising the exact authentication and replay guards.
    """

    robot_ids = tuple(sorted(robot.robot_id for robot in scenario.robots))
    boot_ids = {
        robot.robot_id: f"{robot.boot_id}:{robot.robot_id}"
        for robot in scenario.robots
    }
    keys = {
        robot_id: hashlib.sha256(
            f"kinesis-research:{scenario.seed}:{robot_id}".encode("utf-8")
        ).digest()
        for robot_id in robot_ids
    }
    return EmulatedReplicatedAuction(
        map_version=scenario.warehouse_map.version,
        boot_ids=boot_ids,
        authentication_keys=keys,
        network=network,
        seed=scenario.seed,
        isolated=isolated,
    )
