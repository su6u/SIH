import pytest

from swarmroute.admission import AdmissionError, CellAdmission
from swarmroute.domain import Cell, RobotState


def test_target_remains_blocked_until_the_owner_confirms_exit() -> None:
    admission = CellAdmission(
        (
            RobotState("A", Cell(1, 0), 1.0),
            RobotState("B", Cell(2, 0), 1.0),
        )
    )

    admission.reserve("A", Cell(0, 0))

    assert not admission.can_enter("B", Cell(1, 0))
    admission.confirm("A", Cell(0, 0))
    assert admission.can_enter("B", Cell(1, 0))


def test_inflight_target_is_exclusive() -> None:
    admission = CellAdmission(
        (
            RobotState("A", Cell(0, 0), 1.0),
            RobotState("B", Cell(2, 0), 1.0),
        )
    )

    admission.reserve("A", Cell(1, 0))

    assert not admission.can_enter("B", Cell(1, 0))
    with pytest.raises(AdmissionError, match="not available"):
        admission.reserve("B", Cell(1, 0))


def test_nonadjacent_transition_is_rejected() -> None:
    admission = CellAdmission((RobotState("A", Cell(0, 0), 1.0),))

    with pytest.raises(AdmissionError, match="adjacent"):
        admission.reserve("A", Cell(2, 0))
