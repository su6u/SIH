# 03 — Open-source landscape

## Recommendation

Start with a lightweight Python graph simulator and one independent process per robot. Study/adapt PyPIBT and POGEMA, use standard MovingAI/LoRR maps, and inject network faults. Add ROS 2/Nav2/Gazebo only after the coordination core is stable. Treat Open-RMF as an architecture/interoperability reference and centralized comparator—not as proof of a decentralized solution.

## Project comparison

Activity is a 2 September 2026 snapshot and is not a correctness guarantee.

| Project | License | Stack | Integration | Decision |
|---|---|---|---:|---|
| [Open-RMF](https://github.com/open-rmf/rmf) / [rmf_ros2](https://github.com/open-rmf/rmf_ros2) | Apache-2.0 | C++/Python/ROS 2 | High | Reference, optional comparison |
| [Open-RMF fleet adapter template](https://github.com/open-rmf/fleet_adapter_template) | Apache-2.0 | Python/ROS 2 | Medium-high | Useful interface example |
| [Free Fleet](https://github.com/open-rmf/free_fleet) | Apache-2.0 | Python/ROS 2/Zenoh | Medium-high | Study Nav2/Zenoh wiring |
| [Nav2](https://github.com/ros-navigation/navigation2) | Mixed by package | C++/Python | Medium | Per-robot navigation/stretch |
| [Gazebo Sim](https://github.com/gazebosim/gz-sim) | Apache-2.0 | C++/Python | Medium-high | 3–6 robot physics proof only |
| [POGEMA](https://github.com/Cognitive-AI-Systems/pogema) | MIT | Python | Low | Best rapid benchmark base |
| [PyPIBT](https://github.com/Kei18/pypibt) | MIT | Python | Low | Compact algorithm reference |
| [LaCAM3](https://github.com/Kei18/lacam3) | MIT | C++17 | Medium | Strong centralized upper baseline |
| [libMultiRobotPlanning](https://github.com/whoenig/libMultiRobotPlanning) | MIT | C++14 | Medium | CBS/ECBS/SIPP reference |
| [RHCR](https://github.com/Jiaoyang-Li/RHCR) | USC Research License | C++ | Medium | Study; check reuse terms |
| [MAPF-LNS2](https://github.com/Jiaoyang-Li/MAPF-LNS2) | USC Research License | C++ | Medium | Benchmark; check reuse terms |
| [EECBS](https://github.com/Jiaoyang-Li/EECBS) | USC Research License | C++ | Medium | Small-instance baseline |
| [SMART](https://github.com/smart-mapf/smart) | Repository license must be checked at pin | C++/Python | Medium-high | Realistic execution reference |
| [LSMART](https://github.com/smart-mapf/lifelong-smart) | Check at pin | C++/Python | Medium-high | 2026 lifelong testbed reference |
| [LoRR](https://github.com/MAPF-Competition) | Repository-specific | C++/Python | Low-medium | Benchmarks and winning systems |
| [rmw_zenoh](https://github.com/ros2/rmw_zenoh) | Apache-2.0 | C++/Rust | Medium-high | Promising but more than MVP needs |
| [zenoh-python](https://github.com/eclipse-zenoh/zenoh-python) | EPL/Apache family | Python/Rust | Low-medium | P2P coordination-plane option |
| [VDA 5050](https://github.com/VDA5050/VDA5050) | Spec/repo terms | JSON schema | Medium | Message/interoperability reference |
| [MassRobotics AMR Interop](https://github.com/MassRobotics-AMR/AMR_Interop_Standard) | Spec/repo terms | JSON/messages | Medium | Status/coexistence reference |

## Important Open-RMF distinction

Open-RMF is mature and relevant, but the [RMF core architecture](https://osrf.github.io/ros2multirobotbook/rmf-core.html) describes an authoritative traffic schedule/database. Fleet adapters negotiate, yet that does not make standard RMF a peer-to-peer decentralized fleet controller. Reusing its concepts while placing the SIH decision loop inside each robot is more aligned with the problem.

## Communication choice

For the algorithmic prototype:

- Use in-process transport during unit/property testing.
- Use `zenoh-python` or a minimal UDP/WebSocket peer layer for the multi-process demo.
- Keep messages small: heartbeat, intent horizon, bids, leases, incidents—not LiDAR streams.
- Do not mix `rmw_zenoh` and `zenoh-bridge-ros2dds` mappings without deliberate compatibility work.
- If ROS 2 is added, keep DDS/Nav2 local to each robot namespace and bridge only coordination messages.

## Simulator ladder

### Level 1 — algorithmic digital twin (must)

- 20–100 lightweight agents.
- Deterministic replay and seeded workloads.
- Space-time conflicts, robot footprints/turn delay approximation.
- Adjustable packet delay, loss, duplication, reordering and partition.
- Baseline and ablation runner.

### Level 2 — robotics proof (stretch)

- 3–6 TurtleBot-like agents in Gazebo/Nav2 namespaces.
- Coordinator emits waypoints and leases.
- Nav2 follows; local collision monitor remains authoritative.
- Dashboard subscribes read-only.

## Tools worth reusing

- [MovingAI MAPF maps](https://movingai.com/benchmarks/mapf/)
- [LoRR Benchmark Archive](https://github.com/MAPF-Competition/Benchmark-Archive)
- [POGEMA](https://github.com/Cognitive-AI-Systems/pogema)
- [Linux netem](https://man7.org/linux/man-pages/man8/tc-netem.8.html) for real process-level delay/loss/jitter/reordering
- Property-based tests with Hypothesis for protocol invariants
- SQLite/DuckDB for append-only experiment telemetry, never coordination truth

## Community findings (anecdotal)

ROS/robotics discussions repeatedly mention multi-robot namespace/TF setup, Gazebo spawning, DDS discovery and fleet-adapter integration as schedule risks. Open-RMF production discussions also show that apparent traffic bugs may originate in downstream Nav2/path-pruning behavior. These posts identify tests to run; they do not establish algorithm performance.

- [Open-RMF U-turn discussion](https://discourse.openrobotics.org/t/random-u-turns-with-rmf/50557)
- [ROS 2 multi-robot Nav2 discussion](https://www.reddit.com/r/ROS/comments/1d5bakm)
- [Open-RMF TurtleBot integration discussion](https://www.reddit.com/r/ROS/comments/1e1kr8f)
- [ROS middleware discussion on Hacker News](https://news.ycombinator.com/item?id=40634556)

No genuinely substantive 4chan source was found. Adding irrelevant anonymous posts would reduce, not increase, research quality.
