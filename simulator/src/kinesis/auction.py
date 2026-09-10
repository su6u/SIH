from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol

from .allocation import Bid, select_winner
from .consensus import AuctionReplica
from .network import DeterministicNetwork, NetworkConfig


class AuctionStrategy(Protocol):
    def select(self, bids: tuple[Bid, ...], *, fairness_tolerance: float) -> Bid: ...


@dataclass(frozen=True, slots=True)
class CentralAuction:
    def select(self, bids: tuple[Bid, ...], *, fairness_tolerance: float) -> Bid:
        return select_winner(bids, fairness_tolerance=fairness_tolerance)


class EmulatedReplicatedAuction:
    """Single-process deterministic protocol simulator.

    This class intentionally creates every logical replica in one process. It
    is useful for seeded simulation and fault injection, but it is not a
    distributed deployment. Use ``DistributedRobotNode`` with one process per
    robot for the real peer runtime.
    """

    def __init__(
        self,
        *,
        map_version: str,
        boot_ids: Mapping[str, str],
        authentication_keys: Mapping[str, bytes],
        network: NetworkConfig = NetworkConfig(),
        seed: int = 0,
        maximum_rounds: int = 8,
        isolated: frozenset[str] = frozenset(),
    ) -> None:
        if not map_version:
            raise ValueError("map_version must not be empty")
        if set(boot_ids) != set(authentication_keys):
            raise ValueError("boot identities and authentication keys must match")
        if maximum_rounds <= 0:
            raise ValueError("maximum_rounds must be positive")
        if not isolated <= set(boot_ids):
            raise ValueError("isolated robots must belong to the auction membership")
        self._map_version = map_version
        self._boot_ids = dict(boot_ids)
        self._authentication_keys = dict(authentication_keys)
        self._network = network
        self._seed = seed
        self._maximum_rounds = maximum_rounds
        self._isolated = isolated

    def select(self, bids: tuple[Bid, ...], *, fairness_tolerance: float) -> Bid:
        if not bids:
            raise ValueError("auction has no bids")
        robot_ids = tuple(sorted(bid.robot_id for bid in bids))
        if len(set(robot_ids)) != len(robot_ids):
            raise ValueError("auction bids must have unique robot identifiers")
        if not set(robot_ids) <= set(self._boot_ids):
            raise ValueError("auction bidder is outside configured membership")
        task_keys = {(bid.task_id, bid.auction_epoch) for bid in bids}
        if len(task_keys) != 1:
            raise ValueError("all bids must refer to the same task and epoch")
        task_id, auction_epoch = next(iter(task_keys))
        members = {robot_id: self._boot_ids[robot_id] for robot_id in robot_ids}
        keys = {robot_id: self._authentication_keys[robot_id] for robot_id in robot_ids}
        transport = DeterministicNetwork(
            self._network,
            seed=self._seed + auction_epoch,
        )
        for robot_id in robot_ids:
            transport.register(robot_id)
            if robot_id in self._isolated:
                transport.isolate(robot_id)
        replicas = {
            robot_id: AuctionReplica(
                robot_id=robot_id,
                boot_id=members[robot_id],
                members=members,
                authentication_keys=keys,
                map_version=self._map_version,
                network=transport,
                neighbors=tuple(other for other in robot_ids if other != robot_id),
                fairness_tolerance=fairness_tolerance,
            )
            for robot_id in robot_ids
        }
        for bid in bids:
            replicas[bid.robot_id].observe_local_bid(bid, revision=0, current_tick=0)
        for tick in range(self._maximum_rounds):
            for replica in replicas.values():
                replica.broadcast(current_tick=tick)
            transport.advance(tick)
            for replica in replicas.values():
                replica.receive(current_tick=tick)
            if all(
                replica.has_complete_view(task_id, auction_epoch)
                for replica in replicas.values()
            ):
                claims = tuple(
                    replica.claim_candidate(task_id, auction_epoch)
                    for replica in replicas.values()
                )
                if any(claim is None for claim in claims):
                    raise ValueError("replicated auction has no common feasible winner")
                candidates = {claim.robot_id for claim in claims if claim is not None}
                if len(candidates) != 1:
                    raise ValueError(
                        "replicated auction replicas disagree on the winner"
                    )
                winner_id = next(iter(candidates))
                return next(bid for bid in bids if bid.robot_id == winner_id)
        raise ValueError("replicated auction did not reach a complete view")


# Backward-compatible name for existing scenarios. New code should use the
# explicit EmulatedReplicatedAuction name so simulation is not confused with a
# process- or device-distributed deployment.
ReplicatedAuction = EmulatedReplicatedAuction
