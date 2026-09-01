# 04 — Recommended solution architecture

## Name and pitch

**SwarmRoute** is a safety-first distributed coordination layer for warehouse AMRs. Every robot runs the same decision agent. A dashboard observes; it never commands. The system degrades safely when peers disappear and uses edge learning only to forecast cost/risk.

## Per-robot components

1. **State estimator** — pose, heading, velocity, battery, payload, health, monotonic sequence.
2. **Task agent** — announces, bids, claims, renews and completes lease-backed tasks.
3. **Route planner** — A*/space-time A* over a warehouse lane graph.
4. **Intent ledger** — peer route hashes, next 3–8 edges, ETA windows and freshness.
5. **Reservation manager** — vertices, directed edges and named conflict zones.
6. **Priority manager** — base priority, wait aging, urgency, inherited priority, backtracking.
7. **Deadlock monitor** — local wait-for graph and repeated-state hashes.
8. **Edge predictor** — ETA/congestion inference with timeout and deterministic fallback.
9. **Safety shield** — validates every move and commands slow/stop on stale or unsafe state.
10. **Telemetry emitter** — append-only observations for replay/dashboard; never required for motion.

## Messages

All messages carry `schema_version`, `sender_id`, `boot_id`, `sequence`, `sent_monotonic`, `map_version`, `ttl` and `payload_hash`.

| Message | Essential payload |
|---|---|
| `robot_state` | pose, velocity, battery, mode, active task, health |
| `intent` | plan ID/hash, next edges, buffered ETA windows, commitment horizon |
| `task_announce` | task ID, pickup/drop choices, priority, deadline, capability |
| `task_bid` | epoch, cost decomposition, feasible flag |
| `task_claim` | epoch, deterministic winner, lease expiry |
| `task_renew/release/complete` | idempotency key, epoch, state transition |
| `zone_request` | zone, requested interval, approach node, priority tuple |
| `zone_grant/deny` | proposal ID, interval, reason, peer view |
| `zone_enter/release` | actual entry/exit and sequence |
| `incident` | blocked edge, failed robot, localization fault, emergency stop |
| `map_digest` | map/config version and hash |

## Distributed task auction

Candidate cost:

`finish_eta + congestion + battery_risk + deadline_risk + route_risk + fairness_penalty`

Protocol:

1. Any robot may announce a task with a unique task ID and auction epoch.
2. Eligible peers compute bids from the same task/map version.
3. Each peer independently sorts the deterministic winner tuple: lowest feasible cost, oldest task, lowest robot ID.
4. Winner publishes a claim; peers record the lease.
5. Winner renews until pickup. On expiry before pickup, task returns to auction.
6. After pickup, ownership transfer requires an explicit recovery state; do not silently double-pick.
7. Completion writes a tombstone so stale/replayed announces cannot resurrect work.

This is eventual agreement under the demo’s crash/loss model, not Byzantine consensus.

## Route and reservation logic

- Initial route: space-time A* using learned/deterministic edge weights.
- Reserve both `(vertex, time interval)` and `(directed edge, time interval)` to catch same-cell and head-on swaps.
- Inflate time intervals by clock/localization/execution uncertainty.
- Named one-lane corridors and intersections require leases before entry.
- A robot enters only when the path to the conflict-zone exit/pull-out is available.
- Priority tuple combines task urgency, accumulated wait, low battery risk and robot ID.
- On local conflict, inherit the highest blocked priority backward through the chain and backtrack a selected robot to a pull-out.
- On wait-for-cycle or repeated state, change the ordering and replan the smallest involved group.

## Safety shield

The shield rejects a proposed action if any condition holds:

- vertex or directed-edge reservation conflicts;
- conflict-zone lease absent, expired or mismatched;
- peer intent within collision radius is stale;
- projected footprint/separation violates buffer;
- map/version mismatch affects the route;
- local proximity/human sensor reports danger;
- planning/inference deadline missed;
- current state is uncertain beyond threshold.

Fallback: slow to a declared safe node and stop. A learned prediction can raise route cost but cannot override a shield rejection.

## Network partition behavior

The design chooses safety over liveness:

- Continue only through already committed, locally verified segments.
- Acquire no new contested zone without fresh required acknowledgements.
- Stop before the commitment horizon expires.
- Accept no new task while isolated.
- On reconnect, discard expired proposals, reconcile epochs/tombstones/map hashes, then replan.

There is no honest way to promise both perfect agreement and unlimited availability during arbitrary partitions.

## Dashboard and storage

The UI subscribes to events and computes:

- positions, battery and task ownership;
- planned versus committed paths;
- live reservation/auction messages;
- collision attempts rejected by the shield;
- throughput, p95 completion time, max wait, fairness, messages/sec;
- recovery state and failure timeline.

SQLite/DuckDB tables: `robot_events`, `task_events`, `zone_events`, `network_faults`, `model_predictions`, `trial_metrics`. Killing the dashboard/database is a demo scenario; robots must continue.

## Minimal state machines

### Robot motion

`IDLE → PLANNING → REQUESTING → COMMITTED → MOVING → ARRIVED`

Any state may enter `SAFE_STOP`; recovery goes through `RECONCILING → PLANNING`.

### Task

`ANNOUNCED → BIDDING → LEASED → PICKED → DELIVERED`

Before pickup, an expired lease returns to `ANNOUNCED`. After pickup, failure enters `RECOVERY_REQUIRED`.

### Conflict zone

`FREE_VIEW → PROPOSED → ACKNOWLEDGED → HELD → ENTERED → RELEASED`

Expired or contradictory state never implies permission to enter.

## Novelty that judges can see

- Decision authority demonstrably lives in independent robot processes.
- The dashboard can die without fleet stoppage.
- Auctions and reservations are visible and replayable.
- Failure semantics are designed, not hand-waved.
- Edge AI improves cost prediction while deterministic safety remains auditable.
- The pitch explicitly separates modeled guarantees from production certification.
