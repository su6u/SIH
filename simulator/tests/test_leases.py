import pytest

from swarmroute.leases import LeaseError, ZoneLeaseRegistry, ZoneState


def test_expired_pre_entry_grant_can_be_reissued_with_higher_epoch() -> None:
    registry = ZoneLeaseRegistry()
    first = registry.grant("Z", "R1", "P1", "M1", current_tick=0, ttl_ticks=2)

    assert registry.observe_silence("Z", current_tick=3) is None
    second = registry.grant("Z", "R2", "P2", "M1", current_tick=3, ttl_ticks=2)

    assert second.epoch == first.epoch + 1


def test_entered_zone_becomes_blocked_on_silence_not_free() -> None:
    registry = ZoneLeaseRegistry()
    lease = registry.grant("Z", "R1", "P1", "M1", current_tick=0, ttl_ticks=2)
    registry.enter("Z", "R1", lease.epoch, "P1", "M1", current_tick=1)

    observed = registry.observe_silence("Z", current_tick=3)

    assert observed is not None and observed.state is ZoneState.BLOCKED
    with pytest.raises(LeaseError, match="occupied or unverified"):
        registry.grant("Z", "R2", "P2", "M1", current_tick=3, ttl_ticks=2)


def test_release_requires_matching_fence_and_physical_clearance() -> None:
    registry = ZoneLeaseRegistry()
    lease = registry.grant("Z", "R1", "P1", "M1", current_tick=0, ttl_ticks=5)
    registry.enter("Z", "R1", lease.epoch, "P1", "M1", current_tick=1)

    with pytest.raises(LeaseError, match="epoch mismatch"):
        registry.release("Z", "R1", lease.epoch + 1, physically_clear=True)
    with pytest.raises(LeaseError, match="physical-clear"):
        registry.release("Z", "R1", lease.epoch, physically_clear=False)
    registry.release("Z", "R1", lease.epoch, physically_clear=True)
    assert registry.get("Z") is None
