import pytest

from kinesis.domain import Cell, RobotState, Task
from kinesis.physics import MotionConfig


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_robot_capacity_must_be_finite(value: float) -> None:
    with pytest.raises(ValueError, match="payload_capacity_kg"):
        RobotState("R1", Cell(0, 0), 1.0, payload_capacity_kg=value)


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_task_payload_must_be_finite(value: float) -> None:
    with pytest.raises(ValueError, match="payload"):
        Task("T1", Cell(0, 0), Cell(1, 0), 0, 10, payload_kg=value)


def test_motion_loss_parameters_must_be_finite_and_nonnegative() -> None:
    with pytest.raises(ValueError, match="loss and duration"):
        MotionConfig(auxiliary_power_w=float("nan"))

    with pytest.raises(ValueError, match="loss and duration"):
        MotionConfig(turn_duration_seconds=-1.0)
