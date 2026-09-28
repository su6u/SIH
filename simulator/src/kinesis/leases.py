from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum


class ZoneState(StrEnum):
    FREE = "free"
    GRANTED = "granted"
    ENTERED = "entered"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class ZoneLease:
    zone_id: str
    holder_id: str
    epoch: int
    plan_id: str
    map_version: str
    granted_tick: int
    expires_tick: int
    state: ZoneState = ZoneState.GRANTED


class LeaseError(RuntimeError):
    pass


class ZoneLeaseRegistry:
    def __init__(self) -> None:
        self._leases: dict[str, ZoneLease] = {}
        self._epochs: dict[str, int] = {}

    def get(self, zone_id: str) -> ZoneLease | None:
        return self._leases.get(zone_id)

    def grant(
        self,
        zone_id: str,
        holder_id: str,
        plan_id: str,
        map_version: str,
        *,
        current_tick: int,
        ttl_ticks: int,
    ) -> ZoneLease:
        if ttl_ticks <= 0:
            raise ValueError("ttl_ticks must be positive")
        current = self._leases.get(zone_id)
        if current is not None:
            if current.state in (ZoneState.ENTERED, ZoneState.BLOCKED):
                raise LeaseError(f"zone {zone_id} is physically occupied or unverified")
            if current.expires_tick >= current_tick:
                raise LeaseError(f"zone {zone_id} already has a live grant")

        epoch = self._epochs.get(zone_id, 0) + 1
        lease = ZoneLease(
            zone_id=zone_id,
            holder_id=holder_id,
            epoch=epoch,
            plan_id=plan_id,
            map_version=map_version,
            granted_tick=current_tick,
            expires_tick=current_tick + ttl_ticks,
        )
        self._epochs[zone_id] = epoch
        self._leases[zone_id] = lease
        return lease

    def enter(
        self,
        zone_id: str,
        holder_id: str,
        epoch: int,
        plan_id: str,
        map_version: str,
        *,
        current_tick: int,
    ) -> ZoneLease:
        lease = self._matching(zone_id, holder_id, epoch, plan_id, map_version)
        if lease.state is not ZoneState.GRANTED or current_tick > lease.expires_tick:
            raise LeaseError("grant is not valid for entry")
        entered = replace(lease, state=ZoneState.ENTERED)
        self._leases[zone_id] = entered
        return entered

    def renew(
        self,
        zone_id: str,
        holder_id: str,
        epoch: int,
        *,
        current_tick: int,
        ttl_ticks: int,
    ) -> ZoneLease:
        if ttl_ticks <= 0:
            raise ValueError("ttl_ticks must be positive")
        lease = self._matching(
            zone_id, holder_id, epoch, lease_plan_id=None, map_version=None
        )
        if lease.state not in (ZoneState.GRANTED, ZoneState.ENTERED):
            raise LeaseError("blocked leases cannot be renewed")
        renewed = ZoneLease(
            zone_id=lease.zone_id,
            holder_id=lease.holder_id,
            epoch=lease.epoch,
            plan_id=lease.plan_id,
            map_version=lease.map_version,
            granted_tick=lease.granted_tick,
            expires_tick=current_tick + ttl_ticks,
            state=lease.state,
        )
        self._leases[zone_id] = renewed
        return renewed

    def observe_silence(self, zone_id: str, *, current_tick: int) -> ZoneLease | None:
        lease = self._leases.get(zone_id)
        if lease is None or current_tick <= lease.expires_tick:
            return lease
        if lease.state is ZoneState.GRANTED:
            del self._leases[zone_id]
            return None
        if lease.state is ZoneState.ENTERED:
            blocked = ZoneLease(
                zone_id=lease.zone_id,
                holder_id=lease.holder_id,
                epoch=lease.epoch,
                plan_id=lease.plan_id,
                map_version=lease.map_version,
                granted_tick=lease.granted_tick,
                expires_tick=lease.expires_tick,
                state=ZoneState.BLOCKED,
            )
            self._leases[zone_id] = blocked
            return blocked
        return lease

    def release(
        self,
        zone_id: str,
        holder_id: str,
        epoch: int,
        *,
        physically_clear: bool,
    ) -> None:
        lease = self._matching(
            zone_id, holder_id, epoch, lease_plan_id=None, map_version=None
        )
        if not physically_clear:
            raise LeaseError(
                "zone cannot be released without a physical-clear observation"
            )
        if lease.state not in (ZoneState.ENTERED, ZoneState.BLOCKED):
            raise LeaseError(
                "only an entered or blocked zone can be physically released"
            )
        del self._leases[zone_id]

    def _matching(
        self,
        zone_id: str,
        holder_id: str,
        epoch: int,
        lease_plan_id: str | None,
        map_version: str | None,
    ) -> ZoneLease:
        lease = self._leases.get(zone_id)
        if lease is None:
            raise LeaseError(f"zone {zone_id} has no lease")
        if lease.holder_id != holder_id or lease.epoch != epoch:
            raise LeaseError("holder or fencing epoch mismatch")
        if lease_plan_id is not None and lease.plan_id != lease_plan_id:
            raise LeaseError("plan mismatch")
        if map_version is not None and lease.map_version != map_version:
            raise LeaseError("map version mismatch")
        return lease
