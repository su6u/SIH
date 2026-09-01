# 09 — Curated bibliography

Snapshot: 2 September 2026. Recent arXiv items are marked **preprint**; they are design signals, not equivalent to mature peer-reviewed evidence.

## Foundations and search

1. Stern et al., [Multi-Agent Pathfinding: Definitions, Variants, and Benchmarks](https://doi.org/10.1609/socs.v10i1.18510), SoCS 2019 — standard terminology, objectives and collision models.
2. Sharon et al., [Conflict-Based Search for Optimal Multi-Agent Pathfinding](https://doi.org/10.1016/j.artint.2014.11.006), Artificial Intelligence 2015 — foundational optimal CBS.
3. Li, Ruml & Koenig, [EECBS](https://arxiv.org/abs/2010.01367), AAAI 2021 — bounded-suboptimal CBS reference.
4. Ma et al., [Searching with Consistent Prioritization](https://doi.org/10.1609/aaai.v33i01.33017643), AAAI 2019 — priority-based search.
5. Okumura et al., [Priority Inheritance with Backtracking](https://doi.org/10.24963/ijcai.2019/76), IJCAI 2019 — fast iterative/local coordination with explicit graph assumptions.
6. Okumura, [LaCAM](https://arxiv.org/abs/2211.13432), 2022/AAAI 2023 — scalable lazy constraint addition.
7. Okumura, [Improving LaCAM / LaCAM*](https://arxiv.org/abs/2305.03632), IJCAI 2023 — quick initial solution and eventual optimality.
8. Li et al., [MAPF-LNS2](https://doi.org/10.1609/aaai.v36i9.21266), AAAI 2022 — large-neighborhood collision repair; [code](https://github.com/Jiaoyang-Li/MAPF-LNS2).
9. Andreychuk et al., [Multi-Agent Pathfinding with Continuous Time](https://doi.org/10.24963/ijcai.2019/6), IJCAI 2019 — asynchronous action durations.
10. [WinC-MAPF](https://arxiv.org/abs/2410.01798), AAAI 2025 — completeness framework and explicit deadlock/livelock analysis for windowed planning.

## Lifelong MAPF and warehouse task coupling

11. Ma et al., [Lifelong Multi-Agent Path Finding for Online Pickup and Delivery](https://arxiv.org/abs/1705.10868), AAMAS 2017 — foundational MAPD/token-passing formulation.
12. Ma et al., [MAPD with Kinematic Constraints](https://doi.org/10.1609/aaai.v33i01.33017651), AAAI 2019 — safe-interval/token-passing ideas for realistic motion.
13. Li et al., [Lifelong MAPF in Large-Scale Warehouses / RHCR](https://doi.org/10.1609/aaai.v35i13.17344), AAAI 2021 — rolling-horizon warehouse throughput; [code](https://github.com/Jiaoyang-Li/RHCR).
14. Chen et al., [Traffic Flow Optimisation for Lifelong MAPF](https://doi.org/10.1609/aaai.v38i18.30054), AAAI 2024 — guidance-graph congestion optimization; [code](https://github.com/lunjohnzhang/ggo_public).
15. Jiang et al., [Scaling LMAPF to More Realistic Settings](https://arxiv.org/abs/2404.16162), SoCS 2024 — research gaps in kinodynamics, execution and lifelong settings.
16. Lehoux-Lebacque et al., [MAPF with Real Robot Dynamics and Interdependent Tasks](https://arxiv.org/abs/2408.14527), 2024 **preprint** — warehouse order dependencies and dynamics-compliant trajectories.
17. Schneider et al., [Many-to-Many Multi-Agent Pickup and Delivery](https://arxiv.org/abs/2605.07835), 2026 **preprint** — multiple valid SKU pickup/drop locations.
18. Ren et al., [Dynamic MAPD in Robotic Cellular Warehousing Systems](https://arxiv.org/abs/2606.05669), 2026 **preprint** — orders changing during execution.
19. Shan et al., [Distributed MRTA for Time-Constrained Dynamic Collective Transport](https://doi.org/10.1016/j.robot.2024.104722), RAS 2024 — decentralized online auctions and schedule deviations.
20. Lee et al., [Very Large-Scale MRTA via Robot Redistribution](https://doi.org/10.1016/j.robot.2025.105126), RAS 2025 — path-aware assignment in narrow/conflict-heavy environments.

## Learning and decentralized policies

21. Damani et al., [PRIMAL2](https://arxiv.org/abs/2010.08184), 2020 — decentralized learned lifelong policy at large simulated scale.
22. Wang et al., [SCRIMP](https://arxiv.org/abs/2303.00605), AAMAS 2023 — learned communication for MAPF; [code](https://github.com/marmotlab/SCRIMP).
23. Skrynnik et al., [Learn to Follow](https://doi.org/10.1609/aaai.v38i16.29704), AAAI 2024 — hybrid A* guidance plus learned local conflict behavior; [code](https://github.com/Cognitive-AI-Systems/learn-to-follow).
24. Chen et al., [Deploying Ten Thousand Robots / SILLM](https://doi.org/10.1109/ICRA55743.2025.11127445), ICRA 2025 — scalable imitation learning with structured collision handling; [code](https://github.com/DiligentPanda/Scalable-Imitation-Learning-for-LMAPF).
25. [LNS2+RL](https://doi.org/10.1609/aaai.v39i22.34501), AAAI 2025 — hybrid MARL and neighborhood repair; [code](https://github.com/marmotlab/LNS2-RL).
26. [POGEMA benchmark paper](https://proceedings.iclr.cc/paper_files/paper/2025/hash/10d19888a94f390e58f922ab3937e1cb-Abstract-Conference.html), ICLR 2025 — unified learning/search evaluation; [code](https://github.com/Cognitive-AI-Systems/pogema).
27. [Learning-guided Prioritized Planning for LMAPF in Warehouse Automation](https://arxiv.org/abs/2603.23838), 2026 **preprint** — ML used to guide priorities rather than replace feasibility checks.
28. [Karma Mechanisms for Decentralised Cooperative MAPF](https://github.com/DerKevinRiehl/karma_dmapf), 2026 experimental artifact/**submitted work** — pairwise negotiation and long-run fairness; not yet strong authority.

## Robust execution and uncertainty

29. Hönig et al., [Persistent and Robust Execution of MAPF Schedules in Warehouses](https://doi.org/10.1109/LRA.2019.2894217), RA-L 2019 — action dependency graph execution.
30. Atzmon et al., [Robust MAPF and Executing](https://doi.org/10.1613/jair.1.11734), JAIR 2020 — delay robustness and execution.
31. [Introducing Delays in MAPF](https://doi.org/10.1609/socs.v17i1.31540), SoCS 2024 — deliberately delaying agents to repair schedules.
32. [Planning and Execution in MAPF](https://doi.org/10.1609/icaps.v34i1.31534), ICAPS 2024 — concurrent planning/execution tradeoffs.
33. Zhang et al., [Concurrent Planning and Execution for LMAPF with Delays](https://doi.org/10.1609/aaai.v39i22.34506), AAAI 2025 — delay-aware lifelong execution.
34. Liu et al., [Robust and Effective Multi-Agent Path Execution with Timing Uncertainty](https://doi.org/10.1016/j.artint.2026.104586), Artificial Intelligence 2026 — online maximal safe movement under delay.
35. Yan et al., [SMART](https://arxiv.org/abs/2503.04798), RA-L 2026 — scalable realistic kinematics/execution testbed; [project](https://jingtianyan.github.io/publication/2025-smart).
36. Yan et al., [LSMART](https://arxiv.org/abs/2602.15721), 2026 **preprint** — lifelong AGV testbed and FMS design choices; [code](https://github.com/smart-mapf/lifelong-smart).

## Distributed allocation

37. Nunes & Gini, [Multi-Robot Auctions for Tasks with Temporal Constraints](https://doi.org/10.1609/aaai.v29i1.9440), AAAI 2015 — task windows and schedule-aware bidding.
38. [Group-Based Distributed Auction Algorithms for MRTA](https://doi.org/10.1109/TASE.2022.3175040), IEEE T-ASE 2023 — capacities and time windows.
39. [Distributed MRTA via Consensus ADMM](https://doi.org/10.1109/TRO.2022.3228132), IEEE T-RO 2023 — principled one-hop distributed optimization.
40. [Decentralized Auction-Based Pickup and Delivery under Time Windows](https://doi.org/10.1109/ICUS66297.2025.11294130), IEEE ICUS 2025 — local task bundles and consensus.

## Benchmarks, frameworks and standards

41. [MovingAI MAPF benchmarks](https://movingai.com/benchmarks/mapf/) — standard warehouse/room/maze instances.
42. [League of Robot Runners](https://github.com/MAPF-Competition) — lifelong competition code and benchmarks.
43. [PyPIBT](https://github.com/Kei18/pypibt) — compact MIT-licensed Python reference.
44. [LaCAM3](https://github.com/Kei18/lacam3) — MIT-licensed high-performance solver.
45. [libMultiRobotPlanning](https://github.com/whoenig/libMultiRobotPlanning) — MIT-licensed CBS/ECBS/SIPP library.
46. [Open-RMF root](https://github.com/open-rmf/rmf) and [architecture book](https://osrf.github.io/ros2multirobotbook/rmf-core.html) — industry-grade reference and centralized schedule distinction.
47. [Nav2](https://github.com/ros-navigation/navigation2) — per-robot ROS 2 navigation and collision monitoring.
48. [Zenoh](https://github.com/eclipse-zenoh/zenoh) / [zenoh-python](https://github.com/eclipse-zenoh/zenoh-python) — edge-friendly pub/sub/query transport.
49. [VDA 5050](https://github.com/VDA5050/VDA5050) — interoperability reference between vehicles and master control; not a decentralized planner.
50. [MassRobotics AMR Interoperability Standard](https://github.com/MassRobotics-AMR/AMR_Interop_Standard) — fleet coexistence/status interoperability reference.

## Community and operational reading (anecdotal)

- [Open-RMF random U-turn investigation](https://discourse.openrobotics.org/t/random-u-turns-with-rmf/50557) — illustrates integration-layer diagnosis.
- [ROS 2 multi-robot Nav2 discussion](https://www.reddit.com/r/ROS/comments/1d5bakm) — recurring namespace/TF setup pain.
- [Open-RMF TurtleBot integration discussion](https://www.reddit.com/r/ROS/comments/1e1kr8f) — integration scope signal.
- [ROS middleware discussion](https://news.ycombinator.com/item?id=40634556) — opinionated DDS/Zenoh operational debate; not benchmark evidence.
