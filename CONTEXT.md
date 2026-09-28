# Kinesis domain context

Kinesis is a research platform for coordinating fleets of autonomous mobile robots
(AMRs) in warehouses. It produces reproducible evidence about allocation, routing,
traffic conflicts, timing, energy estimates, and degraded-network behaviour. It is not a
certified safety controller.

## Domain language

- **Task** — a pickup/drop-off request with release time, deadline, payload, and service time.
- **Bid** — one robot's auditable cost and feasibility result for one task and auction epoch.
- **Plan** — consecutive space-time occupancies for one robot; an edge covers the interval
  between two adjacent occupancies.
- **Reservation** — exclusive ownership of a cell at a tick or a directed transition during
  a tick interval.
- **Parking hold** — a reservation that keeps an idle or completed robot's physical cell
  occupied until it receives a replacement plan.
- **Reference scheduler** — the deterministic shared-truth implementation used as an oracle.
- **Peer** — one robot's independent process, authenticated protocol endpoint, local planner,
  and private durable state. It never owns another robot's replica.
- **Membership epoch** — a quorum-certified, removal-only view of robot IDs and boot IDs.
- **Fence token** — a monotonically ordered authority token binding a task claim to a
  membership epoch, auction epoch, and claim revision.
- **Coordinator** — the legacy centralized comparison adapter, disabled in the default mode.
- **Route executor** — the robot-local controller that tracks a timed plan using physical
  odometry and velocity commands.
- **Local safety shield** — a robot-local, fail-closed observer whose fresh approval is required
  by that robot's route executor.
- **Fleet physical monitor** — an additional independent all-robot observer and stop source.
- **Scenario** — a versioned experiment input containing map geometry, robots, and tasks.
- **Algorithm tick** — an exact discrete planning instant.
- **Simulation time** — Gazebo's ROS `/clock`; all physical nodes use it for plan timing.
- **Deterministic conflict** — a forbidden shared cell or reverse-edge traversal in a plan.
- **Physical separation violation** — measured robot distance below the configured threshold.

## Invariants

1. A committed plan has no vertex or reverse-edge conflict with another committed plan.
2. An idle robot remains reserved at its actual cell.
3. An awarded route includes a stationary reservation tail until replaced.
4. Gazebo, ROS, dashboards, and fleet protocols are adapters; domain algorithms do not import them.
5. Simulator safety results and physical-monitor results remain separate measurements.
6. A peer may originate facts only for its own authenticated identity.
7. A membership change requires a durable strict-majority proof from the predecessor view;
   timeouts provide suspicion, never authority by themselves.
8. Task completion is accepted only from the winner holding the current membership fence.
9. Restart never reuses a sender sequence or application revision, and unknown execution state
   fails stopped.
10. A route executor moves only while both odometry and its local safety heartbeat are fresh.
11. In distributed mode, a route executor also requires a fresh authority lease from its own
    peer backed by live-majority evidence; peer crash, minority partition, or membership fencing
    therefore revokes motion locally.
