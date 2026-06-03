from __future__ import annotations

from app.db.models import JobStatus


ALLOWED_TRANSITIONS: dict[JobStatus, set[JobStatus]] = {
    JobStatus.queued: {JobStatus.downloading, JobStatus.paused, JobStatus.cancelled},
    JobStatus.downloading: {JobStatus.paused, JobStatus.completed, JobStatus.failed, JobStatus.cancelled},
    JobStatus.paused: {JobStatus.queued, JobStatus.cancelled},
    JobStatus.completed: set(),
    JobStatus.failed: {JobStatus.queued, JobStatus.cancelled},
    JobStatus.cancelled: set(),
}


def ensure_transition(current_status: JobStatus, next_status: JobStatus) -> None:
    if next_status == current_status:
        return
    allowed = ALLOWED_TRANSITIONS[current_status]
    if next_status not in allowed:
        raise ValueError(f"Invalid transition from {current_status.value} to {next_status.value}")
