import json

from swarmroute.domain import Cell, RobotState, Task
from swarmroute.experiment import FleetExperiment
from swarmroute.graph import WarehouseMap


def test_multi_task_experiment_is_reproducible_and_event_sourced() -> None:
    experiment = FleetExperiment(
        WarehouseMap(7, 3),
        (
            RobotState("R1", Cell(0, 1), 0.9),
            RobotState("R2", Cell(6, 1), 0.9),
        ),
    )
    tasks = (
        Task("T1", Cell(1, 1), Cell(3, 1), 0, 20, payload_kg=100),
        Task("T2", Cell(5, 1), Cell(4, 1), 1, 20, payload_kg=100),
    )

    first = experiment.run(tasks)
    second = experiment.run(tasks)

    assert first.outcomes == second.outcomes
    assert first.metrics == second.metrics
    assert first.metrics.completed_tasks == 2
    assert first.metrics.unassigned_tasks == 0
    lines = list(first.events.json_lines())
    assert len(lines) == 10
    assert [json.loads(line)["sequence"] for line in lines] == list(range(1, 11))


def test_impossible_deadline_produces_explicit_unassigned_outcome() -> None:
    result = FleetExperiment(
        WarehouseMap(10, 1),
        (RobotState("R1", Cell(0, 0), 0.9),),
    ).run((Task("urgent", Cell(8, 0), Cell(9, 0), 0, 2),))

    assert result.metrics.completed_tasks == 0
    assert result.metrics.unassigned_tasks == 1
    assert result.outcomes[0].reason == "no feasible bid"
    assert "Infinity" not in "\n".join(result.events.json_lines())
