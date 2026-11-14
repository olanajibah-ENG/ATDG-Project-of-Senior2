"""Background work of a test job.

`advance_job` runs ONE short pass and returns: a planning pass while the plan is being built, then
one generation pass per unit. While there is more to do it puts itself back on the queue. It never
calls `.get()` on another task: a task that waits on a task can deadlock the worker.
"""
from datetime import datetime

from celery import shared_task
from django.conf import settings

from core_testing.generation import run_generation_pass
from core_testing.llm_facade import LLMFacade, default_client
from core_testing.readers import get_reader
from core_testing.records import get_attempt_repo, get_record_repo
from core_testing.repo import get_job_repo
from core_testing.runner import run_pass
from core_testing.statuses import JobStage


def _request_analysis(file_id):
    # Imported here so that loading this module does not load the analysers.
    from core_ai.celery_tasks.analyze_task import analyze_code_file_task

    analyze_code_file_task.delay(str(file_id))  # fire and forget


@shared_task(name="core_testing.advance_job")
def advance_job(job_id):
    repo = get_job_repo()
    job = repo.get(job_id)
    if job is None:
        return {"job_id": job_id, "done": True}

    if job.get("records_created"):
        facade = LLMFacade(
            default_client(), get_attempt_repo(),
            max_tokens=settings.CORE_TESTING_LLM_MAX_TOKENS,
            model=settings.CORE_TESTING_LLM_MODEL,
        )
        result = run_generation_pass(
            job_id, repo, get_record_repo(), get_attempt_repo(), get_reader(), facade,
            datetime.utcnow(), max_requests=settings.CORE_TESTING_MAX_REQUESTS_PER_JOB,
        )
        delay = 0                                   # next unit straight away
    else:
        result = run_pass(
            job_id, repo, get_reader(), _request_analysis, datetime.utcnow(),
            max_wait_seconds=settings.CORE_TESTING_GATE_MAX_WAIT_SECONDS,
            then_generate=True, record_repo=get_record_repo(),
        )
        handed_over = (repo.get(job_id) or {}).get("stage") == JobStage.GENERATING
        delay = 0 if handed_over else settings.CORE_TESTING_GATE_POLL_SECONDS

    if not result.done:
        advance_job.apply_async((job_id,), countdown=delay)
    return {"job_id": job_id, "done": result.done}


def enqueue_advance(job_id):
    advance_job.delay(job_id)
