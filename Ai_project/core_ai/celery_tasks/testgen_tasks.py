"""Background work of a test job.

`advance_job` runs ONE short pass and returns: a planning pass while the plan is being built, then
one generation pass per unit. While there is more to do it puts itself back on the queue. It never
calls `.get()` on another task: a task that waits on a task can deadlock the worker.
"""
from datetime import datetime

from celery import shared_task
from celery.signals import worker_ready
from django.conf import settings

from core_ai.services.test_generation.generation import run_generation_pass
from core_ai.services.test_generation.llm_facade import LLMFacade, default_client
from core_ai.services.test_generation.readers import get_reader
from core_ai.services.test_generation.records import get_attempt_repo, get_record_repo
from core_ai.services.test_generation.repo import get_job_repo
from core_ai.services.test_generation.run_stage import RunLimits, run_sandbox_pass
from core_ai.services.test_generation.runner import run_pass
from core_ai.services.test_generation.runs import get_run_repo
from core_ai.services.test_generation.statuses import JobStage, JobStatus


def _request_analysis(file_id):
    # Imported here so that loading this module does not load the analysers.
    from core_ai.celery_tasks.analyze_task import analyze_code_file_task

    analyze_code_file_task.delay(str(file_id))  # fire and forget


@shared_task(name="core_ai.testgen.reap_expired", queue="test_sandbox", ignore_result=True)
def reap_expired_sandboxes():
    from core_ai.services.test_generation.sandbox.executor import get_executor
    get_executor().reap_expired()


@worker_ready.connect
def schedule_sandbox_cleanup(sender, **kwargs):
    if any(queue.name == "test_sandbox" for queue in sender.task_consumer.queues):
        sender.timer.call_repeatedly(300, reap_expired_sandboxes.apply_async,
                                     kwargs={"expires": 300})


@shared_task(name="core_ai.testgen.advance_job")
def advance_job(job_id):
    repo = get_job_repo()
    job = repo.get(job_id)
    if job is None or job.get("status") in JobStatus.FINAL:
        return {"job_id": job_id, "done": True}

    if job.get("stage") in (JobStage.GENERATING, JobStage.REPAIRING):
        facade = LLMFacade(
            default_client(), get_attempt_repo(),
            max_tokens=settings.TESTGEN_LLM_MAX_TOKENS,
            model=settings.TESTGEN_LLM_MODEL,
        )
        if job["stage"] == JobStage.REPAIRING:
            from core_ai.services.test_generation.repair import run_repair_pass

            result = run_repair_pass(job_id, jobs=repo, records=get_record_repo(), attempts=get_attempt_repo(),
                                     llm=facade, reader=get_reader())
        else:
            result = run_generation_pass(
                job_id, repo, get_record_repo(), get_attempt_repo(), get_reader(), facade,
                datetime.utcnow(), max_requests=settings.TESTGEN_MAX_REQUESTS_PER_JOB,
            )
        delay = 0                                   # next unit straight away
    elif job.get("records_created"):
        return {"job_id": job_id, "done": True}
    else:
        result = run_pass(
            job_id, repo, get_reader(), _request_analysis, datetime.utcnow(),
            max_wait_seconds=settings.TESTGEN_GATE_MAX_WAIT_SECONDS,
            then_generate=True, record_repo=get_record_repo(),
        )
        if (repo.get(job_id) or {}).get("stage") == JobStage.PREFLIGHT:
            sandbox_pass.delay(job_id)
            return {"job_id": job_id, "done": True, "handover": True}
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

    job = get_job_repo().get(job_id)
    if not job or job["status"] in JobStatus.FINAL:
        return {"job_id": job_id, "done": True}
    executor = get_executor()
    if job["stage"] == JobStage.PREFLIGHT:
        from redis import Redis
        from core_ai.services.test_generation.envs import get_env_repo
        from core_ai.services.test_generation.languages.base import adapter_for
        from core_ai.services.test_generation.preflight import run_preflight_pass

        envs = get_env_repo()
        envs.reap(executor, settings.TESTGEN_ENV_KEEP_DAYS, Redis.from_url(settings.CELERY_BROKER_URL))
        result = run_preflight_pass(job_id, jobs=get_job_repo(), records=get_record_repo(), envs=envs,
                                    executor=executor, reader=get_reader(), adapter=adapter_for("python"))
        if result.handover:
            advance_job.delay(job_id)
        elif not result.done:
            sandbox_pass.apply_async((job_id,), countdown=result.countdown)
        return {"job_id": job_id, "done": result.done}
    if job["stage"] not in (JobStage.SANDBOX_RUN, JobStage.FINAL_RUN, JobStage.FLAKY_CHECK):
        return {"job_id": job_id, "done": True}
    limits = RunLimits(timeout_s=settings.TESTGEN_SANDBOX_TIMEOUT_SECONDS,
                       final_max_s=settings.TESTGEN_SANDBOX_FINAL_MAX_SECONDS,
                       output_limit=settings.TESTGEN_SANDBOX_OUTPUT_LIMIT)
    result = run_sandbox_pass(job_id, get_job_repo(), get_record_repo(), get_run_repo(), get_reader(),
                              executor, datetime.utcnow(), limits)
    if not result.done:
        sandbox_pass.apply_async((job_id,), countdown=result.countdown)
    elif result.handover:
        advance_job.delay(job_id)
    return {"job_id": job_id, "done": result.done}


def enqueue_advance(job_id):
    advance_job.delay(job_id)
