# 05 — Failure and threat model

## Safety invariants

1. No two robots occupy the same reserved vertex interval.
2. No two robots traverse the same edge in opposite directions during overlapping intervals.
3. No robot enters a named conflict zone without a current lease matching its plan/map epoch.
4. No robot moves beyond its verified commitment horizon when relevant peer state is stale.
5. Learning may alter cost, never permission.
6. Task state transitions are idempotent and monotonic within an epoch.
7. Dashboard/database availability cannot be required for motion decisions.

## Scenario catalogue

| Failure / edge case | Detection | Safe response | Evidence to log |
|---|---|---|---|
| Same-cell arrival | Overlapping vertex intervals | Deny lower priority; replan/wait | rejected action, owner, interval |
| Head-on edge swap | Opposite edge reservations | Deny; choose alternate/wait | both intents and decision |
| Rear-end delay | Actual ETA leaves buffer | Extend occupancy; follower slows/stops | delay, min separation |
| Corner/rotation overlap | Swept footprint check | Add turn reservation/buffer | footprint conflict |
| Narrow-aisle face-off | Corridor token contention | One backs to pull-out | wait-for chain, victim |
| Four-robot cycle | Wait-for graph cycle | Priority inherit; backtrack one | cycle members, recovery time |
| Livelock | Repeated local state hash | Change order/small-group repair | hash count, alternative |
| Starvation | Wait age/max wait | Priority aging/reserved opportunity | wait distribution/fairness |
| Robot stops in zone | Missed progress heartbeat | Freeze zone, stop approaches, recover | blocked zone duration |
| Blocked aisle | Local incident / no progress | Share incident, version edge, replan | discovery propagation time |
| Human/dynamic obstacle | Local proximity sensor | Immediate local stop; publish incident | stop latency/min distance |
| Localization drift | Covariance/pose disagreement | Slow/stop, widen buffer, relocalize | uncertainty trace |
| Clock skew | Offset/uncertainty estimator | Inflate leases; rely on sequence/epochs | estimated error |
| Planner timeout/no path | Deadline watchdog | Deterministic wait/backtrack | duration/fallback |
| AI timeout/NaN/OOD | Input/model watchdog | Deterministic congestion cost | model status/fallback |
| Duplicate task announce | Idempotency key/tombstone | Ignore/replay prior response | duplicate count |
| Identical bids | Deterministic tuple | Same winner on all peers | ordered bids |
| Winner fails before pickup | Lease expires/heartbeat | Re-auction | orphan duration |
| Winner fails after pickup | Missing progress + load state | `RECOVERY_REQUIRED`, human/peer policy | payload location |
| Low battery mid-task | Energy forecast | Reassign before pickup; safe charge plan | predicted/actual energy |
| Charger contention | Charger reservation | Auction/queue with battery urgency | queue/wait |
| Delayed message | TTL/epoch/sequence | Ignore stale proposal | age and rejection |
| Out-of-order message | Monotonic sequence | Ignore older state | reorder count |
| Duplicated message | Idempotency key | No repeated transition | duplicate count |
| Packet loss | ACK timeout | Retry boundedly; safe stop if critical | loss/retry/stop |
| Partition | Peer freshness/quorum policy | Finish committed segment, then stop | availability/recovery |
| Split-brain zone lease | Conflicting epoch/ACK set | Treat zone unavailable | conflict record |
| Stale map/config | Digest mismatch | Stop before changed region; sync/replan | versions |
| Rejoining old robot | Boot ID/epoch mismatch | Reconcile; discard old claims | reconciliation time |
| Message storm | Rate/budget monitor | Coalesce state; preserve critical traffic | bytes/messages/latency |
| Dashboard crash | Missing observer only | No robot behavior change | fleet continuity |
| Telemetry DB crash | Writer errors | Buffer/drop observation, never control | lost observations |

## Security-minded extensions

The SIH statement emphasizes reliability more than adversaries, but BEL judges may value basic hardening:

- Pre-shared team identity or per-robot keys for message authentication.
- Schema/version validation and bounded payload sizes.
- Replay protection via boot ID + sequence + TTL.
- Allowlist for robot and map identities.
- Rate limits separated by criticality.
- Audit log of claims, leases and incidents.
- Safe behavior for unauthenticated/invalid traffic.

Do not call a checksum a cryptographic signature. For the prototype, HMAC is explainable and feasible.

## Fault-injection matrix

At minimum test:

- loss: 0%, 5%, 20%, 50% burst;
- one-way latency: 0, 50, 200, 1,000 ms plus jitter;
- duplicate/reorder rates;
- one robot crash in idle, before pickup, during travel and inside a zone;
- partition of one robot and 50/50 group split;
- map update while routes are active;
- dashboard and database termination;
- predictor timeout and corrupted feature vector.

Every injected fault needs an expected invariant, expected degradation, maximum recovery window and a pass/fail rule.
