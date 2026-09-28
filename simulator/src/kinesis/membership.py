from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping


class MembershipError(ValueError):
    pass


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


@dataclass(frozen=True, slots=True)
class MembershipView:
    epoch: int
    predecessor_digest: str
    members: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if self.epoch < 0 or not self.predecessor_digest or not self.members:
            raise MembershipError("membership view fields are invalid")
        if tuple(sorted(self.members)) != self.members:
            raise MembershipError("membership members must be sorted")
        robot_ids = [robot_id for robot_id, _ in self.members]
        if len(set(robot_ids)) != len(robot_ids):
            raise MembershipError("membership robot identifiers must be unique")
        if any(not robot_id or not boot_id for robot_id, boot_id in self.members):
            raise MembershipError("membership identities must not be empty")

    @classmethod
    def initial(cls, members: Mapping[str, str]) -> "MembershipView":
        return cls(0, "genesis", tuple(sorted(members.items())))

    @property
    def digest(self) -> str:
        return hashlib.sha256(_canonical(self.to_mapping())).hexdigest()

    @property
    def member_map(self) -> dict[str, str]:
        return dict(self.members)

    @property
    def quorum_size(self) -> int:
        return len(self.members) // 2 + 1

    def to_mapping(self) -> dict[str, Any]:
        return {
            "epoch": self.epoch,
            "predecessor_digest": self.predecessor_digest,
            "members": [
                {"robot_id": robot_id, "boot_id": boot_id}
                for robot_id, boot_id in self.members
            ],
        }

    @classmethod
    def from_mapping(cls, raw: Any) -> "MembershipView":
        if not isinstance(raw, dict) or set(raw) != {
            "epoch",
            "predecessor_digest",
            "members",
        }:
            raise MembershipError("membership view schema is invalid")
        epoch = raw["epoch"]
        predecessor = raw["predecessor_digest"]
        members = raw["members"]
        if isinstance(epoch, bool) or not isinstance(epoch, int):
            raise MembershipError("membership epoch must be an integer")
        if not isinstance(predecessor, str) or not predecessor:
            raise MembershipError("membership predecessor is invalid")
        if not isinstance(members, list) or not members:
            raise MembershipError("membership members must be a non-empty array")
        parsed: list[tuple[str, str]] = []
        for member in members:
            if not isinstance(member, dict) or set(member) != {"robot_id", "boot_id"}:
                raise MembershipError("membership member schema is invalid")
            robot_id = member["robot_id"]
            boot_id = member["boot_id"]
            if not isinstance(robot_id, str) or not isinstance(boot_id, str):
                raise MembershipError("membership identities must be strings")
            parsed.append((robot_id, boot_id))
        return cls(epoch, predecessor, tuple(parsed))


@dataclass(frozen=True, slots=True)
class MembershipVote:
    voter_id: str
    view: MembershipView

    def __post_init__(self) -> None:
        if not self.voter_id:
            raise MembershipError("membership voter must not be empty")

    def to_mapping(self) -> dict[str, Any]:
        return {"voter_id": self.voter_id, "view": self.view.to_mapping()}

    @classmethod
    def from_mapping(cls, raw: Any) -> "MembershipVote":
        if not isinstance(raw, dict) or set(raw) != {"voter_id", "view"}:
            raise MembershipError("membership vote schema is invalid")
        voter_id = raw["voter_id"]
        if not isinstance(voter_id, str) or not voter_id:
            raise MembershipError("membership voter is invalid")
        return cls(voter_id, MembershipView.from_mapping(raw["view"]))


class MembershipState:
    """Removal-only, majority-backed membership epochs.

    Additions require joint consensus and state transfer, so this state machine
    deliberately rejects them.  A peer may cast at most one durable vote for a
    target epoch.  Any two majorities of the predecessor view intersect.
    """

    def __init__(self, known_members: Mapping[str, str]) -> None:
        if len(known_members) < 2:
            raise MembershipError("distributed membership needs at least two robots")
        self.known_members = dict(known_members)
        self.current = MembershipView.initial(known_members)
        self._history: list[MembershipView] = [self.current]
        self._votes: dict[tuple[int, str], MembershipVote] = {}

    @property
    def votes(self) -> tuple[MembershipVote, ...]:
        return tuple(
            sorted(
                self._votes.values(),
                key=lambda item: (item.view.epoch, item.voter_id),
            )
        )

    @property
    def history(self) -> tuple[MembershipView, ...]:
        return tuple(self._history)

    def create_vote(
        self, voter_id: str, retained_members: set[str] | frozenset[str]
    ) -> MembershipVote:
        current = self.current.member_map
        retained = set(retained_members)
        if voter_id not in current or voter_id not in retained:
            raise MembershipError("only a retained current member may vote")
        if not retained or not retained < set(current):
            raise MembershipError("new membership must remove at least one member")
        view = MembershipView(
            self.current.epoch + 1,
            self.current.digest,
            tuple(sorted((robot_id, current[robot_id]) for robot_id in retained)),
        )
        return MembershipVote(voter_id, view)

    def merge(self, vote: MembershipVote) -> MembershipView | None:
        view = vote.view
        if view.epoch <= self.current.epoch:
            if view.epoch == self.current.epoch and view.digest == self.current.digest:
                return None
            raise MembershipError("membership vote targets an obsolete epoch")
        if view.epoch != self.current.epoch + 1:
            raise MembershipError("membership epochs must advance by one")
        if view.predecessor_digest != self.current.digest:
            raise MembershipError("membership predecessor does not match")
        current = self.current.member_map
        proposed = view.member_map
        if not set(proposed) < set(current):
            raise MembershipError("membership change must be removal-only")
        if any(current.get(robot_id) != boot_id for robot_id, boot_id in proposed.items()):
            raise MembershipError("membership boot identity changed")
        if vote.voter_id not in current:
            raise MembershipError("membership voter is outside predecessor view")
        key = (view.epoch, vote.voter_id)
        existing = self._votes.get(key)
        if existing is not None:
            if existing.view.digest != view.digest:
                raise MembershipError("membership voter equivocated")
            return self._install_if_quorum(view)
        self._votes[key] = vote
        return self._install_if_quorum(view)

    def restore(
        self,
        history: tuple[MembershipView, ...],
        votes: tuple[MembershipVote, ...],
    ) -> None:
        initial = MembershipView.initial(self.known_members)
        if not history or history[0].digest != initial.digest:
            raise MembershipError("persisted genesis membership changed")
        self._votes = {}
        for vote in votes:
            key = (vote.view.epoch, vote.voter_id)
            existing = self._votes.get(key)
            if existing is not None and existing.view.digest != vote.view.digest:
                raise MembershipError("persisted membership vote equivocation")
            self._votes[key] = vote
        previous = initial
        validated = [initial]
        for view in history[1:]:
            if view.epoch != previous.epoch + 1:
                raise MembershipError("persisted membership epochs are not consecutive")
            if view.predecessor_digest != previous.digest:
                raise MembershipError("persisted membership predecessor changed")
            proposed = view.member_map
            if not set(proposed) < set(previous.member_map):
                raise MembershipError("persisted membership is not removal-only")
            if any(
                previous.member_map.get(robot_id) != boot_id
                for robot_id, boot_id in proposed.items()
            ):
                raise MembershipError("persisted membership boot identity changed")
            supporters = {
                vote.voter_id
                for vote in votes
                if vote.view.digest == view.digest
                and vote.voter_id in previous.member_map
            }
            if len(supporters) < previous.quorum_size:
                raise MembershipError("persisted membership lacks a quorum proof")
            validated.append(view)
            previous = view
        predecessor_by_target_epoch = {
            view.epoch + 1: view for view in validated
        }
        for vote in votes:
            predecessor = predecessor_by_target_epoch.get(vote.view.epoch)
            if predecessor is None:
                raise MembershipError("persisted vote has no known predecessor")
            if vote.view.epoch > validated[-1].epoch + 1:
                raise MembershipError("persisted vote skips a membership epoch")
            if vote.view.predecessor_digest != predecessor.digest:
                raise MembershipError("persisted vote predecessor changed")
            proposed = vote.view.member_map
            predecessor_members = predecessor.member_map
            if not set(proposed) < set(predecessor_members):
                raise MembershipError("persisted vote is not removal-only")
            if any(
                predecessor_members.get(robot_id) != boot_id
                for robot_id, boot_id in proposed.items()
            ):
                raise MembershipError("persisted vote boot identity changed")
            if vote.voter_id not in predecessor_members:
                raise MembershipError("persisted voter is outside predecessor view")
        self._history = validated
        self.current = validated[-1]

    def _install_if_quorum(self, view: MembershipView) -> MembershipView | None:
        supporters = {
            vote.voter_id
            for vote in self._votes.values()
            if vote.view.epoch == view.epoch and vote.view.digest == view.digest
        }
        if len(supporters) < self.current.quorum_size:
            return None
        self.current = view
        self._history.append(view)
        return view
