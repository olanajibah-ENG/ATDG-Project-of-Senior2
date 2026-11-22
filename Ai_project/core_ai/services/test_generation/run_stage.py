"""Run stage of a job (S3): ONE record per pass, in an isolated run; then the final run; then the end.

A pass:
  1. on the first pass, makes the version's files available to the runs (read-only volume);
  2. takes the next `generated` record, runs its test file, reads the verdict;
  3. the acceptance gate sets `ready` (with evidence) or the record keeps the real failure;
  4. stores the run, updates progress, and asks to be enqueued again.
When no `generated` record is left, every `ready` test runs once more, together (one final run per
pass). A test that fails there loses `ready` (fails_with_others) and the final run is repeated
without it. The job's coverage comes only from the final run in which every test passed.
"""
from dataclasses import dataclass

from core_ai.services.test_generation import acceptance, coverage, results
from core_ai.services.test_generation.generation import progress_from_records
from core_ai.services.test_generation.languages.base import adapter_for
from core_ai.services.test_generation.runs import new_run
from core_ai.services.test_generation.sandbox import workspace
from core_ai.services.test_generation.sandbox.executor import RunSpec
from core_ai.services.test_generation.statuses import JobStage, JobStatus, RecordStatus, RunReason

ISSUE_STATUSES = (RecordStatus.GENERATION_FAILED, RecordStatus.TEST_FAILED, RecordStatus.ENVIRONMENT_ERROR)


@dataclass
class RunLimits:
    timeout_s: int = 60
    final_max_s: int = 300
    output_limit: int = 20000


def _cut(text, limit):
    text = text or ""
    return text if len(text) <= limit else text[:limit] + f"\n… [cut: {len(text) - limit} more characters]"


def _sandbox_unavailable(record_repo, job_id, message):
    """The version could not be made available: every waiting record ends environment_error."""
    verdict = results.Verdict(RecordStatus.ENVIRONMENT_ERROR, RunReason.SANDBOX_UNAVAILABLE, message)
    while True:
        record = record_repo.next_generated(job_id)
        if record is None:
            return
        acceptance.reject(record_repo, record, verdict=verdict)
        record_repo.update(record["record_id"], {"executed": False})


def finish(job, repo, record_repo, executor):
    state = job.get("sandbox") or {}
    if state.get("src_volume"):
        executor.discard_source(state["src_volume"])
    counts = record_repo.counts(job["job_id"])
    issues = any(counts.get(s, 0) for s in ISSUE_STATUSES) or bool(job.get("error"))
    repo.update(job["job_id"], {
        "status": JobStatus.COMPLETED_WITH_ISSUES if issues else JobStatus.COMPLETED,
        "stage": JobStage.FINAL_RUN if state.get("final_done") else JobStage.SANDBOX_RUN,
        "progress": progress_from_records(counts, job["plan"]),
        "sandbox": dict(state, src_volume=None),
    })


def run_sandbox_pass(job_id, repo, record_repo, run_repo, reader, executor, now, limits=None):
    from core_ai.services.test_generation.runner import PassResult

    limits = limits or RunLimits()
    job = repo.get(job_id)
    if job is None or job["status"] in JobStatus.FINAL:
        return PassResult(done=True)

    state = dict(job.get("sandbox") or {})
    adapter = adapter_for("python", "x.py")

    if not state.get("src_volume"):
        files = workspace.version_files(reader, job)
        try:
            state["src_volume"] = executor.prepare_source(job_id, files)
        except Exception as exc:                       # the engine is not there: nothing can run
            _sandbox_unavailable(record_repo, job_id, f"{type(exc).__name__}: {exc}")
            job["sandbox"] = state
            finish(job, repo, record_repo, executor)
            return PassResult(done=True)
        state["project_names"] = sorted(adapter.top_level_names(files))
        state["runs"] = 0
        repo.update(job_id, {"sandbox": state, "stage": JobStage.SANDBOX_RUN, "status": JobStatus.RUNNING})

    record = record_repo.next_generated(job_id)
    if record is None:
        return _final_run_pass(job, state, repo, record_repo, run_repo, reader, executor, now, limits, adapter)

    state["runs"] = int(state.get("runs") or 0) + 1
    run_id = f"sbx_{job_id}_{record['record_id']}_{state['runs']}"
    spec = RunSpec(run_id=run_id, job_id=job_id, src_volume=state["src_volume"],
                   test_files=workspace.record_test_files([record]),
                   test_paths=[record["test_path"]], timeout_s=limits.timeout_s, with_coverage=True)
    output = executor.run(spec)
    output.output = _cut(output.output, limits.output_limit)

    verdict = results.verdict(output, adapter.expected_test_names(record.get("test_code")),
                              set(state.get("project_names") or []))
    reduced = results.reduce_coverage(output.cov_json) if verdict.acceptable else None

    run_repo.add(new_run(run_id=run_id, job_id=job_id, record_id=record["record_id"], kind="record",
                         version_number=job["version_number"], test_paths=spec.test_paths, output=output,
                         verdict=verdict, coverage=reduced, tests=verdict.tests, now=now))
    record_repo.update(record["record_id"], {
        "run_id": run_id, "executed": output.started,
        "run_result": {"exit_code": output.exit_code, "duration_s": output.duration_s,
                       "tests": verdict.tests, "output": output.output},
    })
    if verdict.acceptable:
        acceptance.accept(record_repo, record, job=job, run_id=run_id, verdict=verdict,
                          duration_s=output.duration_s, contribution=coverage.record_contribution(reduced),
                          now=now)
    else:
        acceptance.reject(record_repo, record, verdict=verdict)

    repo.update(job_id, {
        "status": JobStatus.RUNNING, "stage": JobStage.SANDBOX_RUN, "sandbox": state,
        "progress": progress_from_records(record_repo.counts(job_id), job["plan"]),
    })
    return PassResult(done=False)


# ── the final run (US4) ─────────────────────────────────────────────────────

def _entry_finder(reader, job):
    from core_ai.services.test_generation.languages.python_adapter import find_entry

    ids = {f["path"]: f["file_id"] for f in reader.files_of_version(job["project_id"], job["version_number"])}
    cache = {}

    def entry_of(path, unit_id):
        if path not in cache:
            cache[path] = reader.analysis_of(ids[path]) if path in ids else None
        analysis = cache[path]
        return find_entry(analysis, unit_id)[1] if analysis else None

    return entry_of, sorted(ids)


def _end_final(job, state, repo, record_repo, executor, report, final_run_id=None):
    from core_ai.services.test_generation.runner import PassResult

    state["final_done"] = True
    repo.update(job["job_id"], {"coverage": report, "final_run_id": final_run_id, "sandbox": state})
    job["sandbox"] = state
    finish(job, repo, record_repo, executor)
    return PassResult(done=True)


def _final_run_pass(job, state, repo, record_repo, run_repo, reader, executor, now, limits, adapter):
    from core_ai.services.test_generation.runner import PassResult

    job_id = job["job_id"]
    if state.get("final_done"):
        job["sandbox"] = state
        finish(job, repo, record_repo, executor)
        return PassResult(done=True)

    ready = [r for r in record_repo.list(job_id, status=RecordStatus.READY) if r["level"] == "unit"]
    state.setdefault("first_ready_count", len(ready))
    if not ready:
        return _end_final(job, state, repo, record_repo, executor, coverage.unavailable("no_ready_tests"))
    if int(state.get("final_runs") or 0) > int(state["first_ready_count"]):
        return _end_final(job, state, repo, record_repo, executor,
                          coverage.unavailable("final_run_unavailable", "too many repeated final runs"))

    state["final_runs"] = int(state.get("final_runs") or 0) + 1
    run_id = f"sbx_{job_id}_final_{state['final_runs']}"
    timeout = min(limits.timeout_s + 15 * len(ready), limits.final_max_s)
    spec = RunSpec(run_id=run_id, job_id=job_id, src_volume=state["src_volume"],
                   test_files=workspace.record_test_files(ready), test_paths=[r["test_path"] for r in ready],
                   timeout_s=timeout, with_coverage=True)
    repo.update(job_id, {"stage": JobStage.FINAL_RUN, "sandbox": state, "status": JobStatus.RUNNING})
    output = executor.run(spec)
    output.output = _cut(output.output, limits.output_limit)
    cases = results.parse_junit(output.junit_xml) if output.started else None
    run_repo.add(new_run(run_id=run_id, job_id=job_id, record_id=None, kind="final",
                         version_number=job["version_number"], test_paths=spec.test_paths, output=output,
                         verdict=None, tests=[{"name": c["name"], "outcome": c["outcome"]} for c in cases or []],
                         now=now, keep_junit=True))

    if not output.started or output.timed_out or cases is None:
        why = output.start_error or ("the final run reached its time limit" if output.timed_out
                                     else "the final run left no readable result file")
        return _end_final(job, state, repo, record_repo, executor, coverage.unavailable("final_run_unavailable", why))

    outcome = {}
    for case in cases:
        outcome.setdefault(results._base_name(case["name"]), []).append(case)
    failing = []
    for record in ready:
        names = adapter.expected_test_names(record.get("test_code"))
        missing = [{"outcome": "missing", "message": "did not run in the final run"}]
        bad = [c for n in names for c in outcome.get(n, missing) if c["outcome"] != "passed"]
        if bad:
            failing.append((record, bad[0].get("message") or bad[0].get("text") or bad[0]["outcome"]))

    if failing:
        excluded = list(state.get("excluded") or [])
        for record, message in failing:
            acceptance.reject(record_repo, record, verdict=results.Verdict(
                RecordStatus.TEST_FAILED, RunReason.FAILS_WITH_OTHERS,
                "passed alone, failed with the other tests: " + (results._short(message) or "")))
            excluded.append([record["record_id"], RunReason.FAILS_WITH_OTHERS])
        state["excluded"] = excluded
        repo.update(job_id, {"sandbox": state,
                             "progress": progress_from_records(record_repo.counts(job_id), job["plan"])})
        return PassResult(done=False)                  # the next pass repeats the final run without them

    entry_of, version_paths = _entry_finder(reader, job)
    report = coverage.job_report(
        results.reduce_coverage(output.cov_json), final_run_id=run_id, ready_count=len(ready),
        plan_ranges=coverage.skipped_ranges(job.get("plan"), entry_of), version_paths=version_paths,
        excluded=[tuple(x) for x in state.get("excluded") or []])
    return _end_final(job, state, repo, record_repo, executor, report, final_run_id=run_id)
