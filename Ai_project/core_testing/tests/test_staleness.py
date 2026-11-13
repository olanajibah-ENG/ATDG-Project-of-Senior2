from datetime import datetime, timedelta

from core_testing.repo import new_job
from core_testing.runner import run_pass
from core_testing.staleness import fail_if_stale, stale_error

T0 = datetime(2026, 11, 13, 12, 0, 0)
QUEUE, GATE = 120, 600


def _job(repo, **fields):
    job = repo.create(new_job(user_id=7, project_id="p", version_number=1, paths=[], levels=["unit"],
                              files=[], now=T0))
    if fields:
        repo._jobs[job["job_id"]].update(fields)       # set fields without touching updated_at
    return repo.get(job["job_id"])


def _check(job, seconds):
    return stale_error(job, T0 + timedelta(seconds=seconds), QUEUE, GATE)


def test_fresh_queued_job_is_not_stale(repo):
    assert _check(_job(repo), 30) is None
    assert _check(_job(repo), QUEUE) is None           # exactly at the limit: still fine


def test_queued_job_never_picked_up_is_stale(repo):
    error = _check(_job(repo), QUEUE + 1)
    assert error["code"] == "worker_unavailable"
    assert "worker" in error["message"]


def test_running_job_that_stopped_moving_is_stale(repo):
    job = _job(repo, status="running", stage="waiting_analysis", updated_at=T0)
    assert _check(job, GATE + QUEUE) is None
    assert _check(job, GATE + QUEUE + 1)["code"] == "worker_unavailable"


def test_finished_jobs_are_never_stale(repo):
    for status in ("completed", "failed", "completed_with_issues", "cancelled"):
        job = _job(repo, status=status, stage="planned", updated_at=T0)
        assert _check(job, 10 ** 6) is None


def test_fail_if_stale_marks_the_job_failed_once(repo):
    job = _job(repo)
    late = T0 + timedelta(seconds=QUEUE + 1)
    result = fail_if_stale(job, repo, late, QUEUE, GATE)
    assert result["status"] == "failed"
    assert result["error"]["code"] == "worker_unavailable"
    assert repo.get(job["job_id"])["status"] == "failed"      # saved, not only returned
    # reading it again changes nothing
    again = fail_if_stale(repo.get(job["job_id"]), repo, late + timedelta(hours=1), QUEUE, GATE)
    assert again["error"] == result["error"]


def test_fail_if_stale_leaves_a_healthy_job_alone(repo):
    job = _job(repo)
    result = fail_if_stale(job, repo, T0 + timedelta(seconds=5), QUEUE, GATE)
    assert result["status"] == "pending" and result["error"] is None


def test_a_late_pass_does_not_revive_a_failed_job(repo, reader):
    job = _job(repo)
    fail_if_stale(job, repo, T0 + timedelta(seconds=QUEUE + 1), QUEUE, GATE)
    result = run_pass(job["job_id"], repo, reader, lambda file_id: None, T0 + timedelta(seconds=500))
    assert result.done is True
    assert repo.get(job["job_id"])["status"] == "failed"
