from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass, replace
from enum import StrEnum

from .allocation import Bid, Bidder, is_settled_refusal
from .auction import AuctionStrategy, CentralAuction
from .domain import Cell, Plan, PlanStep, RobotMode, RobotState, Task
from .events import EventLog
from .experiment import TaskOutcome
from .graph import WarehouseMap
from .leases import LeaseError, ZoneLeaseRegistry, ZoneState
from .heuristics import DistanceOracle
from .operations import ConflictZone, Intervention, InterventionKind
from .physics import MotionConfig
from .planner import NoPathError, SpaceTimeAStar
from .reservations import ReservationTable
from .schedule import (
    RobotHorizon,
    RollingHorizonScheduler,
    Schedule,
    ScheduleWeights,
)


class CoordinationPolicy(StrEnum):
    SPACE_TIME = "space_time"
    STOP_AND_WAIT = "stop_and_wait"
    ROLLING_HORIZON = "rolling_horizon"


@dataclass(frozen=True, slots=True)
class SimulationConfig:
    max_ticks: int = 240
    planning_horizon_ticks: int = 180
    fairness_tolerance: float = 0.05
    motion: MotionConfig = MotionConfig()
    policy: CoordinationPolicy = CoordinationPolicy.SPACE_TIME
    clearance_cells: float = 0.0
    schedule_weights: ScheduleWeights = ScheduleWeights()
    # The look-ahead auction is usually already at a local optimum when open
    # orders do not outnumber free robots, so the improvement search is given a
    # budget that is worth its latency rather than the largest one that fits.
    schedule_improvement_steps: int = 500
    schedule_shortlist: int = 3
    schedule_seed: int = 0
    # How much slower than its free-space estimate a look-ahead hold must
    # still tolerate and meet the deadline. Applies to ROLLING_HORIZON only.
    schedule_hold_margin: float = 2.5

    def __post_init__(self) -> None:
        if self.max_ticks <= 0 or self.planning_horizon_ticks <= 0:
            raise ValueError("simulation horizons must be positive")
        if not 0 <= self.fairness_tolerance <= 1:
            raise ValueError("fairness_tolerance must be in [0, 1]")
        if not 0 <= self.clearance_cells <= 1:
            raise ValueError("clearance_cells must be in [0, 1]")
        if not isinstance(self.policy, CoordinationPolicy):
            raise ValueError("policy must be a CoordinationPolicy")
        if self.schedule_improvement_steps < 0:
            raise ValueError("schedule_improvement_steps must be non-negative")
        if self.schedule_shortlist <= 0:
            raise ValueError("schedule_shortlist must be positive")
        if self.schedule_hold_margin < 1.0:
            raise ValueError("schedule_hold_margin must be at least 1.0")

    @property
    def tick_seconds(self) -> float:
        return self.motion.tick_seconds


@dataclass(frozen=True, slots=True)
class RouteAssignment:
    task_id: str
    robot_id: str
    auction_epoch: int
    assigned_tick: int
    pickup_tick: int
    dropoff_tick: int
    finish_tick: int
    score: float
    plan: Plan


@dataclass(frozen=True, slots=True)
class FleetMetrics:
    task_count: int
    completed_tasks: int
    expired_tasks: int
    unfinished_tasks: int
    deadline_misses: int
    elapsed_ticks: int
    makespan_ticks: int
    total_distance_cells: int
    mean_flow_ticks: float
    utilization: float
    throughput_per_simulated_minute: float
    rejected_plan_conflicts: int
    executed_grid_vertex_conflicts: int
    executed_grid_reverse_edge_conflicts: int


@dataclass(frozen=True, slots=True)
class FleetRunResult:
    outcomes: tuple[TaskOutcome, ...]
    robots: tuple[RobotState, ...]
    assignments: tuple[RouteAssignment, ...]
    metrics: FleetMetrics
    events: EventLog


@dataclass(slots=True)
class _ActiveJob:
    task: Task
    bid: Bid
    pickup_emitted: bool = False
    dropoff_emitted: bool = False


class FleetSimulation:
    def __init__(
        self,
        warehouse_map: WarehouseMap,
        robots: tuple[RobotState, ...],
        *,
        config: SimulationConfig = SimulationConfig(),
        auction: AuctionStrategy | None = None,
        conflict_zones: tuple[ConflictZone, ...] = (),
    ) -> None:
        if not robots:
            raise ValueError("at least one robot is required")
        if len({robot.robot_id for robot in robots}) != len(robots):
            raise ValueError("robot identifiers must be unique")
        if len({robot.cell for robot in robots}) != len(robots):
            raise ValueError("robots must start in unique cells")
        for robot in robots:
            if not warehouse_map.traversable(robot.cell):
                raise ValueError(f"robot {robot.robot_id} starts in a blocked cell")
        self._map = warehouse_map
        self._initial_robots = tuple(sorted(robots, key=lambda item: item.robot_id))
        self._config = config
        self._auction = auction if auction is not None else CentralAuction()
        self._conflict_zones = conflict_zones
        zone_cells: set[Cell] = set()
        for zone in conflict_zones:
            if zone_cells & zone.cells:
                raise ValueError("conflict zones must not overlap")
            if any(not warehouse_map.traversable(cell) for cell in zone.cells):
                raise ValueError(f"conflict zone {zone.zone_id} contains an invalid cell")
            zone_cells.update(zone.cells)

    def run(
        self,
        tasks: tuple[Task, ...],
        interventions: tuple[Intervention, ...] = (),
    ) -> FleetRunResult:
        self._validate_tasks(tasks)
        if len({item.intervention_id for item in interventions}) != len(interventions):
            raise ValueError("intervention identifiers must be unique")
        reservations = ReservationTable(clearance_cells=self._config.clearance_cells)
        warehouse_map = self._map
        distances = DistanceOracle(warehouse_map)
        planner = SpaceTimeAStar(
            warehouse_map,
            reservations,
            move_ticks=self._config.motion.move_ticks,
            distances=distances,
        )
        bidder = Bidder(
            planner,
            reservations,
            motion=self._config.motion,
            planning_horizon_ticks=self._config.planning_horizon_ticks,
            max_plan_tick=self._config.max_ticks,
        )
        scheduler = self._build_scheduler(distances)
        robots = {robot.robot_id: robot for robot in self._initial_robots}
        active: dict[str, _ActiveJob] = {}
        pending: dict[str, Task] = {}
        assignments: list[RouteAssignment] = []
        outcomes: dict[str, TaskOutcome] = {}
        events = EventLog()
        disabled: set[str] = set()
        charging: dict[str, tuple[int | None, float]] = {}
        leases = ZoneLeaseRegistry()
        robot_leases: dict[str, tuple[str, int]] = {}
        blocked_lease_events: set[str] = set()
        zones_by_cell = {
            cell: zone for zone in self._conflict_zones for cell in zone.cells
        }
        interventions_by_tick: dict[int, list[Intervention]] = {}
        for item in sorted(interventions, key=lambda value: (value.tick, value.intervention_id)):
            if item.tick > self._config.max_ticks:
                continue
            interventions_by_tick.setdefault(item.tick, []).append(item)
        ordered_tasks = tuple(
            sorted(tasks, key=lambda item: (item.release_tick, item.task_id))
        )
        releases: dict[int, list[Task]] = {}
        for task in ordered_tasks:
            releases.setdefault(task.release_tick, []).append(task)

        for robot in self._initial_robots:
            conflicts = reservations.commit(
                self._hold_plan(robot.robot_id, robot.cell, 0)
            )
            if conflicts:
                raise AssertionError(
                    f"initial parking reservation conflict: {conflicts}"
                )

        total_distance = 0
        busy_robot_ticks = 0
        epoch = 0
        elapsed_tick = 0
        executed_vertex_conflicts = 0
        executed_reverse_edge_conflicts = 0
        rejected_plan_conflicts = 0
        schedule_memo: tuple[object, Schedule] | None = None
        settled: set[tuple[str, str]] = set()
        parking_moves: dict[str, Plan] = {}
        endpoint_cells = {task.pickup for task in tasks} | {
            task.dropoff for task in tasks
        }

        def rebuild_bidder() -> tuple[Bidder, RollingHorizonScheduler]:
            oracle = DistanceOracle(warehouse_map)
            return (
                Bidder(
                    SpaceTimeAStar(
                        warehouse_map,
                        reservations,
                        move_ticks=self._config.motion.move_ticks,
                        distances=oracle,
                    ),
                    reservations,
                    motion=self._config.motion,
                    planning_horizon_ticks=self._config.planning_horizon_ticks,
                    max_plan_tick=self._config.max_ticks,
                ),
                self._build_scheduler(oracle),
            )

        def hold(robot_id: str, tick: int) -> None:
            settled.clear()
            conflicts = reservations.commit(
                self._hold_plan(robot_id, robots[robot_id].cell, tick)
            )
            if conflicts:
                raise AssertionError(f"parking reservation conflict: {conflicts}")

        def requeue_active(
            robot_id: str, tick: int, reason: str, *, handoff_payload: bool = False
        ) -> None:
            job = active.pop(robot_id, None)
            settled.clear()
            parking_moves.pop(robot_id, None)
            reservations.release(robot_id, from_tick=tick)
            if job is None:
                return
            task = job.task
            if job.pickup_emitted:
                occupied = {robot.cell for key, robot in robots.items() if key != robot_id}
                recovery_cell = robots[robot_id].cell
                if handoff_payload:
                    recovery_cell = next(
                        (
                            cell
                            for cell in warehouse_map.neighbors(robots[robot_id].cell)
                            if cell not in occupied
                        ),
                        robots[robot_id].cell,
                    )
                task = replace(
                    task,
                    pickup=recovery_cell,
                    release_tick=tick,
                    service_ticks=0,
                )
                events.append(
                    tick=tick,
                    kind="payload_recovery_requested",
                    entity_id=task.task_id,
                    data={"failed_robot_id": robot_id, "cell": asdict(recovery_cell)},
                )
            pending[task.task_id] = task
            robots[robot_id] = replace(
                robots[robot_id], available_tick=tick, mode=RobotMode.RECONCILING
            )
            events.append(
                tick=tick,
                kind="task_requeued",
                entity_id=task.task_id,
                data={"robot_id": robot_id, "reason": reason},
            )

        def requeue_with_dependencies(
            robot_ids: tuple[str, ...],
            tick: int,
            reason: str,
            *,
            do_not_hold: frozenset[str] = frozenset(),
            handoff_payload_from: frozenset[str] = frozenset(),
        ) -> tuple[str, ...]:
            queue = list(robot_ids)
            requeued: list[str] = []
            stopped_cells: set[Cell] = set()
            while queue:
                robot_id = queue.pop(0)
                if robot_id in requeued:
                    continue
                requeue_active(
                    robot_id,
                    tick,
                    reason,
                    handoff_payload=robot_id in handoff_payload_from,
                )
                requeued.append(robot_id)
                stopped_cells.add(robots[robot_id].cell)
                for other_id, job in active.items():
                    if other_id in requeued or other_id in queue:
                        continue
                    if any(
                        step.tick >= tick and step.cell in stopped_cells
                        for step in self._execution_plan(job).steps
                    ):
                        queue.append(other_id)
            for robot_id in requeued:
                if robot_id not in do_not_hold:
                    hold(robot_id, tick)
            return tuple(requeued)

        for tick in range(self._config.max_ticks + 1):
            elapsed_tick = tick
            for robot_id, (recover_tick, recovered_soc) in tuple(charging.items()):
                if recover_tick is None or tick < recover_tick:
                    continue
                charging.pop(robot_id)
                robots[robot_id] = replace(
                    robots[robot_id], battery_soc=recovered_soc, mode=RobotMode.IDLE
                )
                events.append(
                    tick=tick,
                    kind="robot_charge_completed",
                    entity_id=robot_id,
                    data={"battery_soc": recovered_soc},
                )

            map_changed = False
            for intervention in interventions_by_tick.get(tick, []):
                events.append(
                    tick=tick,
                    kind="intervention_applied",
                    entity_id=intervention.intervention_id,
                    data={"kind": intervention.kind.value},
                )
                if intervention.kind is InterventionKind.BLOCK_CELLS:
                    occupied = {
                        robot.cell for robot in robots.values() if robot.cell in intervention.cells
                    }
                    if occupied:
                        raise ValueError(
                            f"cannot block physically occupied cells at tick {tick}: {occupied}"
                        )
                    affected = tuple(
                        robot_id
                        for robot_id, job in active.items()
                        if any(
                            step.tick >= tick and step.cell in intervention.cells
                            for step in self._execution_plan(job).steps
                        )
                    )
                    requeue_with_dependencies(
                        affected, tick, "route invalidated by blocked cells"
                    )
                    warehouse_map = WarehouseMap(
                        warehouse_map.width,
                        warehouse_map.height,
                        warehouse_map.blocked | frozenset(intervention.cells),
                        f"{warehouse_map.version}+{intervention.intervention_id}",
                    )
                    map_changed = True
                    events.append(
                        tick=tick,
                        kind="cells_blocked",
                        entity_id=intervention.intervention_id,
                        data={"cells": [asdict(cell) for cell in intervention.cells]},
                    )
                elif intervention.kind is InterventionKind.ROBOT_FAILURE:
                    robot_id = intervention.robot_id
                    if robot_id is None:
                        raise AssertionError("validated robot failure has no robot_id")
                    if robot_id in disabled:
                        continue
                    failed_cell = robots[robot_id].cell
                    disabled.add(robot_id)
                    charging.pop(robot_id, None)
                    requeue_with_dependencies(
                        (robot_id,),
                        tick,
                        "robot entered safe-stop",
                        do_not_hold=frozenset({robot_id}),
                        handoff_payload_from=frozenset({robot_id}),
                    )
                    robots[robot_id] = replace(
                        robots[robot_id], available_tick=self._config.max_ticks, mode=RobotMode.SAFE_STOP
                    )
                    affected = tuple(
                        other_id
                        for other_id, job in active.items()
                        if any(
                            step.tick >= tick and step.cell == failed_cell
                            for step in self._execution_plan(job).steps
                        )
                    )
                    requeue_with_dependencies(
                        affected, tick, "route blocked by failed robot"
                    )
                    warehouse_map = WarehouseMap(
                        warehouse_map.width,
                        warehouse_map.height,
                        warehouse_map.blocked | frozenset({failed_cell}),
                        f"{warehouse_map.version}+{intervention.intervention_id}",
                    )
                    map_changed = True
                    events.append(
                        tick=tick,
                        kind="robot_safe_stopped",
                        entity_id=robot_id,
                        data={"cell": asdict(failed_cell)},
                    )
                elif intervention.kind is InterventionKind.BATTERY_LOW:
                    robot_id = intervention.robot_id
                    if robot_id is None or intervention.battery_soc is None:
                        raise AssertionError("validated battery intervention is incomplete")
                    requeue_with_dependencies(
                        (robot_id,), tick, "battery reserve protection"
                    )
                    charging[robot_id] = (
                        intervention.recover_tick,
                        intervention.recovered_soc,
                    )
                    robots[robot_id] = replace(
                        robots[robot_id],
                        battery_soc=intervention.battery_soc,
                        available_tick=intervention.recover_tick or self._config.max_ticks,
                        mode=RobotMode.RECONCILING,
                    )
                    events.append(
                        tick=tick,
                        kind="robot_charge_requested",
                        entity_id=robot_id,
                        data={
                            "battery_soc": intervention.battery_soc,
                            "recover_tick": intervention.recover_tick,
                        },
                    )
            if map_changed:
                bidder, scheduler = rebuild_bidder()
                schedule_memo = None
                settled.clear()

            for task in releases.get(tick, []):
                pending[task.task_id] = task
                events.append(tick=tick, kind="task_announced", entity_id=task.task_id)

            positions_before_move = {
                robot_id: robot.cell for robot_id, robot in robots.items()
            }

            desired_zones: dict[str, ConflictZone | None] = {}
            for robot_id, job in active.items():
                step = self._step_at(self._execution_plan(job), tick)
                desired_zones[robot_id] = zones_by_cell.get(step.cell) if step else None
            for robot_id, (zone_id, epoch_value) in tuple(robot_leases.items()):
                desired = desired_zones.get(robot_id)
                if desired is not None and desired.zone_id == zone_id:
                    leases.renew(
                        zone_id,
                        robot_id,
                        epoch_value,
                        current_tick=tick,
                        ttl_ticks=desired.lease_ttl_ticks,
                    )
                    continue
                if robot_id not in disabled:
                    leases.release(zone_id, robot_id, epoch_value, physically_clear=True)
                    events.append(
                        tick=tick,
                        kind="zone_lease_released",
                        entity_id=zone_id,
                        data={"robot_id": robot_id, "epoch": epoch_value},
                    )
                    robot_leases.pop(robot_id)
            for robot_id, desired in sorted(desired_zones.items()):
                if desired is None or robot_id in robot_leases:
                    continue
                job = active[robot_id]
                plan_id = f"{job.task.task_id}:{job.bid.auction_epoch}"
                lease = leases.grant(
                    desired.zone_id,
                    robot_id,
                    plan_id,
                    warehouse_map.version,
                    current_tick=tick,
                    ttl_ticks=desired.lease_ttl_ticks,
                )
                lease = leases.enter(
                    desired.zone_id,
                    robot_id,
                    lease.epoch,
                    plan_id,
                    warehouse_map.version,
                    current_tick=tick,
                )
                robot_leases[robot_id] = (lease.zone_id, lease.epoch)
                events.append(
                    tick=tick,
                    kind="zone_lease_entered",
                    entity_id=lease.zone_id,
                    data={"robot_id": robot_id, "epoch": lease.epoch, "plan_id": plan_id},
                )

            for zone in self._conflict_zones:
                observed = leases.observe_silence(zone.zone_id, current_tick=tick)
                if (
                    observed is not None
                    and observed.state is ZoneState.BLOCKED
                    and zone.zone_id not in blocked_lease_events
                ):
                    blocked_lease_events.add(zone.zone_id)
                    events.append(
                        tick=tick,
                        kind="zone_blocked_on_silence",
                        entity_id=zone.zone_id,
                        data={"robot_id": observed.holder_id, "epoch": observed.epoch},
                    )
            completed_robot_ids: list[str] = []
            for robot_id in sorted(active):
                busy_robot_ticks += 1
                job = active[robot_id]
                plan = self._execution_plan(job)
                step = self._step_at(plan, tick)
                if step is not None:
                    current = robots[robot_id]
                    if current.cell != step.cell:
                        total_distance += 1
                        events.append(
                            tick=tick,
                            kind="robot_moved",
                            entity_id=robot_id,
                            data={
                                "from": asdict(current.cell),
                                "to": asdict(step.cell),
                                "task_id": job.task.task_id,
                            },
                        )
                    robots[robot_id] = replace(
                        current, cell=step.cell, mode=RobotMode.MOVING
                    )
                self._emit_milestones(job, robot_id, tick, events)
                if tick == plan.end.tick:
                    if job.bid.expected_soc is None:
                        raise AssertionError("feasible active bid has no expected_soc")
                    current = robots[robot_id]
                    robots[robot_id] = replace(
                        current,
                        battery_soc=job.bid.expected_soc,
                        available_tick=tick,
                        completed_tasks=current.completed_tasks + 1,
                        mode=RobotMode.IDLE,
                    )
                    outcomes[job.task.task_id] = TaskOutcome(
                        job.task.task_id,
                        "completed",
                        robot_id,
                        job.task.release_tick,
                        tick,
                    )
                    events.append(
                        tick=tick,
                        kind="task_completed",
                        entity_id=job.task.task_id,
                        data={
                            "robot_id": robot_id,
                            "battery_soc": job.bid.expected_soc,
                        },
                    )
                    completed_robot_ids.append(robot_id)

            for robot_id in sorted(parking_moves):
                plan = parking_moves[robot_id]
                step = self._step_at(plan, tick)
                if step is not None:
                    current = robots[robot_id]
                    if current.cell != step.cell:
                        total_distance += 1
                        events.append(
                            tick=tick,
                            kind="robot_moved",
                            entity_id=robot_id,
                            data={
                                "from": asdict(current.cell),
                                "to": asdict(step.cell),
                                "task_id": None,
                            },
                        )
                    robots[robot_id] = replace(current, cell=step.cell)
                if step is None or tick >= plan.end.tick:
                    parking_moves.pop(robot_id, None)

            vertex_conflicts, reverse_edge_conflicts = self._executed_conflicts(
                positions_before_move,
                robots,
                tick,
            )
            executed_vertex_conflicts += vertex_conflicts
            executed_reverse_edge_conflicts += reverse_edge_conflicts
            for robot_id in completed_robot_ids:
                active.pop(robot_id)

            for task_id, task in tuple(sorted(pending.items())):
                if tick > task.deadline_tick:
                    pending.pop(task_id)
                    outcomes[task_id] = TaskOutcome(
                        task_id,
                        "expired",
                        None,
                        task.release_tick,
                        None,
                        "deadline elapsed before a feasible assignment",
                    )
                    events.append(
                        tick=tick,
                        kind="task_expired",
                        entity_id=task_id,
                        data={"deadline_tick": task.deadline_tick},
                    )

            idle_ids = [
                robot_id
                for robot_id in sorted(robots)
                if robot_id not in active
                and robot_id not in disabled
                and robot_id not in charging
            ]
            if self._config.policy is CoordinationPolicy.STOP_AND_WAIT and active:
                idle_ids = []

            def collect_bids(
                task: Task, robot_ids: tuple[str, ...], auction_epoch: int
            ) -> tuple[list[Bid], list[Bid]]:
                nonlocal rejected_plan_conflicts
                collected: list[Bid] = []
                schedulable: list[Bid] = []
                for robot_id in robot_ids:
                    if (robot_id, task.task_id) in settled:
                        continue
                    bid = bidder.bid(
                        robots[robot_id],
                        task,
                        current_tick=tick,
                        auction_epoch=auction_epoch,
                    )
                    collected.append(bid)
                    if not bid.feasible:
                        if is_settled_refusal(bid):
                            settled.add((robot_id, task.task_id))
                        continue
                    conflicts = reservations.conflicts_for(
                        self._reservation_plan(self._execution_plan_from_bid(bid))
                    )
                    if not conflicts:
                        schedulable.append(bid)
                        continue
                    rejected_plan_conflicts += 1
                    first_conflict = conflicts[0]
                    events.append(
                        tick=tick,
                        kind="plan_conflict_rejected",
                        entity_id=task.task_id,
                        data={
                            "robot_id": bid.robot_id,
                            "owner_id": first_conflict.owner_id,
                            "conflict_kind": first_conflict.kind.value,
                            "conflict_tick": first_conflict.tick,
                            "cell": (
                                asdict(first_conflict.cell)
                                if first_conflict.cell is not None
                                else None
                            ),
                            "edge": (
                                [asdict(cell) for cell in first_conflict.edge]
                                if first_conflict.edge is not None
                                else None
                            ),
                        },
                    )
                return collected, schedulable

            if self._config.policy is CoordinationPolicy.ROLLING_HORIZON:
                auction_plan, schedule_memo = self._rolling_horizon_plan(
                    scheduler,
                    robots=robots,
                    active=active,
                    disabled=disabled,
                    charging=charging,
                    pending=pending,
                    idle_ids=tuple(idle_ids),
                    tick=tick,
                    memo=schedule_memo,
                )
            else:
                auction_plan = tuple(
                    (task, ())
                    for task in sorted(
                        pending.values(),
                        key=lambda item: (
                            item.deadline_tick,
                            item.release_tick,
                            item.task_id,
                        ),
                    )
                )
            for task, preferred in auction_plan:
                if not idle_ids:
                    break
                if task.task_id not in pending:
                    continue
                epoch += 1
                shortlist = tuple(
                    robot_id for robot_id in preferred if robot_id in idle_ids
                )
                # The schedule's own choice is auctioned first and alone, so a
                # look-ahead award is not undone by a rival whose myopic score
                # happens to be lower. Wider tiers are only a fallback for when
                # that robot turns out to be infeasible or in conflict.
                tiers: list[tuple[str, ...]] = []
                if shortlist:
                    tiers.append(shortlist[:1])
                    if len(shortlist) > 1:
                        tiers.append(shortlist[1:])
                tiers.append(
                    tuple(
                        robot_id for robot_id in idle_ids if robot_id not in shortlist
                    )
                )
                bids: list[Bid] = []
                schedulable_bids: list[Bid] = []
                for tier in tiers:
                    if not tier:
                        continue
                    tier_bids, tier_schedulable = collect_bids(task, tier, epoch)
                    bids.extend(tier_bids)
                    schedulable_bids.extend(tier_schedulable)
                    if schedulable_bids:
                        break
                for bid in bids:
                    events.append(
                        tick=tick,
                        kind="task_bid",
                        entity_id=task.task_id,
                        data={
                            "robot_id": bid.robot_id,
                            "auction_epoch": epoch,
                            "feasible": bid.feasible,
                            "score": bid.score,
                            "expected_finish_tick": bid.expected_finish_tick,
                            "reason": bid.reason,
                        },
                    )
                try:
                    winner = self._auction.select(
                        tuple(schedulable_bids),
                        fairness_tolerance=self._config.fairness_tolerance,
                    )
                except ValueError:
                    continue
                plan = self._execution_plan_from_bid(winner)
                if winner.pickup_plan is None or winner.dropoff_plan is None:
                    raise AssertionError("feasible bid has incomplete route segments")

                settled.clear()
                parking_moves.pop(winner.robot_id, None)
                reservations.release(winner.robot_id, from_tick=tick + 1)
                conflicts = reservations.commit(self._reservation_plan(plan))
                if conflicts:
                    raise AssertionError(
                        f"selected plan conflicted during commit: {conflicts}"
                    )
                current = robots[winner.robot_id]
                robots[winner.robot_id] = replace(
                    current,
                    available_tick=plan.end.tick,
                    mode=RobotMode.COMMITTED,
                )
                job = _ActiveJob(task, winner)
                active[winner.robot_id] = job
                pending.pop(task.task_id)
                idle_ids.remove(winner.robot_id)
                assignment = RouteAssignment(
                    task_id=task.task_id,
                    robot_id=winner.robot_id,
                    auction_epoch=epoch,
                    assigned_tick=tick,
                    pickup_tick=winner.pickup_plan.end.tick,
                    dropoff_tick=winner.dropoff_plan.end.tick,
                    finish_tick=plan.end.tick,
                    score=winner.score,
                    plan=plan,
                )
                assignments.append(assignment)
                events.append(
                    tick=tick,
                    kind="task_awarded",
                    entity_id=task.task_id,
                    data={
                        "robot_id": winner.robot_id,
                        "auction_epoch": epoch,
                        "pickup_tick": assignment.pickup_tick,
                        "finish_tick": assignment.finish_tick,
                        "score": winner.score,
                    },
                )
                self._emit_milestones(job, winner.robot_id, tick, events)
                if self._config.policy is CoordinationPolicy.STOP_AND_WAIT:
                    break

            open_endpoints = {
                task.pickup for task in ordered_tasks if task.task_id not in outcomes
            } | {
                task.dropoff for task in ordered_tasks if task.task_id not in outcomes
            }
            if open_endpoints:
                for robot_id in sorted(robots):
                    if (
                        robot_id in active
                        or robot_id in disabled
                        or robot_id in charging
                        or robot_id in parking_moves
                    ):
                        continue
                    if robots[robot_id].cell not in open_endpoints:
                        continue
                    moved = self._evacuate_endpoint(
                        robot_id,
                        robots,
                        reservations,
                        planner,
                        warehouse_map,
                        open_endpoints,
                        tick,
                    )
                    if moved is None:
                        continue
                    settled.clear()
                    parking_moves[robot_id] = moved
                    events.append(
                        tick=tick,
                        kind="endpoint_vacated",
                        entity_id=robot_id,
                        data={
                            "from": asdict(robots[robot_id].cell),
                            "to": asdict(moved.end.cell),
                        },
                    )

            if len(outcomes) == len(tasks) and not active and not charging:
                break

        for task in ordered_tasks:
            if task.task_id in outcomes:
                continue
            status = (
                "unfinished"
                if task.task_id in pending or task.release_tick <= elapsed_tick
                else "unreleased"
            )
            outcomes[task.task_id] = TaskOutcome(
                task.task_id,
                status,
                next(
                    (
                        assignment.robot_id
                        for assignment in assignments
                        if assignment.task_id == task.task_id
                    ),
                    None,
                ),
                task.release_tick,
                None,
                "simulation horizon elapsed",
            )

        ordered_outcomes = tuple(outcomes[task.task_id] for task in ordered_tasks)
        completed = tuple(
            item for item in ordered_outcomes if item.status == "completed"
        )
        flows = tuple(
            item.finish_tick - item.release_tick
            for item in completed
            if item.finish_tick is not None
        )
        elapsed_seconds = max(1, elapsed_tick) * self._config.tick_seconds
        metrics = FleetMetrics(
            task_count=len(tasks),
            completed_tasks=len(completed),
            expired_tasks=sum(item.status == "expired" for item in ordered_outcomes),
            unfinished_tasks=sum(
                item.status in {"unfinished", "unreleased"} for item in ordered_outcomes
            ),
            deadline_misses=sum(
                item.finish_tick is not None
                and item.finish_tick
                > next(
                    task.deadline_tick for task in tasks if task.task_id == item.task_id
                )
                for item in completed
            ),
            elapsed_ticks=elapsed_tick,
            makespan_ticks=max(
                (item.finish_tick or 0 for item in completed), default=0
            ),
            total_distance_cells=total_distance,
            mean_flow_ticks=sum(flows) / len(flows) if flows else 0.0,
            utilization=busy_robot_ticks / max(1, len(robots) * (elapsed_tick + 1)),
            throughput_per_simulated_minute=len(completed) * 60.0 / elapsed_seconds,
            rejected_plan_conflicts=rejected_plan_conflicts,
            executed_grid_vertex_conflicts=executed_vertex_conflicts,
            executed_grid_reverse_edge_conflicts=executed_reverse_edge_conflicts,
        )
        return FleetRunResult(
            outcomes=ordered_outcomes,
            robots=tuple(sorted(robots.values(), key=lambda item: item.robot_id)),
            assignments=tuple(assignments),
            metrics=metrics,
            events=events,
        )

    def _evacuate_endpoint(
        self,
        robot_id: str,
        robots: dict[str, RobotState],
        reservations: ReservationTable,
        planner: SpaceTimeAStar,
        warehouse_map: WarehouseMap,
        open_endpoints: set[Cell],
        tick: int,
    ) -> Plan | None:
        """Step an idle robot off a pickup or drop-off cell it is squatting on.

        A parked robot holds its cell for the rest of the run, and a workload
        can reuse the same handful of endpoints many times over — the 57 x 41
        fulfilment scenario has 32 orders sharing 12 endpoint cells. Once every
        robot rests on one, every remaining order has an unreachable pickup or
        drop-off and the fleet deadlocks with robots idle. Moving to the
        nearest cell no open order needs costs a few ticks and keeps the
        instance solvable; this is the well-formed-infrastructure condition
        that decoupled multi-agent pickup and delivery planners rely on.
        """
        origin = robots[robot_id].cell
        target = self._nearest_free_parking(warehouse_map, origin, open_endpoints)
        if target is None:
            return None
        reservations.release(robot_id, from_tick=tick + 1)
        try:
            route = planner.plan(
                robot_id,
                origin,
                target,
                start_tick=tick,
                max_tick=min(
                    tick + self._config.planning_horizon_ticks, self._config.max_ticks
                ),
            )
        except (NoPathError, ValueError):
            route = None
        if route is not None and not reservations.commit(self._reservation_plan(route)):
            return route
        # Nothing better was available; put the original hold back so the cell
        # this robot is physically standing on stays reserved.
        conflicts = reservations.commit(self._hold_plan(robot_id, origin, tick))
        if conflicts:
            raise AssertionError(f"parking reservation conflict: {conflicts}")
        return None

    @staticmethod
    def _nearest_free_parking(
        warehouse_map: WarehouseMap, origin: Cell, open_endpoints: set[Cell]
    ) -> Cell | None:
        """Closest traversable cell that no open order needs."""
        seen = {origin}
        frontier = deque([origin])
        while frontier:
            cell = frontier.popleft()
            if cell != origin and cell not in open_endpoints:
                return cell
            for neighbour in warehouse_map.neighbors(cell):
                if neighbour not in seen:
                    seen.add(neighbour)
                    frontier.append(neighbour)
        return None

    def _build_scheduler(self, distances: DistanceOracle) -> RollingHorizonScheduler:
        return RollingHorizonScheduler(
            distances,
            move_ticks=self._config.motion.move_ticks,
            weights=self._config.schedule_weights,
            improvement_steps=self._config.schedule_improvement_steps,
            seed=self._config.schedule_seed,
        )

    def _rolling_horizon_plan(
        self,
        scheduler: RollingHorizonScheduler,
        *,
        robots: dict[str, RobotState],
        active: dict[str, _ActiveJob],
        disabled: set[str],
        charging: dict[str, tuple[int | None, float]],
        pending: dict[str, Task],
        idle_ids: tuple[str, ...],
        tick: int,
        memo: tuple[object, Schedule] | None,
    ) -> tuple[tuple[tuple[Task, tuple[str, ...]], ...], tuple[object, Schedule] | None]:
        """Turn a look-ahead schedule into an ordered list of auctions to run.

        Every robot that is still in service is projected forward to the pose
        and tick where its committed work ends, so a robot about to finish can
        out-bid an idle robot that is far away. Only the head of an idle
        robot's sequence is auctioned; the rest is advice that gets recomputed
        once the fleet state moves on. Work the schedule could not place, or
        placed past its deadline, is appended so nothing starves.
        """
        if not idle_ids or not pending:
            return (), memo

        horizons: list[RobotHorizon] = []
        for robot_id in sorted(robots):
            if robot_id in disabled:
                continue
            robot = robots[robot_id]
            job = active.get(robot_id)
            if job is not None:
                plan = self._execution_plan(job)
                cell, ready = plan.end.cell, plan.end.tick
            else:
                cell, ready = robot.cell, max(tick, robot.available_tick)
            if robot_id in charging:
                recover = charging[robot_id][0]
                ready = max(
                    ready, self._config.max_ticks if recover is None else recover
                )
            horizons.append(
                RobotHorizon(robot_id, cell, ready, robot.payload_capacity_kg)
            )
        if not horizons:
            return (), memo

        signature = (
            tuple(sorted(pending)),
            idle_ids,
            tuple((item.robot_id, item.cell, item.ready_tick) for item in horizons),
        )
        if memo is not None and memo[0] == signature:
            solution = memo[1]
        else:
            solution = scheduler.solve(horizons, pending.values(), current_tick=tick)
            memo = (signature, solution)
        sequences = solution.sequences

        by_id = {item.robot_id: item for item in horizons}
        claimed: dict[str, str] = {}
        for robot_id in idle_ids:
            for task_id in sequences.get(robot_id, ()):
                task = pending.get(task_id)
                if task is None or task_id in claimed:
                    continue
                if task.release_tick > tick:
                    continue
                claimed[task_id] = robot_id
                break

        limit = self._config.schedule_shortlist

        def rank_idle(task: Task, leader: str | None) -> tuple[str, ...]:
            """The leader, then the next best free robots by estimated finish.

            Bidding is two space-time searches per robot, so an auction that
            asks every robot about every open order is the dominant cost on a
            large map. Ranking on cached distances first keeps that bounded.
            """
            ranked: list[tuple[int, str]] = []
            for other in idle_ids:
                if other == leader:
                    continue
                finish = scheduler.finish_tick(by_id[other], task, current_tick=tick)
                if finish is not None:
                    ranked.append((finish, other))
            ranked.sort()
            head = () if leader is None else (leader,)
            keep = limit - len(head)
            return head + tuple(other for _, other in ranked[: max(0, keep)])

        entries: list[tuple[Task, tuple[str, ...]]] = []
        for task_id, robot_id in claimed.items():
            entries.append((pending[task_id], rank_idle(pending[task_id], robot_id)))
        # A task the schedule parked on a robot that is still busy is normally
        # left alone: holding it for the robot that will finish nearest to its
        # pickup is the whole point of looking ahead. The hold ends when the
        # schedule could not place the task at all, when it placed it past the
        # deadline, or — the case that matters on a congested map — when a
        # robot is standing still with nothing claimed. The projection is
        # built from free-space distances, so under heavy traffic it keeps
        # promising a release that slides another tick out; letting a robot
        # idle on the strength of that promise loses more orders than the
        # shorter route ever saves.
        margin = self._config.schedule_hold_margin

        def worth_holding(task: Task) -> bool:
            entry = solution.entries.get(task.task_id)
            if entry is None:
                return False
            # The schedule prices routes in free space, so its finish tick is
            # optimistic by however much traffic the fleet is actually in. A
            # hold is only worth taking if the order still lands in time after
            # the same congestion allowance the bidder is willing to accept.
            projected = entry.start_tick + margin * (entry.finish_tick - entry.start_tick)
            return projected <= task.deadline_tick

        leftovers = sorted(
            (
                task
                for task_id, task in pending.items()
                if task_id not in claimed
                and task.release_tick <= tick
                and not worth_holding(task)
            ),
            key=lambda item: (item.deadline_tick, item.release_tick, item.task_id),
        )
        entries.extend((task, rank_idle(task, None)) for task in leftovers)
        entries.sort(
            key=lambda item: (
                item[0].deadline_tick,
                item[0].release_tick,
                item[0].task_id,
            )
        )
        return tuple(entries), memo

    def _hold_plan(self, robot_id: str, cell: Cell, start_tick: int) -> Plan:
        return Plan.from_steps(
            robot_id,
            (
                PlanStep(cell, tick)
                for tick in range(start_tick, self._config.max_ticks + 1)
            ),
        )

    def _reservation_plan(self, execution: Plan) -> Plan:
        steps = list(execution.steps)
        steps.extend(
            PlanStep(execution.end.cell, tick)
            for tick in range(execution.end.tick + 1, self._config.max_ticks + 1)
        )
        return Plan.from_steps(execution.robot_id, steps)

    @staticmethod
    def _step_at(plan: Plan, tick: int) -> PlanStep | None:
        index = tick - plan.start.tick
        return plan.steps[index] if 0 <= index < len(plan.steps) else None

    @staticmethod
    def _execution_plan(job: _ActiveJob) -> Plan:
        return FleetSimulation._execution_plan_from_bid(job.bid)

    @staticmethod
    def _execution_plan_from_bid(bid: Bid) -> Plan:
        if (
            bid.execution_plan is None
            or bid.expected_finish_tick is None
            or bid.expected_soc is None
        ):
            raise AssertionError("feasible bid is missing its execution plan")
        return bid.execution_plan

    @staticmethod
    def _emit_milestones(
        job: _ActiveJob, robot_id: str, tick: int, events: EventLog
    ) -> None:
        if job.bid.pickup_plan is None or job.bid.dropoff_plan is None:
            raise AssertionError("active job is missing route segments")
        if not job.pickup_emitted and tick >= job.bid.pickup_plan.end.tick:
            job.pickup_emitted = True
            events.append(
                tick=tick,
                kind="task_picked",
                entity_id=job.task.task_id,
                data={"robot_id": robot_id},
            )
        if not job.dropoff_emitted and tick >= job.bid.dropoff_plan.end.tick:
            job.dropoff_emitted = True
            events.append(
                tick=tick,
                kind="task_dropped",
                entity_id=job.task.task_id,
                data={"robot_id": robot_id},
            )

    @staticmethod
    def _executed_conflicts(
        before: dict[str, Cell], robots: dict[str, RobotState], tick: int
    ) -> tuple[int, int]:
        owners: dict[Cell, str] = {}
        vertex_conflicts = 0
        for robot_id in sorted(robots):
            cell = robots[robot_id].cell
            other = owners.get(cell)
            if other is not None:
                vertex_conflicts += 1
            owners[cell] = robot_id
        if tick == 0:
            return vertex_conflicts, 0
        reverse_edge_conflicts = 0
        robot_ids = sorted(robots)
        for index, robot_id in enumerate(robot_ids):
            for other_id in robot_ids[index + 1 :]:
                if (
                    before[robot_id] == robots[other_id].cell
                    and before[other_id] == robots[robot_id].cell
                    and before[robot_id] != before[other_id]
                ):
                    reverse_edge_conflicts += 1
        return vertex_conflicts, reverse_edge_conflicts

    def _validate_tasks(self, tasks: tuple[Task, ...]) -> None:
        if len({task.task_id for task in tasks}) != len(tasks):
            raise ValueError("task identifiers must be unique")
        for task in tasks:
            if not self._map.traversable(task.pickup) or not self._map.traversable(
                task.dropoff
            ):
                raise ValueError(
                    f"task {task.task_id} uses a blocked or out-of-bounds cell"
                )
