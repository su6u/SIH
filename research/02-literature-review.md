# 02 — Literature and algorithm review

## Research verdict

The literature does not support a single “best algorithm” for this challenge. The practical design is a layered hybrid:

1. **Distributed auction with expiring task leases** for online MRTA/MAPD.
2. **Local space-time A\*** for route generation.
3. **Short-horizon reservations** for vertices, directed edges and named bottlenecks.
4. **PIBT-inspired priority inheritance/backtracking** for immediate local jams.
5. **Repeated-state and wait-for-cycle detection** for deadlock/livelock recovery.
6. **A deterministic execution shield** beneath planning and learning.
7. **A small congestion/ETA predictor** that adjusts bids and route costs only.

This combination is an engineering synthesis from the sources below. No single paper proves the entire system.

## Algorithm comparison

| Method | Nature | Best property | Critical limitation | Hackathon use |
|---|---|---|---|---|
| Independent A* | Local, uncoordinated | Tiny and fast | Produces vertex/edge conflicts and traffic hotspots | Weak baseline |
| Stop-and-wait | Reactive safety rule | Simple and safe under ideal sensing | Serializes traffic; can deadlock/starve | Required comparison |
| CBS | Centralized optimal search | Optimal under its model | Conflict tree can explode | Small-instance oracle |
| ECBS/EECBS | Centralized bounded-suboptimal | Faster with a cost bound | Still a global planner | Optional reference |
| PBS | Priority-tree search | Strong runtime/quality tradeoff | Centralized priority search | Reference |
| RHCR | Centralized rolling horizon | Lifelong warehouse throughput; scales in simulation | Myopic windows need care; central | Architectural inspiration |
| MAPF-LNS2 | Central large-neighborhood repair | Excellent dense-instance solver | Complex C++ integration | Benchmark/stretch |
| LaCAM/LaCAM* | Central lazy constraint search | Very fast initial solutions at large scale | Not decentralized execution | Upper comparator |
| PIBT | Local iterative coordination | Fast, simple priority inheritance | Finite-arrival proof needs graph conditions | Core conflict policy |
| Token Passing / TPTS | Distributed-capable MAPD | Understandable assignment + path ownership | Token/partition and well-formed-instance assumptions | Lease/token ideas |
| Space-Time A* / SIPP | Single-agent under reservations | Avoids occupied time slots | Quality depends on reservation horizon/order | Core local planner |
| ORCA/RVO | Local continuous avoidance | Fast reactive motion | Symmetry and narrow aisles can deadlock | Low-level fallback only |
| Auction / Contract Net | Distributed task assignment | Explainable and implementable | Split-brain without epochs/leases | Core task allocation |
| ADMM consensus | Distributed optimization | Principled objective | Iterations/solver complexity | Research reference |
| PRIMAL2/SCRIMP/Follower | Learned local policy | Fast decentralized inference | OOD and no hard safety guarantee | Optional pretrained demo |
| SILLM | Learned guidance + collision resolution | Demonstrated extreme scale | Training/integration beyond 36 hours | Design inspiration |
| Guidance graph optimization | Offline/slow-loop traffic shaping | Improves flow without replacing planner | Requires traces and stable layout | Strong post-MVP lever |

## The most important findings

### 1. The objective is throughput, not merely shortest paths

[RHCR](https://doi.org/10.1609/aaai.v35i13.17344) frames lifelong warehouse MAPF as repeated windowed planning and reports simulation with up to 1,000 agents. [Guidance Graph Optimization](https://doi.org/10.1609/aaai.v38i18.30054) shows that changing traffic costs/directions can improve lifelong flow even when the underlying planner is unchanged. Therefore, individual shortest paths are the wrong system objective.

### 2. Learning is most credible inside a safe search/control stack

[SILLM](https://arxiv.org/abs/2410.21415), [LNS2+RL](https://doi.org/10.1609/aaai.v39i22.34501) and recent learned-priority work use learning to guide or accelerate structured planning rather than asking an unconstrained policy to own all correctness. The [POGEMA 2025 benchmark](https://proceedings.iclr.cc/paper_files/paper/2025/hash/10d19888a94f390e58f922ab3937e1cb-Abstract-Conference.html) is a useful warning against assuming generic MARL automatically beats specialized search.

For SIH, learning predicts traversal delay/congestion. Reservations and the action validator remain authoritative.

### 3. PIBT is excellent but its guarantee is conditional

[PIBT](https://doi.org/10.24963/ijcai.2019/76) is compelling because it makes local priority inheritance and backtracking fast enough for hundreds of agents. Its finite-arrival guarantee depends on graph structure resembling biconnected/cycle-rich environments. Arbitrary one-cell warehouse aisles can violate that condition. We therefore use “PIBT-inspired,” add explicit corridor leases/pull-outs, and test deadlock/livelock rather than claiming a universal theorem.

### 4. Planning and execution must be separated

[Persistent and Robust Execution of MAPF Schedules](https://doi.org/10.1109/LRA.2019.2894217), [SMART](https://arxiv.org/abs/2503.04798), [LSMART](https://arxiv.org/abs/2602.15721), and the 2026 [timing-uncertainty execution framework](https://doi.org/10.1016/j.artint.2026.104586) all attack the gap between a collision-free plan and imperfect physical execution. This motivates a commitment horizon, action dependency/reservation checks, timing buffers and safe-stop behavior.

### 5. Real warehouses couple routing and assignment

[Multi-Agent Path Finding with Real Robot Dynamics and Interdependent Tasks](https://arxiv.org/abs/2408.14527) adds dynamics and pickup/drop dependencies. [Many-to-Many MAPD](https://arxiv.org/abs/2605.07835) shows that one SKU may have multiple valid pickup/drop locations. [Dynamic MAPD in robotic cellular warehouses](https://arxiv.org/abs/2606.05669) handles orders that change during execution. A task bid therefore needs route congestion, capability, battery and risk—not Euclidean distance alone.

### 6. Distributed assignment needs failure semantics

Distributed auction papers show scalable assignment, but a working protocol must add epochs, deterministic tie-breaking, idempotency, leases and completion tombstones. These are distributed-systems inferences needed for delayed, duplicated and partitioned messages; “everyone heard the same bid” is not safe as an assumption.

## 2024–2026 frontier worth tracking

- **2026 LSMART:** realistic lifelong AGV testbed with kinodynamics, communication delays, planner invocation/failure policies.
- **2026 robust execution under timing uncertainty:** adjusts legal concurrent movement online using dependency/feasibility reasoning.
- **2026 many-to-many MAPD:** multiple valid storage locations materially change assignment quality.
- **2026 dynamic MAPD:** order content can evolve while robots execute.
- **2026 learned priorities for warehouse LMAPF:** promising because ML guides prioritized planning rather than replacing feasibility checks.
- **2025 SMART:** scalable real-dynamics bridge between abstract MAPF and fleet execution.
- **2025 SILLM:** very large-scale imitation learning with structured collision resolution.
- **2025 WinC-MAPF:** explicitly addresses completeness and livelock/deadlock in windowed planning.
- **2024 real dynamics/interdependent tasks:** warehouse task and motion realism.
- **2024 guidance-graph optimization:** co-optimizing traffic structure can beat merely improving the solver.

## Edge-AI model proposal

Train one compact gradient-boosted regressor or tiny MLP from simulator traces.

Inputs per candidate graph edge:

- local robot density;
- reserved time slots in the next horizon;
- intersection queue length;
- recent mean/p95 traversal delay;
- opposing-flow imbalance;
- robot payload and battery class;
- packet latency/loss estimate;
- recent replans and blockage flag.

Outputs:

- predicted traversal time; optionally
- calibrated probability of severe delay within the next horizon.

Use:

`route_edge_cost = geometry + predicted_delay + reservation_pressure + risk + turn_penalty`

`task_bid_cost = predicted_finish + battery_penalty + deadline_penalty + fairness_penalty`

Required ablation: independent shortest path → deterministic congestion heatmap → learned prediction → learned prediction plus distributed coordination.

## What not to overclaim

- A* is not AI differentiation.
- “Edge AI” does not require a large neural network.
- Decentralized decisions over one MQTT broker are not infrastructure-independent.
- PIBT does not make every arbitrary layout deadlock-free.
- An average 20% improvement can hide starvation; report p95/max wait and fairness.
- Zero observed collisions in simulation is not a physical safety certification.
