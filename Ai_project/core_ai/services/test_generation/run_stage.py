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
from dataclasses import dataclass, replace
from django.conf import settings
from . import flaky, snapshots

from core_ai.services.test_generation import acceptance, coverage, results
from core_ai.services.test_generation.generation import progress_from_records
from core_ai.services.test_generation.languages.base import adapter_for
from core_ai.services.test_generation.runs import new_run
from core_ai.services.test_generation.sandbox import workspace
from core_ai.services.test_generation.sandbox.executor import RunMode, RunSpec
from core_ai.services.test_generation.statuses import Actor, JobStage, JobStatus, RecordStatus, RunReason

ISSUE_STATUSES = (RecordStatus.GENERATION_FAILED, RecordStatus.TEST_FAILED, RecordStatus.ENVIRONMENT_ERROR)


@dataclass
class RunLimits:
    timeout_s: int = 60
    final_max_s: int = 300
    output_limit: int = 20000


def expected_cases(code):
    import ast
    from .validation.validator import _test_functions
    try:
        tree = ast.parse(code or "")
    except SyntaxError:
        return 0
    count = 0
    for test in _test_functions(tree):
        cases = 1
        for dec in test.decorator_list:
            if (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)
                    and dec.func.attr == "parametrize" and len(dec.args) > 1
                    and isinstance(dec.args[1], (ast.Tuple, ast.List))):
                cases *= len(dec.args[1].elts)
        count += cases
    return count


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
    issues = any(counts.get(s, 0) for s in ISSUE_STATUSES) or bool(job.get("error")) or "flaky_check_inconclusive" in (job.get("notices") or [])
    snapshot_id = None
    if job.get("final_run_id"):
        snapshot = snapshots.new_snapshot(job, partial=False)
        snapshots.get_snapshot_repo().add(snapshot)
        snapshot_id = snapshot["snapshot_id"]
    progress = progress_from_records(counts, job["plan"])
    progress["repaired"] = sum(bool((r.get("evidence") or {}).get("repaired"))
                               for r in record_repo.list(job["job_id"], status=RecordStatus.READY))
    repo.update(job["job_id"], {
        "status": JobStatus.COMPLETED_WITH_ISSUES if issues else JobStatus.COMPLETED,
        "stage": JobStage.FINAL_RUN if state.get("final_done") else JobStage.SANDBOX_RUN,
        "progress": progress, "snapshot_id": snapshot_id,
        "sandbox": dict(state, src_volume=None),
    })


def _retry_start(repo, job_id, state, operation):
    from core_ai.services.test_generation.runner import PassResult

    retry = state.get("start_retry") or {}
    count = retry["count"] if retry.get("operation") == operation else 0
    if count >= 2:
        return None
    state["start_retry"] = {"operation": operation, "count": count + 1}
    repo.update(job_id, {"sandbox": state})
    return PassResult(done=False, countdown=5 * 2 ** count)


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
            retry = _retry_start(repo, job_id, state, "prepare_source")
            if retry:
                return retry
            _sandbox_unavailable(record_repo, job_id, f"{type(exc).__name__}: {exc}")
            job["sandbox"] = state
            finish(job, repo, record_repo, executor)
            return PassResult(done=True)
        state["project_names"] = sorted(adapter.top_level_names(files))
        state["runs"] = 0
        repo.update(job_id, {"sandbox": state, "stage": JobStage.SANDBOX_RUN, "status": JobStatus.RUNNING})

    record = record_repo.next_generated(job_id)
    if record is None:
        if record_repo.next_repairable(job_id):
            repo.update(job_id, {'stage': JobStage.REPAIRING})
            return PassResult(done=True, handover=True)
        return _final_run_pass(job, state, repo, record_repo, run_repo, reader, executor, now, limits, adapter)

    state["runs"] = int(state.get("runs") or 0) + 1
    run_id = f"sbx_{job_id}_{record['record_id']}_{state['runs']}"
    spec = RunSpec(run_id=run_id, job_id=job_id, src_volume=state["src_volume"],
                   env_volume=(job.get('preflight') or {}).get('volume'),
                   test_files=workspace.record_test_files([record]),
                   test_paths=[record["test_path"]], timeout_s=min(300, max(limits.timeout_s, 30 * expected_cases(record.get("test_code")) + 30)), with_coverage=True)
    collection = replace(spec, mode=RunMode.COLLECT_ONLY, with_coverage=False, run_id=run_id + "_collect")
    output = executor.run(collection)
    if output.started and output.exit_code == 0 and not output.timed_out and not output.oom_killed:
        output = executor.run(spec)
    else:
        run_id = collection.run_id
    if not output.started:
        retry = _retry_start(repo, job_id, state, record["record_id"])
        if retry:
            return retry
    state.pop("start_retry", None)
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
        acceptance.reject(record_repo, record, verdict=verdict, run_id=run_id)
        if (record.get("attempts_used") and record["attempts_used"] >= settings.TESTGEN_MAX_REPAIR_ATTEMPTS
                and verdict.status == RecordStatus.TEST_FAILED):
            from .repair import finalize
            finalize(record_repo, dict(record, reason_code=verdict.reason))

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
    job.update(sandbox=state, final_run_id=final_run_id, coverage=report)
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
    if not ready:
        return _end_final(job, state, repo, record_repo, executor, coverage.unavailable("no_ready_tests"))

    checking = job.get("stage") == JobStage.FLAKY_CHECK
    state["final_runs"] = int(state.get("final_runs") or 0) + 1
    run_id = f"sbx_{job_id}_final_{state['final_runs']}"
    timeout = min(limits.timeout_s + 15 * len(ready), limits.final_max_s)
    spec = RunSpec(run_id=run_id, job_id=job_id, src_volume=state["src_volume"],
                   env_volume=(job.get('preflight') or {}).get('volume'),
                   test_files=workspace.record_test_files(ready), test_paths=[r["test_path"] for r in ready],
                   timeout_s=timeout, with_coverage=not checking)
    repo.update(job_id, {"stage": JobStage.FLAKY_CHECK if checking else JobStage.FINAL_RUN, "sandbox": state, "status": JobStatus.RUNNING})
    output = executor.run(spec)
    if not checking and not output.started:
        retry = _retry_start(repo, job_id, state, "final")
        if retry:
            return retry
    state.pop("start_retry", None)
    output.output = _cut(output.output, limits.output_limit)
    cases = results.parse_junit(output.junit_xml) if output.started else None
    run_repo.add(new_run(run_id=run_id, job_id=job_id, record_id=None, kind="flaky" if checking else "final",
                         version_number=job["version_number"], test_paths=spec.test_paths, output=output,
                         verdict=None, tests=[{"name": c["name"], "outcome": c["outcome"]} for c in cases or []],
                         now=now, keep_junit=True))

    if checking:
        check = job["flaky"]
        if (not cases or not output.started or output.timed_out or output.oom_killed
                or output.exit_code and all(c["outcome"] == "passed" for c in cases)):
            if not check.get("retried"):
                repo.update(job_id, {"flaky": dict(check, retried=True)})
                return PassResult(done=False, countdown=5 if not output.started else 0)
            notices = list(job.get("notices") or []) + ["flaky_check_inconclusive"]
            repo.update(job_id, {"notices": notices, "flaky": dict(check, status="inconclusive")})
            job["notices"] = notices
        else:
            check["runs"].append(run_id)
            check["retried"] = False
            if len(check["runs"]) < settings.TESTGEN_FLAKY_RERUNS:
                repo.update(job_id, {"flaky": check})
                return PassResult(done=False)
            removed = flaky.differing_records(run_repo.get(job["final_run_id"]),
                                              [run_repo.get(r) for r in check["runs"]], ready)
            check.update(status="done", removed=removed)
            for rid in removed:
                record_repo.transition(rid, RecordStatus.TEST_FAILED, Actor.FLAKY, {
                    "reason_code": "flaky", "reason_detail": "outcomes differed between runs",
                    "evidence": None, "coverage_contribution": None})
                state.setdefault("excluded", []).append([rid, "flaky"])
            state["after_flaky"] = True
            repo.update(job_id, {"flaky": check, "sandbox": state, "stage": JobStage.FINAL_RUN})
            if removed:
                return PassResult(done=False)
        return _end_final(job, state, repo, record_repo, executor, job["coverage"], job["final_run_id"])

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
            failing.append((record, bad))

    if failing:
        excluded = list(state.get("excluded") or [])
        for record, bad in failing:
            message = bad[0].get("message") or bad[0].get("text") or bad[0]["outcome"]
            acceptance.reject(record_repo, record, actor=Actor.FINAL_RUN, verdict=results.Verdict(
                RecordStatus.TEST_FAILED, RunReason.FAILS_WITH_OTHERS,
                "passed alone, failed with the other tests: " + (results._short(message) or "")))
            record_repo.update(record["record_id"], {
                "repair_closed": bool(record.get("fwo_repaired") or state.get("after_flaky")),
                "fwo_repaired": True, "run_id": run_id,
                "run_result": {"exit_code": output.exit_code, "duration_s": output.duration_s,
                               "tests": bad, "output": output.output},
            })
            excluded.append([record["record_id"], RunReason.FAILS_WITH_OTHERS])
        state["excluded"] = excluded
        repo.update(job_id, {"sandbox": state,
                             "progress": progress_from_records(record_repo.counts(job_id), job["plan"])})
        return PassResult(done=False)                  # the next pass repeats the final run without them

    if output.exit_code != 0 or any(c["outcome"] != "passed" for c in cases):
        return _end_final(job, state, repo, record_repo, executor, coverage.unavailable(
            "final_run_unavailable", "the complete suite did not exit cleanly"))
    entry_of, version_paths = _entry_finder(reader, job)
    report = coverage.job_report(
        results.reduce_coverage(output.cov_json), final_run_id=run_id, ready_count=len(ready),
        plan_ranges=coverage.skipped_ranges(job.get("plan"), entry_of), version_paths=version_paths,
        excluded=[tuple(x) for x in state.get("excluded") or [] if x[0] not in {r["record_id"] for r in ready}])
    if not state.get("after_flaky") and settings.TESTGEN_FLAKY_RERUNS:
        repo.update(job_id, {"coverage": report, "final_run_id": run_id, "stage": JobStage.FLAKY_CHECK,
                             "flaky": {"status": "running", "runs": [], "removed": []}})
        return PassResult(done=False)
    return _end_final(job, state, repo, record_repo, executor, report, final_run_id=run_id)
