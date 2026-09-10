from __future__ import annotations

from pathlib import Path

import pytest

from kinesis.durable import DurableStateError, JsonPeerStateStore
from kinesis.membership import MembershipError, MembershipState


MEMBERS = {"R1": "B1", "R2": "B2", "R3": "B3"}


def test_majority_installs_the_same_removal_only_view() -> None:
    states = {robot_id: MembershipState(MEMBERS) for robot_id in MEMBERS}
    votes = (
        states["R1"].create_vote("R1", {"R1", "R2"}),
        states["R2"].create_vote("R2", {"R1", "R2"}),
    )

    for state in states.values():
        installed = None
        for vote in votes:
            installed = state.merge(vote) or installed
        assert installed is not None
        assert state.current.epoch == 1
        assert state.current.member_map == {"R1": "B1", "R2": "B2"}


def test_minority_cannot_install_a_membership_change() -> None:
    state = MembershipState(MEMBERS)
    vote = state.create_vote("R1", {"R1", "R2"})

    assert state.merge(vote) is None
    assert state.current.epoch == 0


def test_one_vote_per_voter_per_epoch_rejects_equivocation() -> None:
    state = MembershipState(MEMBERS)
    state.merge(state.create_vote("R1", {"R1", "R2"}))
    conflicting = state.create_vote("R1", {"R1", "R3"})

    with pytest.raises(MembershipError, match="equivocated"):
        state.merge(conflicting)


def test_membership_addition_and_boot_identity_change_are_rejected() -> None:
    state = MembershipState(MEMBERS)

    with pytest.raises(MembershipError, match="remove"):
        state.create_vote("R1", set(MEMBERS))


def test_peer_state_store_is_atomic_and_strict(tmp_path: Path) -> None:
    path = tmp_path / "robot-R1.json"
    store = JsonPeerStateStore(path)
    state = {"schema_version": "1.0", "send_sequence": 7}

    store.save(state)

    assert store.load() == state
    assert not tuple(tmp_path.glob("*.tmp"))


def test_peer_state_store_rejects_corruption(tmp_path: Path) -> None:
    path = tmp_path / "robot-R1.json"
    path.write_text("not-json", encoding="utf-8")

    with pytest.raises(DurableStateError, match="UTF-8 JSON"):
        JsonPeerStateStore(path).load()


def test_restore_requires_the_quorum_proof_for_every_installed_view() -> None:
    source = MembershipState(MEMBERS)
    votes = (
        source.create_vote("R1", {"R1", "R2"}),
        source.create_vote("R2", {"R1", "R2"}),
    )
    for vote in votes:
        source.merge(vote)

    restored = MembershipState(MEMBERS)
    restored.restore(source.history, votes)
    assert restored.current == source.current

    with pytest.raises(MembershipError, match="quorum proof"):
        MembershipState(MEMBERS).restore(source.history, votes[:1])
