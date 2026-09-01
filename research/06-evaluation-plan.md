# 06 — Evaluation plan

## Primary claim

Demonstrate at least 20% lower total task-completion time than stop-and-wait on overlapping routes while executing zero modeled inter-robot conflicts in the declared simulator/test conditions.

The fair test is paired and seeded: identical map, task arrivals, robot properties, faults and random seed for every policy.

## Policies / ablations

1. **Stop-and-wait baseline** — independent shortest paths plus reactive yield.
2. **Independent A*** — reveals unsafe/conflict-prone selfish routing; report attempted conflicts.
3. **Distributed deterministic** — auctions + reservations + priority inheritance, fixed costs.
4. **Distributed + heatmap** — moving-average congestion costs.
5. **Distributed + edge model** — learned ETA/congestion cost.
6. **Optional oracle** — CBS/EECBS/LaCAM on small frozen batches only.

This isolates whether gains come from coordination or from the claimed AI component.

## Maps and scale

- Standard [MovingAI warehouse maps](https://movingai.com/benchmarks/mapf/).
- [LoRR benchmark archive](https://github.com/MAPF-Competition/Benchmark-Archive).
- POGEMA warehouse/maze/bottleneck families.
- Handcrafted three-way intersection, one-cell aisle, passing bay and circular-deadlock maps.

Run 4, 8, 16, 32 and, if cheap, 64 agents. The physical/ROS proof needs only 3–6 agents.

## Workloads

- steady Poisson task arrivals;
- burst arrivals;
- one-zone hotspot;
- opposing traffic through a choke point;
- priority/deadline tasks;
- pickup/drop dwell time;
- battery and charger contention;
- blocked aisle and failed robot;
- multiple possible SKU pickup locations as a stretch.

## Metrics

### Outcome

- tasks completed per minute;
- total and mean task flow time;
- p50/p95/max task completion time;
- makespan and sum-of-costs for fixed batches;
- deadline miss rate;
- improvement percentage versus stop-and-wait.

### Safety and resilience

- executed vertex, edge-swap, footprint and unauthorized-zone conflicts;
- unsafe proposals rejected by the shield (separate from executed collisions);
- minimum simulated separation;
- deadlocks/livelocks and recovery time;
- orphaned/duplicated tasks;
- safe-stop count and duration;
- availability and throughput during/after partition.

### Fairness and efficiency

- maximum robot wait;
- starvation count;
- Jain fairness index over completed tasks or waiting time;
- distance and energy proxy per task;
- idle time and route replans.

### Edge and communication

- p50/p95 planner and model inference latency;
- process memory and CPU per robot;
- messages and bytes per robot per second;
- stale/duplicate/reordered message count;
- task/zone agreement latency.

## Statistical protocol

- Minimum 10 seeds for development; target 30 for final claims.
- Report median and bootstrap 95% confidence interval, not only the best run.
- Publish scenario config, seed and raw event log.
- Predefine excluded/crashed trials; never silently drop a bad run.
- Plot full distributions or boxplots for completion time and wait.
- Report density/load point where the system collapses.

## Acceptance gates

| Gate | Pass condition |
|---|---|
| Safety | 0 executed modeled conflicts across final matrix |
| SIH target | ≥20% reduction in total completion time on declared overlap suite |
| No hidden controller | Fleet continues after dashboard and DB termination |
| Partition | No unleased entry; isolated robot reaches safe stop |
| Reassignment | Failed pre-pickup winner’s task is safely re-auctioned |
| Deadlock | All handcrafted cycles detected and resolved within limit |
| AI value | Learned model beats deterministic distributed variant on held-out workloads without safety regression |
| Edge budget | p95 decision latency below chosen control deadline on target-class machine |

## Judge-facing visualizations

- One replay with baseline and proposed policy side by side.
- Throughput bar with confidence intervals.
- Task completion p95 and maximum wait.
- Conflict-attempt versus executed-conflict counters.
- Live zone lease and task-auction event stream.
- Network partition timeline showing safe degradation and recovery.
- AI ablation showing predicted versus actual edge delay.

## Claim formula

`improvement = (baseline_total_time - proposed_total_time) / baseline_total_time × 100`

Also report throughput improvement; total time alone can be misleading for continuous workloads.
