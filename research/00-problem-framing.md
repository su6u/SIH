# 00 — Problem framing

## Verified challenge

SIH26123 is a Bharat Electronics Limited software problem under Robotics & Drones. The requested simulation must demonstrate at least three warehouse AMRs, local/edge computation, robot-to-robot state and intent sharing, dynamic conflict/deadlock resolution, task reassignment and rerouting, plus a monitoring dashboard. The published success target is zero inter-robot collisions and at least 20% lower total task-completion time than stop-and-wait when routes overlap.

The clearest indexed statement is the [SIH26123 problem mirror](https://sih2026.vuce.in/en/ps/SIH26123), which links onward to the official SIH site. The user-provided pasted explainer was not treated as technical authority.

## Correct mathematical framing

This is not one algorithm. It is a coupled online system:

| Layer | Formal family | Decision |
|---|---|---|
| Orders | Multi-Agent Pickup and Delivery (MAPD) | Which pickup/drop sequence is active? |
| Assignment | Multi-Robot Task Allocation (MRTA) | Which capable robot owns each task? |
| Routing | Lifelong Multi-Agent Path Finding (LMAPF) | Which collision-free route is used as tasks keep arriving? |
| Traffic | Space-time reservation / resource allocation | Who occupies a shared aisle or intersection, and when? |
| Execution | Robust path execution | What remains safe under delay, drift, obstacles, and failure? |
| Learning | Edge inference | What is the predicted traversal delay or congestion risk? |
| Safety | Hard shield / state machine | Is the proposed next action permitted? |

### Why lifelong MAPF matters

One-shot MAPF fixes starts and goals and ends when all agents arrive. A warehouse continuously produces new pickup-and-delivery work, so throughput, tail latency, fairness, energy and recovery matter more than the optimal sum-of-costs for one frozen batch. This is why RHCR, MAPD, POGEMA/LoRR and 2025–2026 realistic execution work are more relevant than a classroom CBS-only demo.

### Why a discrete safe plan is not enough

Classical grid MAPF usually prevents same-vertex and edge-swap conflicts at synchronized time steps. Physical AMRs have footprints, turn radii, acceleration, localization error, clock error and unpredictable dwell time. A path that is safe under unit-time pebble motion can become unsafe when one robot leaves a cell late. The prototype therefore separates planning from execution safety and adds buffers, leases, heartbeats and a local brake/stop state machine.

## Non-functional requirements inferred from the wording

These are engineering inferences, not hidden SIH requirements:

- **No authoritative central controller:** a dashboard or telemetry database may exist, but killing it must not stop robot decisions.
- **Fail-safe partition policy:** when agreement is impossible, preserve safety rather than pretending both partitions can remain fully available.
- **Bounded edge work:** planning and inference must complete on Pi/Jetson-class hardware, so algorithms need predictable short horizons.
- **Explainability:** judges should see auctions, reservations, priority inheritance and failure recovery—not just moving dots.
- **Reproducibility:** the ≥20% claim must come from paired, seeded runs against a defined baseline.

## Scope boundary for the hackathon

### Must prove

- 3–20 logical robots, each with independent state and decision loop.
- Decentralized task ownership and conflict-zone access.
- Zero executed modeled conflicts in the declared test matrix.
- Aisle blockage, robot failure, packet delay/loss and dashboard failure.
- Side-by-side stop-and-wait versus SwarmRoute metrics.
- Measurable contribution from the edge model via ablation.

### Should not consume the schedule

- Production SLAM, perception, manipulation or mechanical design.
- Hundreds of physics-heavy Gazebo robots.
- Full Open-RMF customization.
- Industrial functional-safety certification.
- Distributed consensus under arbitrary Byzantine behavior.

## Honest claim language

Say: “Across N seeded trials in our simulator, under the stated kinematic and network model, no robot entered an occupied vertex, conflicting edge, or unleased critical zone.”

Do not say: “AI guarantees zero collisions in every real warehouse.”
