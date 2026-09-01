# 08 — Pitch and demo script

## Core story

“Most fleet demos put intelligence in one server. SwarmRoute puts the decision loop on every robot. They announce work, negotiate short-horizon space-time reservations, inherit priority when traffic jams, and stop safely when agreement disappears. A tiny edge model predicts congestion, but deterministic code owns collision safety.”

## Five-minute flow

### 0:00–0:35 — problem

Show three robots converging on one intersection. Explain that selfish shortest paths are locally sensible and globally bad; a central controller adds a failure/network dependency.

### 0:35–1:05 — architecture

Point to identical per-robot agents and the read-only dashboard. State the five layers: auction, space-time route, zone lease, priority inheritance, safety shield.

### 1:05–1:45 — baseline

Run the fixed seed with stop-and-wait. Highlight queueing, task time and attempted conflicts. Do not manufacture an actual crash for drama.

### 1:45–2:35 — distributed run

Replay the identical seed with SwarmRoute. Show task bids and intersection ownership. Point to a robot accepting a slightly longer path because predicted congestion makes fleet throughput better.

### 2:35–3:25 — failure

Block the preferred aisle, then disconnect one robot. Show: incident propagation → reroute → isolated robot safe-stop → lease expiry → pre-pickup task reassignment.

### 3:25–3:50 — no hidden controller

Kill the dashboard/telemetry service. Robots continue. Explain that observation is centralized for humans; decision authority is not.

### 3:50–4:30 — evidence

Show paired metrics: completion-time improvement, throughput, p95 wait, zero executed modeled conflicts, recovery time and AI ablation. State trial count and assumptions.

### 4:30–5:00 — close

“We are not claiming a certified warehouse controller. We built the architecture that can become one: distributed decisions, deterministic safety, measurable edge intelligence and failure behavior that is safe by design.”

## Likely judge questions

### “Where is the AI?”

The on-device model predicts edge traversal delay/congestion from local density, reservations, queue, payload and network state. It changes route and bid cost. The ablation quantifies its contribution. Safety remains deterministic.

### “Is this really decentralized if there is a dashboard?”

Yes at the decision layer. Each robot owns its state, bids, routes and leases. The dashboard is a subscriber. We prove it by killing the dashboard during motion.

### “Can you guarantee zero collision?”

Under our declared simulator model, the shield enforces vertex, edge, footprint-buffer and conflict-zone invariants. We report zero executed conflicts across N seeded trials. Real deployment requires certified hardware safety, localization/perception validation and industrial testing.

### “Why not MARL?”

Training and out-of-distribution validation are disproportionate for 36 hours, and a policy does not provide the hard audit trail needed for collision safety. Current strong work increasingly uses learning to guide structured planning/search. We follow that pattern.

### “Why not Open-RMF?”

Open-RMF is an excellent interoperability and centralized traffic-management reference. Its authoritative schedule does not satisfy the challenge’s peer decision objective by itself. We can expose an adapter later.

### “What happens in a network partition?”

We choose safety over liveness. Robots finish only committed clear segments, acquire no contested zone without fresh agreement, then stop at safe nodes. On reconnect they reconcile epochs and replan.

### “How do you beat stop-and-wait?”

We reserve before the conflict, route some robots around hotspots, coordinate small speed/wait windows and allocate tasks using predicted finish time—not just distance. Paired seeds make the difference measurable.

## Slide titles

1. One server should not stop the warehouse.
2. The real problem is lifelong assignment + traffic + execution.
3. Every robot runs the same SwarmRoute agent.
4. Learning predicts; deterministic logic protects.
5. Failure is a state, not a surprise.
6. Same workload, paired evidence.
7. A 36-hour build with a production-shaped architecture.
