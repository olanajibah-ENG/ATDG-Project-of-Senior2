"""Generation phase of a job: ONE unit per pass.

A pass picks the next pending `unit` record, builds its context, gets an answer (an earlier one
when the same context was already answered, otherwise one model request), checks the answer
without running it, and stores the outcome. Then the task re-enqueues itself.

A pass never loops over all units: a model request can take minutes, and one unit per pass keeps
tasks short, shows progress after every unit, and loses at most one unit if the worker stops.

Nothing here can set a record to `ready`.
"""
from core_ai.services.test_generation import assembler
from core_ai.services.test_generation.languages.base import adapter_for
from core_ai.services.test_generation.languages.python_adapter import is_python, split_unit_id
from core_ai.services.test_generation.llm_facade import ModelUnavailable
from core_ai.services.test_generation.records import new_record
from core_ai.services.test_generation.runner import PassResult
from core_ai.services.test_generation.statuses import JobStage, JobStatus, Level, RecordStatus, StopReason
from core_ai.services.test_generation.strategies.unit import UnitStrategy
from core_ai.services.test_generation.validation import validator

STOP_MESSAGES = {
    StopReason.MODEL_UNAVAILABLE:
        "The language model could not be reached or its quota is used up. Tests already generated "
        "are kept; the rest are still pending. Start a new job later to continue.",
    StopReason.REQUEST_LIMIT_REACHED:
        "This job reached its limit of model requests. Tests already generated are kept; the rest "
        "are still pending. Start a new job to continue.",
}


def create_records(job, record_repo):
    """One record per (planned unit, requested level), in plan order."""
    records = [new_record(job["job_id"], unit, level)
               for unit in job["plan"]["units"] for level in job["levels"]]
    record_repo.create_many(records)
    return len(records)


def progress_from_records(counts, plan):
    total = sum(counts.values())
    by_status = dict(counts)
    by_status["skipped"] = by_status.get("skipped", 0) + len(plan.get("skipped") or [])
    return {"total": total, "done": total - counts.get(RecordStatus.PENDING, 0), "by_status": by_status}


def _analyses_for(unit, job, reader):
    """Stored analysis of the unit's file and of its callees' files, by path."""
    file_ids = {f["path"]: f["file_id"] for f in job["files"]}
    paths = {unit["file"]} | {split_unit_id(c)[0] for c in unit.get("callees") or []}
    out = {}
    for path in paths:
        if path in file_ids:
            analysis = reader.analysis_of(file_ids[path])
            if analysis is not None:
                out[path] = analysis
    return out


def _finish(job, repo, record_repo, *, stop_reason=None):
    counts = record_repo.counts(job["job_id"])
    fields = {"progress": progress_from_records(counts, job["plan"]), "stage": JobStage.GENERATED}
    if stop_reason:
        fields.update(status=JobStatus.COMPLETED_WITH_ISSUES,
                      error={"code": stop_reason, "message": STOP_MESSAGES[stop_reason]})
    elif counts.get(RecordStatus.GENERATION_FAILED, 0):
        fields.update(status=JobStatus.COMPLETED_WITH_ISSUES, error=None)
    else:
        fields.update(status=JobStatus.COMPLETED, error=None)
    repo.update(job["job_id"], fields)
    return PassResult(done=True)


def run_generation_pass(job_id, repo, record_repo, attempt_repo, reader, llm, now, *,
                        max_requests=20, strategy=None):
    job = repo.get(job_id)
    if job is None or job["status"] in JobStatus.FINAL:
        return PassResult(done=True)

    strategy = strategy or UnitStrategy()
    record = record_repo.next_pending(job_id, Level.UNIT)
    if record is None:
        return _finish(job, repo, record_repo)

    unit = next((u for u in job["plan"]["units"] if u["id"] == record["unit_id"]), None)
    adapter = adapter_for("python", record["file"])
    context = strategy.build_context(unit, _analyses_for(unit, job, reader), adapter) if unit else None

    if context is None:
        record_repo.update(record["record_id"], {
            "status": RecordStatus.GENERATION_FAILED, "reason_code": "no_code",
            "reason_detail": "the unit's stored details could not be found, so nothing was asked",
        })
    else:
        system, user = strategy.build_prompt(context, adapter)
        request_hash = strategy.request_hash(context)
        common = dict(job_id=job_id, record_id=record["record_id"], unit_id=record["unit_id"],
                      level=Level.UNIT, purpose="generate", request_hash=request_hash,
                      prompt_version=strategy.prompt_version)

        earlier = attempt_repo.find_reusable(request_hash)
        if earlier is not None and validator.looks_cut_off(earlier.get("answer_text")):
            earlier = None          # that answer was cut off mid-file: it is worth asking again
        if earlier is not None:
            result = llm.reuse(earlier, **common)
        else:
            spent = int(job.get("llm_requests") or 0)
            if spent >= max_requests:
                return _finish(job, repo, record_repo, stop_reason=StopReason.REQUEST_LIMIT_REACHED)
            try:
                result = llm.complete(system=system, user=user, **common)
            except ModelUnavailable:
                # Nothing is wrong with the unit: it stays pending and the job stops here.
                return _finish(job, repo, record_repo, stop_reason=StopReason.MODEL_UNAVAILABLE)
            repo.update(job_id, {"llm_requests": spent + 1})

        python_paths = [f["path"] for f in job["files"] if is_python(f.get("file_type"), f.get("path"))]
        checked = validator.validate(result.text, unit_id=record["unit_id"], level=Level.UNIT,
                                     allowed_roots=adapter.allowed_import_roots(python_paths))
        attempt_repo.set_validation(result.attempt_id, checked.as_dict())

        fields = {"model": result.model, "prompt_version": strategy.prompt_version, "reused": result.reused}
        if checked.ok:
            fields.update(
                status=RecordStatus.GENERATED, reason_code=None, reason_detail=None,
                test_path=assembler.test_path(record["unit_id"], Level.UNIT),
                test_code=assembler.assemble(checked.code, unit_id=record["unit_id"],
                                             body_hash=record.get("body_hash"), job_id=job_id),
            )
        else:
            fields.update(status=RecordStatus.GENERATION_FAILED, reason_code=checked.reason_code,
                          reason_detail=checked.reason_detail)
        record_repo.update(record["record_id"], fields)

    repo.update(job_id, {
        "status": JobStatus.RUNNING, "stage": JobStage.GENERATING,
        "progress": progress_from_records(record_repo.counts(job_id), job["plan"]),
    })
    return PassResult(done=False)
