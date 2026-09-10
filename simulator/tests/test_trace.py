from kinesis.domain import Cell, RobotState, Task
from kinesis.fleet import FleetSimulation, SimulationConfig
from kinesis.graph import WarehouseMap
from kinesis.operations import Intervention, InterventionKind
from kinesis.scenario import Scenario
from kinesis.trace import TraceMetadata, build_presentation_trace


def test_presentation_trace_is_derived_from_authoritative_events() -> None:
    warehouse = WarehouseMap(4, 2, version="M1")
    robots = (
        RobotState("R1", Cell(0, 0), 1.0),
        RobotState("R2", Cell(0, 1), 1.0),
    )
    task = Task("T1", Cell(1, 0), Cell(3, 0), 0, 12, service_ticks=0)
    failure = Intervention(
        "failure-r1", 1, InterventionKind.ROBOT_FAILURE, robot_id="R1"
    )
    scenario = Scenario("trace", warehouse, robots, (task,), 7)
    result = FleetSimulation(
        warehouse,
        robots,
        config=SimulationConfig(max_ticks=12, planning_horizon_ticks=12),
    ).run(scenario.tasks, (failure,))

    trace = build_presentation_trace(
        scenario,
        result,
        TraceMetadata("failure", "Failure", "Re-auction", "failure"),
        origin=(0.0, 0.0),
        resolution=1.0,
        duration=12,
        interventions=(failure,),
    )

    assert trace["evidence"]["source"] == "kinesis.FleetSimulation"
    assert trace["summary"]["completed"] == 1
    assert trace["summary"]["conflicts"] == 0
    r1 = next(robot for robot in trace["robots"] if robot["id"] == "R1")
    assert r1["frames"][1]["status"] == "safe-stop"
    assert all(frame["status"] == "safe-stop" for frame in r1["frames"][1:])
    assert trace["incidents"][0]["type"] == "robot_failure"
    exported_kinds = {event["kind"] for event in trace["events"]}
    assert "robot_safe_stopped" in exported_kinds
    assert "task_requeued" in exported_kinds


def test_trace_positions_match_every_robot_move_event() -> None:
    warehouse = WarehouseMap(3, 1, version="M1")
    robot = RobotState("R1", Cell(0, 0), 1.0)
    task = Task("T1", Cell(0, 0), Cell(2, 0), 0, 5, service_ticks=0)
    scenario = Scenario("trace", warehouse, (robot,), (task,), 7)
    result = FleetSimulation(
        warehouse,
        (robot,),
        config=SimulationConfig(max_ticks=5, planning_horizon_ticks=5),
    ).run((task,))

    trace = build_presentation_trace(
        scenario,
        result,
        TraceMetadata("normal", "Normal", "", "normal"),
        origin=(10.0, -4.0),
        resolution=1.5,
        duration=5,
    )

    frames = trace["robots"][0]["frames"]
    for event in result.events.events:
        if event.kind != "robot_moved":
            continue
        target = event.data["to"]
        assert frames[event.tick]["x"] == 10.0 + target["x"] * 1.5
        assert frames[event.tick]["z"] == -(-4.0 + target["y"] * 1.5)
