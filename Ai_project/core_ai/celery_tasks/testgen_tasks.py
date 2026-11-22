"""Background work of a test job.

`advance_job` runs ONE short pass and returns: a planning pass while the plan is being built, then
one generation pass per unit. While there is more to do it puts itself back on the queue. It never
calls `.get()` on another task: a task that waits on a task can deadlock the worker.
"""
from datetime import datetime

from celery import shared_task
from django.conf import settings

from core_ai.services.test_generation.generation import run_generation_pass
from core_ai.services.test_generation.llm_facade import LLMFacade, default_client
from core_ai.services.test_generation.readers import get_reader
from core_ai.services.test_generation.records import get_attempt_repo, get_record_repo
from core_ai.services.test_generation.repo import get_job_repo
from core_ai.services.test_generation.run_stage import RunLimits, run_sandbox_pass
from core_ai.services.test_generation.runner import run_pass
from core_ai.services.test_generation.runs import get_run_repo
from core_ai.services.test_generation.statuses import JobStage


def _request_analysis(file_id):
    # Imported here so that loading this module does not load the analysers.
    from core_ai.celery_tasks.analyze_task import analyze_code_file_task

    analyze_code_file_task.delay(str(file_id))  # fire and forget


@shared_task(name="core_ai.testgen.advance_job")
def advance_job(job_id):
    repo = get_job_repo()
    job = repo.get(job_id)
    if job is None:
        return {"job_id": job_id, "done": True}

    if job.get("records_created"):
        facade = LLMFacade(
            default_client(), get_attempt_repo(),
            max_tokens=settings.TESTGEN_LLM_MAX_TOKENS,
            model=settings.TESTGEN_LLM_MODEL,
        )
        result = run_generation_pass(
            job_id, repo, get_record_repo(), get_attempt_repo(), get_reader(), facade,
            datetime.utcnow(), max_requests=settings.TESTGEN_MAX_REQUESTS_PER_JOB,
        )
        delay = 0                                   # next unit straight away
    else:
        result = run_pass(
            job_id, repo, get_reader(), _request_analysis, datetime.utcnow(),
            max_wait_seconds=settings.TESTGEN_GATE_MAX_WAIT_SECONDS,
            then_generate=True, record_repo=get_record_repo(),
        )
        handed_over = (repo.get(job_id) or {}).get("stage") == JobStage.GENERATING
        delay = 0 if handed_over else settings.TESTGEN_GATE_POLL_SECONDS

    if not result.done:
        advance_job.apply_async((job_id,), countdown=delay)
    elif getattr(result, "handover", False):
        sandbox_pass.delay(job_id)                    # S3: run what was generated (queue test_sandbox)
    return {"job_id": job_id, "done": result.done, "handover": getattr(result, "handover", False)}


@shared_task(name="core_ai.testgen.sandbox_pass")
def sandbox_pass(job_id):
    """S3: one isolated run per pass. Routed to the queue `test_sandbox` (settings.CELERY_TASK_ROUTES),
    which only the sandbox worker consumes."""
    from core_ai.services.test_generation.sandbox.executor import get_executor

    limits = RunLimits(timeout_s=settings.TESTGEN_SANDBOX_TIMEOUT_SECONDS,
                       final_max_s=settings.TESTGEN_SANDBOX_FINAL_MAX_SECONDS,
                       output_limit=settings.TESTGEN_SANDBOX_OUTPUT_LIMIT)
    result = run_sandbox_pass(job_id, get_job_repo(), get_record_repo(), get_run_repo(), get_reader(),
                              get_executor(), datetime.utcnow(), limits)
    if not result.done:
        sandbox_pass.delay(job_id)
    return {"job_id": job_id, "done": result.done}


def enqueue_advance(job_id):
    advance_job.delay(job_id)
