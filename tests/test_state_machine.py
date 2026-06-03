import pytest

from app.db.models import JobStatus
from app.worker.state_machine import ensure_transition


def test_valid_transition() -> None:
    ensure_transition(JobStatus.queued, JobStatus.downloading)


def test_invalid_transition() -> None:
    with pytest.raises(ValueError):
        ensure_transition(JobStatus.completed, JobStatus.queued)
