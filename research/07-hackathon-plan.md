# 07 — Six-person hackathon plan

Assumption: 36 hours, four technical members (lead/generalist; two Python developers; one SQL/data developer) and two presentation/operations members.

## Ownership

| Member | Primary ownership | Concrete deliverables |
|---|---|---|
| 1 — Lead/generalist | Architecture, protocol, safety, integration | message schemas, state machines, shield, merge, demo control |
| 2 — Python A | Distributed task layer | auctions, epochs, leases, idempotency, failure reassignment, tests |
| 3 — Python B | Motion coordination | space-time A*, reservations, priority inheritance, deadlock recovery |
| 4 — SQL/data | Experiment/replay | append-only event schema, seeded runner, metrics queries/API, predictor dataset |
| 5 — QA/evidence | Failure matrix and research validation | scenario configs, run checklist, citation audit, screenshots/video backup |
| 6 — Story/UI | Dashboard and pitch operations | judge flow, UI content, poster/slides, narration, timekeeping |

Member 4 must not put task/lease truth in SQL. Storage is observability only.

## 36-hour schedule

### Hours 0–3 — freeze contracts

- Fix map representation, time model and robot footprint assumptions.
- Write message schema and state-machine diagrams.
- Define stop-and-wait baseline exactly.
- Freeze three must-pass demo scenarios and metrics.

### Hours 3–10 — vertical tracer bullet

- Three independent robot processes.
- Task generator and deterministic replay.
- Basic A*, motion loop and event transport.
- Telemetry logger and minimal map view.
- One task completes end-to-end.

### Hours 10–18 — coordination core

- Auction epochs/leases and tie-breaking.
- Vertex/edge/zone reservations.
- PIBT-inspired priority inheritance.
- Three-way intersection and narrow aisle tests.
- First stop-and-wait comparison.

### Hours 18–24 — failure semantics

- Blocked aisle propagation/replan.
- Robot crash and task reassignment.
- Delay/loss/reorder injection.
- Safe stop on stale peer state.
- Deadlock/repeated-state recovery.

### Hours 24–28 — Edge AI

- Generate trace features.
- Train compact ETA/congestion model.
- Wire model into bids/edge weights behind timeout/fallback.
- Run fixed-cost and learned-cost ablation.

### Hours 28–32 — evidence freeze

- Run paired seeds and compute confidence intervals.
- Capture best representative replay and failure recovery.
- Freeze product features; only correctness fixes afterward.
- If stable, connect 3–6 Nav2/Gazebo agents as a stretch.

### Hours 32–35 — pitch and backup

- Five-minute demo rehearsal.
- Recorded offline backup.
- Slide/poster claim audit.
- Verify dashboard/database kill test.
- Package configs, raw logs and citations.

### Hour 35–36 — buffer

Bug fixes, no new features.

## Definition of minimum convincing demo

- 12–20 logical robots on a visible warehouse graph.
- Continuous task arrivals.
- Live task auction and zone lease visualization.
- A blocked aisle triggers local model cost change and reroute.
- A robot disconnects; it safe-stops and its unstarted task is reassigned.
- Dashboard is killed while robot processes continue.
- A paired baseline/proposed run shows ≥20% improvement under the chosen overlap workload.

## Stretch order

1. Better statistical dashboard.
2. Gazebo/Nav2 3-robot adapter.
3. Many-to-many SKU pickup choice.
4. ONNX export to Pi/Jetson.
5. Small-group ECBS repair.

Do not reverse this order. A beautiful ROS world with weak distributed logic will miss the problem.

## Merge discipline

- One shared schema package frozen early.
- Feature branches or clearly owned modules.
- Seeded smoke scenario required before merge.
- No unreviewed protocol field changes after hour 18.
- Tag a known-good demo every four hours after the tracer bullet.
- Maintain a one-command offline demo and a prerecorded fallback.
