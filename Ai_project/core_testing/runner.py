"""One pass of a job: gate → graph → plan. Short, idempotent, and it never waits on anything.

The Celery task calls `run_pass` and re-enqueues itself while `done` is False. Everything the pass
needs is passed in, so the same code runs in tests with in-memory storage and no Celery.
"""
from dataclasses import dataclass
from datetime import timedelta

from core_testing import gate, planner
from core_testing.graphify import loader, merge, resolver
from core_testing.languages.python_adapter import is_python
from core_testing.statuses import RECORD_STATUSES, FileStatus, JobStage, JobStatus, Level, SkipReason


@dataclass
class PassResult:
    done: bool


def _progress(plan):
    by_status = {name: 0 for name in RECORD_STATUSES}
    by_status["pending"] = plan["work_items_count"]
    by_status["skipped"] = len(plan["skipped"])
    return {"total": plan["work_items_count"], "done": 0, "by_status": by_status}


def run_pass(job_id, repo, reader, request_analysis, now, max_wait_seconds=600,
             then_generate=False, record_repo=None):
    """`then_generate=False` is the S1 behaviour: planning ends the job (completed / planned).
    With `then_generate=True` and the unit level requested, planning instead creates the records
    and leaves the job running, in stage `generating`, for the generation phase."""
    job = repo.get(job_id)
    if job is None or job["status"] in JobStatus.FINAL:
        return PassResult(done=True)

    gate_state = dict(job.get("gate") or {})
    if gate_state.get("deadline_at") is None:
        gate_state["deadline_at"] = now + timedelta(seconds=max_wait_seconds)
    gate_state["passes"] = int(gate_state.get("passes") or 0) + 1
    deadline = gate_state["deadline_at"]

    files = job["files"]
    ready, skipped_files, waiting = [], [], 0
    python_total = 0

    for entry in files:
        python = is_python(entry.get("file_type"), entry.get("path"))
        python_total += 1 if python else 0
        decision = gate.decide(
            is_python=python,
            file_state=reader.file_state(entry["file_id"]) if python else {},
            analysis_requests=int(entry.get("analysis_requests") or 0),
            requested_at=entry.get("requested_at"),
            now=now,
            deadline=deadline,
        )
        if decision.action == gate.READY:
            analysis = reader.analysis_of(entry["file_id"])
            if analysis is None:
                decision = gate.Decision(gate.SKIP, SkipReason.ANALYSIS_FAILED)
            else:
                entry["status"], entry["reason"] = FileStatus.PENDING, None
                ready.append((entry["path"], analysis))
                continue
        if decision.action == gate.REQUEST:
            request_analysis(entry["file_id"])
            entry["analysis_requests"] = int(entry.get("analysis_requests") or 0) + 1
            entry["requested_at"] = now
            entry["status"], entry["reason"] = FileStatus.PENDING, None
            waiting += 1
        elif decision.action == gate.WAIT:
            entry["status"], entry["reason"] = FileStatus.PENDING, None
            waiting += 1
        else:  # SKIP
            entry["status"], entry["reason"] = FileStatus.SKIPPED, decision.reason
            skipped_files.append({"path": entry["path"], "reason": decision.reason})

    file_graphs = [loader.load_file(path, analysis) for path, analysis in ready]
    project_graph = resolver.resolve_calls(merge.merge(file_graphs), file_graphs)
    plan, no_unit_paths = planner.build_plan(ready, skipped_files, job["levels"], project_graph)
    for entry in files:
        if entry["path"] in no_unit_paths:
            entry["status"], entry["reason"] = FileStatus.SKIPPED, SkipReason.NO_UNITS

    fields = {"files": files, "plan": plan, "progress": _progress(plan), "gate": gate_state}
    if waiting:
        fields.update(status=JobStatus.RUNNING, stage=JobStage.WAITING_ANALYSIS, error=None)
        done = False
    elif python_total and not ready:
        fields.update(
            status=JobStatus.FAILED, stage=JobStage.PLANNED,
            error={"code": "analysis_failed", "message": "No selected Python file could be analysed."},
        )
        done = True
    elif then_generate and Level.UNIT in job["levels"] and plan["units"]:
        from core_testing import generation

        job["plan"] = plan
        if not job.get("records_created"):
            generation.create_records(job, record_repo)
        fields.update(
            status=JobStatus.RUNNING, stage=JobStage.GENERATING, error=None,
            records_created=True, llm_requests=int(job.get("llm_requests") or 0),
            progress=generation.progress_from_records(record_repo.counts(job_id), plan),
        )
        done = False
    else:
        fields.update(status=JobStatus.COMPLETED, stage=JobStage.PLANNED, error=None)
        done = True

    repo.update(job_id, fields)
    return PassResult(done=done)
