from dataclasses import replace

import pytest

from kinesis.network import DeterministicNetwork, NetworkConfig, NetworkEventKind
from kinesis.protocol import MessageEnvelope, MessageRejected, ReplayGuard


KEYS = {"R1": b"r1-test-key"}


def _message(sequence: int = 1) -> MessageEnvelope:
    return MessageEnvelope.create(
        kind="intent",
        sender_id="R1",
        boot_id="boot-a",
        sequence=sequence,
        sent_tick=4,
        ttl_ticks=3,
        map_version="M1",
        payload={"path": [1, 2, 3]},
        signing_key=KEYS["R1"],
    )


def test_replay_guard_rejects_duplicates_stale_messages_and_tampering() -> None:
    guard = ReplayGuard(
        schema_version="1.0", map_version="M1", authentication_keys=KEYS
    )
    message = _message()
    guard.accept(message, current_tick=5)

    with pytest.raises(MessageRejected, match="duplicate"):
        guard.accept(message, current_tick=5)
    with pytest.raises(MessageRejected, match="expired"):
        ReplayGuard(
            schema_version="1.0", map_version="M1", authentication_keys=KEYS
        ).accept(message, current_tick=8)
    with pytest.raises(MessageRejected, match="hash mismatch"):
        ReplayGuard(
            schema_version="1.0", map_version="M1", authentication_keys=KEYS
        ).accept(replace(message, payload={"path": [9]}), current_tick=5)


def test_reboot_has_a_separate_sequence_space() -> None:
    guard = ReplayGuard(
        schema_version="1.0", map_version="M1", authentication_keys=KEYS
    )
    guard.accept(_message(sequence=8), current_tick=4)
    rebooted = MessageEnvelope.create(
        kind="intent",
        sender_id="R1",
        boot_id="boot-b",
        sequence=0,
        sent_tick=4,
        ttl_ticks=3,
        map_version="M1",
        payload={"path": [1, 2, 3]},
        signing_key=KEYS["R1"],
    )
    guard.accept(rebooted, current_tick=4)


def test_message_authentication_rejects_the_wrong_sender_key() -> None:
    guard = ReplayGuard(
        schema_version="1.0",
        map_version="M1",
        authentication_keys={"R1": b"wrong-key"},
    )

    with pytest.raises(MessageRejected, match="authentication"):
        guard.accept(_message(), current_tick=4)


def test_network_is_seeded_and_partition_drops_messages() -> None:
    config = NetworkConfig(1, 3, loss_rate=0.0, duplicate_rate=0.0)
    first = DeterministicNetwork(config, seed=12)
    second = DeterministicNetwork(config, seed=12)
    for network in (first, second):
        network.register("R1")
        network.register("R2")
        network.send(_message(), ["R2"])
        network.advance(10)

    assert first.events == second.events
    assert first.receive("R2") == second.receive("R2")

    partitioned = DeterministicNetwork(config, seed=12)
    partitioned.register("R1")
    partitioned.register("R2")
    partitioned.isolate("R2")
    partitioned.send(_message(), ["R2"])
    assert partitioned.receive("R2") == ()
    assert partitioned.events[-1].kind is NetworkEventKind.PARTITION_DROPPED
