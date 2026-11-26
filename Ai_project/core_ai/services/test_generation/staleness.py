"""A job whose background work never arrived must not stay "pending" forever.

Two ways a job can get stuck, both seen from the outside as "nothing changes":
  - queued : the worker never ran the first pass (worker down, or it dropped the message)
  - running: a pass re-enqueued itself and that message was lost

There is no scheduler watching jobs, so the check runs when the job is read: if it has been still
for too long it is marked failed, with an error the user can read. A pass that arrives later does
nothing, because a failed job is final.
"""
from datetime import timedelta

from core_ai.services.test_generation.statuses import JobStage, JobStatus

ERROR_CODE = "worker_unavailable"


def stale_error(job, now, queue_timeout_seconds, gate_max_wait_seconds):
    """→ an error dict when the job is stuck, else None."""
    status = job.get("status")

    if status == JobStatus.PENDING and job.get("stage") == JobStage.QUEUED:
        created = job.get("created_at")
        if created is not None and now - created > timedelta(seconds=queue_timeout_seconds):
            return {
                "code": ERROR_CODE,
                "message": "The job was never picked up by the background worker. "
                           "Check that the worker is running, then start the job again.",
            }

    if status == JobStatus.RUNNING:
        updated = job.get("updated_at")
        limit = timedelta(seconds=gate_max_wait_seconds + queue_timeout_seconds)
        if updated is not None and now - updated > limit:
            return {
                "code": ERROR_CODE,
                "message": "The job stopped making progress. "
                           "Check that the worker is running, then start the job again.",
            }

    return None


def fail_if_stale(job, repo, now, queue_timeout_seconds, gate_max_wait_seconds):
    """Marks a stuck job as failed and returns the job as it now is."""
    error = stale_error(job, now, queue_timeout_seconds, gate_max_wait_seconds)
    if error is None:
        return job
    repo.update(job["job_id"], {"status": JobStatus.FAILED, "error": error})
    return repo.get(job["job_id"]) or job
