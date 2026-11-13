"""Background work of a test job.

`advance_job` runs ONE short pass and returns. While files still wait for their analysis it puts
itself back on the queue with a delay. It never calls `.get()` on another task: a task that waits
on a task can deadlock the worker.
"""
from datetime import datetime

from celery import shared_task
from django.conf import settings

from core_testing.readers import get_reader
from core_testing.repo import get_job_repo
from core_testing.runner import run_pass


def _request_analysis(file_id):
    # Imported here so that loading this module does not load the analysers.
    from core_ai.celery_tasks.analyze_task import analyze_code_file_task

    analyze_code_file_task.delay(str(file_id))  # fire and forget


@shared_task(name="core_testing.advance_job")
def advance_job(job_id):
    result = run_pass(
        job_id,
        get_job_repo(),
        get_reader(),
        _request_analysis,
        datetime.utcnow(),
        max_wait_seconds=settings.CORE_TESTING_GATE_MAX_WAIT_SECONDS,
    )
    if not result.done:
        advance_job.apply_async((job_id,), countdown=settings.CORE_TESTING_GATE_POLL_SECONDS)
    return {"job_id": job_id, "done": result.done}


def enqueue_advance(job_id):
    advance_job.delay(job_id)
