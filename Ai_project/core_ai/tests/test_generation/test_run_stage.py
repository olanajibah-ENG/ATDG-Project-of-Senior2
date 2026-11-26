"""S3 run stage with a scripted sandbox: one record per pass, the gate, failures, finishing the job."""
from datetime import datetime

import pytest

from core_ai.models.testgen import new_job, new_record
from core_ai.services.test_generation import acceptance, results
from core_ai.services.test_generation.records import InMemoryRecordRepo, ReadyNotAllowed
from core_ai.services.test_generation.run_stage import RunLimits, run_sandbox_pass
from core_ai.services.test_generation.statuses import Actor
from core_ai.tests.test_generation.conftest import PROJECT_ID
from core_ai.tests.test_generation.fake_sandbox import (FakeSandboxExecutor, cov_json, junit,
                                                       junit_collection_error, junit_fail)

COURSE = "class Course:\n    def __init__(self, title, capacity=2):\n        self.title = title\n        self.capacity = capacity\n"


def make_test_code(unit, n=2, body="    assert True\n"):
    stem = unit.replace(".", "_")
    tests = "".join(f"def test_{stem}__unit_{i}():\n{body}\n" for i in range(1, n + 1))
    return f"# generated\nfrom demo.course import Course\n\n{tests}"


@pytest.fixture
def setup(repo, reader, runs, monkeypatch):
    # Exercise the original S3 run in isolation. S4 scenarios enable both budgets.
    from django.conf import settings
    monkeypatch.setattr(settings, 'TESTGEN_MAX_REPAIR_ATTEMPTS', 0)
    monkeypatch.setattr(settings, 'TESTGEN_FLAKY_RERUNS', 0)
    reader.add_file("f1", "demo/course.py", content=COURSE)
    reader.add_file("f2", "demo/student.py", content="from demo.course import Course\n")
    reader.add_file("f3", "config.json", file_type="json", content="{}")
    reader.add_version(PROJECT_ID, 10, ["f1", "f2", "f3"])
    records = InMemoryRecordRepo()

    def make(units=("Course.__init__", "Course.is_full", "Course.add_student"), statuses=None):
        job = new_job(user_id=7, project_id=PROJECT_ID, version_number=10, paths=[], levels=["unit", "edge"],
                      files=[{"path": "demo/course.py", "file_id": "f1", "file_type": "python"}])
        job.update(status="running", stage="sandbox_run",
                   plan={"units": [{"id": f"demo/course.py::{u}", "file": "demo/course.py"} for u in units],
                         "skipped": [], "work_items_count": len(units) * 2})
        repo.create(job)
        made = []
        for i, unit in enumerate(units):
            for level in ("unit", "edge"):
                rec = new_record(job["job_id"], {"id": f"demo/course.py::{unit}", "file": "demo/course.py",
                                                 "body_hash": f"h{i}"}, level)
                if level == "unit":
                    status = (statuses or {}).get(unit, "generated")
                    rec.update(status=status, test_code=make_test_code(unit) if status == "generated" else None,
                               test_path=f"tests/generated/test_demo_course_{unit.replace('.', '_')}__unit.py")
                made.append(rec)
        records.create_many(made)
        return job["job_id"]

    return make, records


def run_all(job_id, repo, records, runs, reader, sandbox, passes=50):
    done = 0
    for _ in range(passes):
        done += 1
        if run_sandbox_pass(job_id, repo, records, runs, reader, sandbox, datetime.utcnow(), RunLimits()).done:
            return done
    raise AssertionError("did not finish")


def unit_record(records, job_id, unit):
    return next(r for r in records.list(job_id) if r["unit_id"].endswith(unit) and r["level"] == "unit")


# ── US1 ──────────────────────────────────────────────────────────────────────

def test_every_generated_record_runs_and_passing_ones_become_ready(setup, repo, runs, reader, sandbox):
    make, records = setup
    job_id = make()
    passes = run_all(job_id, repo, records, runs, reader, sandbox)
    assert passes == 4                                   # 3 records, then the final run (which finishes)
    unit = [r for r in records.list(job_id) if r["level"] == "unit"]
    assert {r["status"] for r in unit} == {"ready"}
    for r in unit:
        ev = r["evidence"]
        assert ev["version_number"] == 10 and ev["run_id"] == r["run_id"] and ev["tests"] == ev["passed"] == 2
        assert ev["body_hash"] == r["body_hash"] and ev["test_sha256"] == acceptance.test_sha256(r["test_code"])
        assert r["executed"] is True
    job = repo.get(job_id)
    assert (job["status"], job["stage"]) == ("completed", "final_run")
    assert job["progress"]["by_status"]["ready"] == 3


def test_edge_and_generation_failed_records_are_never_run(setup, repo, runs, reader, sandbox):
    make, records = setup
    job_id = make(statuses={"Course.is_full": "generation_failed"})
    run_all(job_id, repo, records, runs, reader, sandbox)
    assert len([s for s in sandbox.specs if "_final_" not in s.run_id and s.mode == "full"]) == 2
    assert unit_record(records, job_id, "Course.is_full")["status"] == "generation_failed"
    assert {r["status"] for r in records.list(job_id) if r["level"] == "edge"} == {"pending"}
    assert repo.get(job_id)["status"] == "completed_with_issues"


def test_one_record_per_pass_and_the_source_is_prepared_once(setup, repo, runs, reader, sandbox):
    make, records = setup
    job_id = make()
    run_sandbox_pass(job_id, repo, records, runs, reader, sandbox, datetime.utcnow())
    assert [s.mode for s in sandbox.specs] == ["collect_only", "full"] and len(sandbox.prepared) == 1
    assert repo.get(job_id)["progress"]["by_status"]["ready"] == 1
    run_all(job_id, repo, records, runs, reader, sandbox)
    assert len(sandbox.prepared) == 1 and sandbox.discarded == [f"sbx_{job_id}_src"]


def test_the_whole_version_is_given_to_the_run(setup, repo, runs, reader, sandbox):
    make, records = setup
    job_id = make(units=("Course.__init__",))
    run_all(job_id, repo, records, runs, reader, sandbox)
    _, files = sandbox.prepared[0]
    assert set(files) == {"demo/course.py", "demo/student.py", "config.json"}
    assert files["demo/course.py"] == COURSE.encode()


def test_run_spec_carries_the_test_file_and_limits(setup, repo, runs, reader, sandbox):
    make, records = setup
    job_id = make(units=("Course.__init__",))
    run_all(job_id, repo, records, runs, reader, sandbox)
    spec = sandbox.specs[1]
    assert spec.timeout_s == 90 and spec.with_coverage and spec.src_volume == f"sbx_{job_id}_src"
    assert spec.test_paths == ["tests/generated/test_demo_course_Course___init____unit.py"]
    assert set(spec.test_files) == {"pytest.ini", "generated/test_demo_course_Course___init____unit.py"}


def test_a_failing_test_is_not_ready_and_keeps_the_message(setup, repo, runs, reader, sandbox):
    make, records = setup
    job_id = make(units=("Course.__init__", "Course.is_full"))
    path = "tests/generated/test_demo_course_Course___init____unit.py"
    names = ["test_Course___init____unit_1", "test_Course___init____unit_2"]
    sandbox.script[path] = {"exit_code": 1, "junit": junit_fail(names, names[1], "AssertionError: assert 2 == '2'")}
    run_all(job_id, repo, records, runs, reader, sandbox)
    rec = unit_record(records, job_id, "Course.__init__")
    assert (rec["status"], rec["reason_code"], rec["reason_detail"]) == (
        "test_failed", "assertion", "AssertionError: assert 2 == '2'")
    assert rec["evidence"] is None and rec["executed"] is True
    assert [t["outcome"] for t in rec["run_result"]["tests"]] == ["passed", "failed"]
    assert unit_record(records, job_id, "Course.is_full")["status"] == "ready"      # the batch continues
    assert repo.get(job_id)["status"] == "completed_with_issues"


def test_a_run_that_cannot_start_is_sandbox_unavailable_and_the_next_still_runs(setup, repo, runs, reader, sandbox):
    make, records = setup
    job_id = make(units=("Course.__init__", "Course.is_full"))
    sandbox.script["tests/generated/test_demo_course_Course___init____unit.py"] = {"start_error": "no such image"}
    run_all(job_id, repo, records, runs, reader, sandbox)
    rec = unit_record(records, job_id, "Course.__init__")
    assert (rec["status"], rec["reason_code"]) == ("environment_error", "sandbox_unavailable")
    assert rec["executed"] is False
    assert unit_record(records, job_id, "Course.is_full")["status"] == "ready"


def test_engine_down_before_anything_runs(setup, repo, runs, reader):
    make, records = setup
    job_id = make()

    class Down(FakeSandboxExecutor):
        def prepare_source(self, job_id, files):
            raise ConnectionError("docker socket not found")

    run_all(job_id, repo, records, runs, reader, Down())
    unit = [r for r in records.list(job_id) if r["level"] == "unit"]
    assert {(r["status"], r["reason_code"]) for r in unit} == {("environment_error", "sandbox_unavailable")}
    assert repo.get(job_id)["status"] == "completed_with_issues"


def test_runs_are_stored_for_audit(setup, repo, runs, reader, sandbox):
    make, records = setup
    job_id = make(units=("Course.__init__",))
    run_all(job_id, repo, records, runs, reader, sandbox)
    stored = runs.list(job_id, kind="record")
    assert len(stored) == 1 and stored[0]["kind"] == "record" and stored[0]["version_number"] == 10
    assert stored[0]["verdict"]["status"] == "ready" and stored[0]["exit_code"] == 0


def test_a_ready_record_keeps_its_own_coverage_as_a_contribution(setup, repo, runs, reader, sandbox):
    make, records = setup
    job_id = make(units=("Course.__init__",))
    path = "tests/generated/test_demo_course_Course___init____unit.py"
    names = ["test_Course___init____unit_1", "test_Course___init____unit_2"]
    sandbox.script[path] = {"exit_code": 0, "junit": junit([(n, "passed", None) for n in names]),
                            "cov": cov_json({"demo/course.py": (4, [1, 2, 3, 4], [], 0, 0)})}
    run_all(job_id, repo, records, runs, reader, sandbox)
    contribution = unit_record(records, job_id, "Course.__init__")["coverage_contribution"]
    assert contribution == {"label": "this record's own run",
                            "files": [{"file": "demo/course.py", "covered_lines": [1, 2, 3, 4], "covered_branches": 0}]}


def test_long_output_is_cut_and_the_outcome_unchanged(setup, repo, runs, reader, sandbox):
    make, records = setup
    job_id = make(units=("Course.__init__",))
    path = "tests/generated/test_demo_course_Course___init____unit.py"
    names = ["test_Course___init____unit_1", "test_Course___init____unit_2"]
    sandbox.script[path] = {"exit_code": 0, "junit": junit([(n, "passed", None) for n in names]), "output": "x" * 50000}
    run_sandbox_pass(job_id, repo, records, runs, reader, sandbox, datetime.utcnow(), RunLimits(output_limit=100))
    rec = unit_record(records, job_id, "Course.__init__")
    assert rec["status"] == "ready" and len(rec["run_result"]["output"]) < 200


def test_missing_dependency_and_collection_error(setup, repo, runs, reader, sandbox):
    make, records = setup
    job_id = make(units=("Course.__init__", "Course.is_full"))
    sandbox.script["tests/generated/test_demo_course_Course___init____unit.py"] = {
        "exit_code": 2, "junit": junit_collection_error("ModuleNotFoundError: No module named 'requests'")}
    sandbox.script["tests/generated/test_demo_course_Course_is_full__unit.py"] = {
        "exit_code": 2, "junit": junit_collection_error("ModuleNotFoundError: No module named 'demo.nope'")}
    run_all(job_id, repo, records, runs, reader, sandbox)
    first = unit_record(records, job_id, "Course.__init__")
    assert (first["status"], first["reason_code"], first["reason_detail"]) == (
        "environment_error", "missing_dependency", "requests")
    second = unit_record(records, job_id, "Course.is_full")
    assert (second["status"], second["reason_code"]) == ("test_failed", "collection_error")


def test_a_job_with_nothing_generated_finishes_without_runs(setup, repo, runs, reader, sandbox):
    make, records = setup
    job_id = make(statuses={u: "generation_failed" for u in ("Course.__init__", "Course.is_full", "Course.add_student")})
    run_all(job_id, repo, records, runs, reader, sandbox)
    assert sandbox.specs == [] and repo.get(job_id)["status"] == "completed_with_issues"


# ── the gate ─────────────────────────────────────────────────────────────────

def test_collection_error_skips_full_execution(setup, repo, runs, reader, sandbox):
    make, records = setup
    job_id = make(units=("Course.__init__",))
    path = "tests/generated/test_demo_course_Course___init____unit.py"
    sandbox.script["collect_only", path] = {
        "exit_code": 2, "junit": junit_collection_error("ModuleNotFoundError: No module named 'requests'")}
    run_sandbox_pass(job_id, repo, records, runs, reader, sandbox, datetime.utcnow())
    rec = unit_record(records, job_id, "Course.__init__")
    assert rec["reason_code"] == "missing_dependency" and rec["evidence"] is None
    assert [s.mode for s in sandbox.specs] == ["collect_only"]
    assert rec["run_id"] == sandbox.specs[0].run_id


def test_record_start_backoff_recovers_without_repair(setup, repo, runs, reader, sandbox):
    make, records = setup
    job_id = make(units=("Course.__init__",))
    sandbox.start_error = "engine unavailable"
    for delay in (5, 10):
        result = run_sandbox_pass(job_id, repo, records, runs, reader, sandbox, datetime.utcnow())
        assert result.countdown == delay
        assert unit_record(records, job_id, "Course.__init__")["status"] == "generated"
    sandbox.start_error = None
    run_all(job_id, repo, records, runs, reader, sandbox)
    assert unit_record(records, job_id, "Course.__init__")["evidence"]["repaired"] is False


def test_ready_cannot_be_written_outside_the_gate():
    records = InMemoryRecordRepo()
    records.create_many([{"record_id": "t_1", "job_id": "j", "level": "unit", "status": "generated"}])
    with pytest.raises(ReadyNotAllowed):
        records.update("t_1", {"status": "ready"})
    assert records.get("t_1")["status"] == "generated"


def test_accept_refuses_a_verdict_that_is_not_a_pass():
    records = InMemoryRecordRepo()
    rec = {"record_id": "t_1", "job_id": "j", "level": "unit", "status": "generated", "test_code": "x"}
    records.create_many([rec])
    bad = results.Verdict("test_failed", "assertion", "boom")
    with pytest.raises(acceptance.NotAcceptable):
        acceptance.accept(records, rec, job={"version_number": 1}, run_id="r", verdict=bad, duration_s=0.1)
    assert records.get("t_1")["status"] == "generated"


def test_reject_clears_evidence_of_a_ready_record():
    records = InMemoryRecordRepo()
    rec = {"record_id": "t_1", "job_id": "j", "level": "unit", "status": "generated", "test_code": "x"}
    records.create_many([rec])
    ok = results.Verdict("ready", None, None, [{"name": "test_a", "outcome": "passed", "message": None}])
    acceptance.accept(records, rec, job={"version_number": 1}, run_id="r", verdict=ok, duration_s=0.1)
    assert records.get("t_1")["evidence"]["passed"] == 1
    acceptance.reject(records, rec, actor=Actor.FINAL_RUN,
                      verdict=results.Verdict("test_failed", "fails_with_others", "x"))
    after = records.get("t_1")
    assert (after["status"], after["reason_code"], after["evidence"]) == ("test_failed", "fails_with_others", None)


@pytest.mark.parametrize("junit_text", [None, "<testsuites><testcase name='x'>", "not xml"])
def test_a_missing_or_damaged_result_file_never_makes_a_record_ready(setup, repo, runs, reader, sandbox, junit_text):
    make, records = setup
    job_id = make(units=("Course.__init__",))
    sandbox.script["tests/generated/test_demo_course_Course___init____unit.py"] = {"exit_code": 0, "junit": junit_text}
    run_all(job_id, repo, records, runs, reader, sandbox)
    rec = unit_record(records, job_id, "Course.__init__")
    assert (rec["status"], rec["reason_code"], rec.get("evidence")) == ("environment_error", "no_result_file", None)
    assert repo.get(job_id)["status"] == "completed_with_issues"


# ── US3: every failure kind keeps its real reason ───────────────────────────

INIT_PATH = "tests/generated/test_demo_course_Course___init____unit.py"
INIT_NAMES = ["test_Course___init____unit_1", "test_Course___init____unit_2"]


@pytest.mark.parametrize("entry, status, reason", [
    ({"exit_code": 5, "junit": junit([])}, "test_failed", "no_tests"),
    ({"exit_code": 0, "junit": junit([(INIT_NAMES[0], "passed", None), (INIT_NAMES[1], "skipped", "why")])},
     "test_failed", "skipped_test"),
    ({"exit_code": 137, "junit": None}, "environment_error", "run_timeout"),
    ({"exit_code": None, "timed_out": True, "junit": None}, "environment_error", "run_timeout"),
])
def test_each_failure_kind_through_the_run_stage(setup, repo, runs, reader, sandbox, entry, status, reason):
    make, records = setup
    job_id = make(units=("Course.__init__",))
    sandbox.script[INIT_PATH] = entry
    run_all(job_id, repo, records, runs, reader, sandbox)
    rec = unit_record(records, job_id, "Course.__init__")
    assert (rec["status"], rec["reason_code"]) == (status, reason)
    assert rec.get("evidence") is None


# ── US4: the final run and the coverage ─────────────────────────────────────

def test_final_run_holds_exactly_the_ready_tests_with_coverage(setup, repo, runs, reader, sandbox):
    make, records = setup
    job_id = make()
    sandbox.script[INIT_PATH] = {"exit_code": 1, "junit": junit_fail(INIT_NAMES, INIT_NAMES[0], "boom")}
    run_all(job_id, repo, records, runs, reader, sandbox)
    finals = [s for s in sandbox.specs if "_final_" in s.run_id]
    assert len(finals) == 1
    final = finals[0]
    assert sorted(final.test_paths) == sorted(r["test_path"] for r in records.list(job_id, status="ready"))
    assert INIT_PATH not in final.test_paths and final.with_coverage
    assert final.timeout_s == 60 + 15 * 2
    job = repo.get(job_id)
    assert job["stage"] == "final_run" and job["final_run_id"] == final.run_id


def test_final_run_time_limit_is_capped(setup, repo, runs, reader, sandbox):
    make, records = setup
    job_id = make(units=tuple(f"Course.m{i}" for i in range(20)))
    run_all(job_id, repo, records, runs, reader, sandbox, passes=100)
    final = [s for s in sandbox.specs if "_final_" in s.run_id][0]
    assert final.timeout_s == 300


def test_a_test_failing_with_the_others_loses_ready_and_the_final_run_is_repeated(setup, repo, runs, reader, sandbox):
    make, records = setup
    job_id = make(units=("Course.__init__", "Course.is_full"))
    full = INIT_NAMES + ["test_Course_is_full__unit_1", "test_Course_is_full__unit_2"]
    sandbox.script["final"] = [
        {"exit_code": 1, "junit": junit_fail(full, INIT_NAMES[1], "AssertionError: shared state")},
        {"exit_code": 0, "junit": junit([(n, "passed", None) for n in full[2:]]),
         "cov": cov_json({"demo/course.py": (4, [1, 2, 3], [4], 2, 1)}, root="src")},
    ]
    run_all(job_id, repo, records, runs, reader, sandbox)
    rec = unit_record(records, job_id, "Course.__init__")
    assert (rec["status"], rec["reason_code"], rec["evidence"]) == ("test_failed", "fails_with_others", None)
    assert "shared state" in rec["reason_detail"]
    finals = [s for s in sandbox.specs if "_final_" in s.run_id]
    assert len(finals) == 2 and INIT_PATH not in finals[1].test_paths
    job = repo.get(job_id)
    assert job["final_run_id"] == finals[1].run_id
    assert job["coverage"]["available"] and job["coverage"]["totals"]["line_pct"] == 75.0
    assert job["coverage"]["excluded_records"] == [{"record_id": rec["record_id"], "reason": "fails_with_others"}]
    assert job["status"] == "completed_with_issues"


def test_coverage_never_comes_from_a_record_run(setup, repo, runs, reader, sandbox):
    make, records = setup
    job_id = make(units=("Course.__init__",))
    sandbox.script[INIT_PATH] = {"exit_code": 0, "junit": junit([(n, "passed", None) for n in INIT_NAMES]),
                                 "cov": cov_json({"demo/course.py": (10, list(range(1, 11)), [], 0, 0)}, root="src")}
    sandbox.script["final"] = {"exit_code": 0, "junit": junit([(n, "passed", None) for n in INIT_NAMES]),
                               "cov": cov_json({"demo/course.py": (10, [1, 2, 3, 4, 5], [6, 7, 8, 9, 10], 0, 0)},
                                               root="src")}
    run_all(job_id, repo, records, runs, reader, sandbox)
    assert repo.get(job_id)["coverage"]["totals"]["line_pct"] == 50.0


def test_no_ready_test_means_no_coverage_and_no_final_run(setup, repo, runs, reader, sandbox):
    make, records = setup
    job_id = make(units=("Course.__init__",))
    sandbox.script[INIT_PATH] = {"exit_code": 1, "junit": junit_fail(INIT_NAMES, INIT_NAMES[0], "x")}
    run_all(job_id, repo, records, runs, reader, sandbox)
    assert not [s for s in sandbox.specs if "_final_" in s.run_id]
    assert repo.get(job_id)["coverage"] == {"available": False, "reason": "no_ready_tests"}


def test_a_final_run_that_cannot_start_gives_no_coverage_and_keeps_ready(setup, repo, runs, reader, sandbox):
    make, records = setup
    job_id = make(units=("Course.__init__",))
    sandbox.script["final"] = {"start_error": "engine gone"}
    run_all(job_id, repo, records, runs, reader, sandbox)
    cov = repo.get(job_id)["coverage"]
    assert (cov["available"], cov["reason"]) == (False, "final_run_unavailable")
    assert unit_record(records, job_id, "Course.__init__")["status"] == "ready"


def test_the_final_runs_junit_is_kept_for_the_bundle(setup, repo, runs, reader, sandbox):
    make, records = setup
    job_id = make(units=("Course.__init__",))
    run_all(job_id, repo, records, runs, reader, sandbox)
    final = runs.get(repo.get(job_id)["final_run_id"])
    assert final["kind"] == "final" and "<testsuites>" in final["junit_xml"]
    assert all(r["junit_xml"] is None for r in runs.list(job_id, kind="record"))
