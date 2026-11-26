from datetime import datetime

import pytest

from core_ai.models.testgen import new_record
from core_ai.services.test_generation import generation, preflight, repair
from core_ai.services.test_generation.languages.base import adapter_for
from core_ai.services.test_generation.llm_facade import LLMFacade
from core_ai.services.test_generation.run_stage import run_sandbox_pass
from core_ai.services.test_generation.sandbox.executor import InstallOutput
from core_ai.services.test_generation.validation.repair_guards import check
from .fake_sandbox import junit_fail
from .helpers import build_analysis

CODE = "def value():\n    return 1\n"
TEST = "from example import value\n\ndef test_value():\n    assert value() == 1\n"
FIX = "VERDICT: fix_test\nREASON: correct expected result\n```python\n" + TEST + "```"


@pytest.fixture
def job(repo, reader, records):
    from core_ai.models.testgen import new_job
    file = dict(path="example.py", file_id="src", file_type="python")
    analysis = build_analysis(CODE)
    reader.add_file("src", file["path"], analysis=analysis, content=CODE)
    reader.add_version("project", 1, ["src"])
    j = new_job(user_id=1, project_id="project", version_number=1, paths=[], levels=["unit"], files=[file])
    unit = adapter_for("python").list_units("example.py", analysis)[0][0]
    j.update(status="running", stage="preflight", plan={"units": [unit], "skipped": []}, records_created=True)
    repo.create(j)
    records.create_many([new_record(j["job_id"], unit, "unit")])
    return j["job_id"]


def start_generation(job, repo, reader, records, attempts, sandbox):
    preflight.run_preflight_pass(job, jobs=repo, records=records, reader=reader, envs=None,
                                 executor=sandbox, adapter=adapter_for("python"))
    assert repo.get(job)["preflight"]["status"] == "skipped"
    model = lambda *args, **kwargs: {"text": TEST.replace("== 1", "== 0")}
    for _ in range(2):
        generation.run_generation_pass(job, repo, records, attempts, reader, LLMFacade(model, attempts), datetime.utcnow())
    rec = records.list(job)[0]
    name = adapter_for("python").expected_test_names(rec["test_code"])[0]
    sandbox.script[rec["test_path"]] = [{"exit_code": 1, "junit": junit_fail([name], name, "AssertionError")}]
    return rec, name


@pytest.mark.parametrize("reply,reason", [(FIX, None),
    ("VERDICT: suspect_code\nLOCATION: example.py:2\nEXPECTED: zero\nEXPLANATION: returns one", "suspected_code_bug"),
    ("VERDICT: fix_test\nREASON: repeat\n```python\n" + TEST.replace("== 1", "== 0") + "```", "assertion"),
    ("malformed", "assertion")])
def test_job_through_repair_and_final_run(job, repo, reader, records, attempts, runs, sandbox, snapshots_repo, reply, reason):
    rec, _ = start_generation(job, repo, reader, records, attempts, sandbox)
    for _ in range(20):
        j = repo.get(job)
        if j["status"].startswith("completed"):
            break
        if j["stage"] == "repairing":
            model = lambda *args, **kwargs: {"text": reply}
            repair.run_repair_pass(job, jobs=repo, records=records, attempts=attempts, reader=reader,
                                   llm=LLMFacade(model, attempts))
        else:
            run_sandbox_pass(job, repo, records, runs, reader, sandbox, datetime.utcnow())
    j = repo.get(job)
    record = records.get(rec["record_id"])
    assert j["status"] == ("completed_with_issues" if reason else "completed")
    assert record["reason_code"] == reason
    assert record["attempts_used"] == (2 if reply == "malformed" else 1)
    if reply == "malformed":
        repairs = [a for a in attempts.list(job) if a["purpose"] == "repair"]
        assert len({a["request_hash"] for a in repairs}) == 2
        assert all(not a["reused"] for a in repairs)
        assert record["attempts"][-1]["rejection"]["rule"] == "invalid_repair_format"
    assert all(a["repair_of"] for a in attempts.list(job) if a["purpose"] == "repair")
    if not reason:
        assert record["evidence"]["repaired"] and record["evidence"]["attempt"] == 2
        assert len(j["flaky"]["runs"]) == 2
        assert snapshots_repo.get(job)["final_run_id"] == j["final_run_id"]
    else:
        assert snapshots_repo.get(job) is None


def test_flaky_test_is_removed(job, repo, reader, records, attempts, runs, sandbox, snapshots_repo):
    rec, name = start_generation(job, repo, reader, records, attempts, sandbox)
    sandbox.script.clear()
    sandbox.script["final"] = [None, {"exit_code": 1, "junit": junit_fail([name], name, "unstable")}, None]
    for _ in range(8):
        if run_sandbox_pass(job, repo, records, runs, reader, sandbox, datetime.utcnow()).done:
            break
    assert records.get(rec["record_id"])["reason_code"] == "flaky"
    assert repo.get(job)["coverage"]["reason"] == "no_ready_tests"
    assert snapshots_repo.get(job) is None


def test_preflight_propagates_missing_import():
    deps = preflight.required_imports({"pkg/a.py": b"from .b import run", "pkg/b.py": b"import requests",
                                       "clean.py": b"import sys"})
    assert deps == {"pkg/a.py": {"requests"}, "pkg/b.py": {"requests"}, "clean.py": set()}


def test_manifests_prefer_base_and_drop_options():
    text, warnings = adapter_for("python").install_spec({"requirements/base.txt": b"six\n--index-url https://example.org",
                                                       "requirements/local.txt": b"other"})
    assert text == "six" and len(warnings) == 2


@pytest.mark.parametrize("code,rule", [(TEST.replace("value()", "other()"), "unit_not_called"),
    (TEST + "pytest.skip()", "skip_marker"), (TEST + "try:\n    value()\nexcept Exception:\n    pass", "swallowed_failure"),
    (TEST + "mock.patch('example.value')", "mocks_unit"), (TEST + "pytest.raises(Exception)", "generic_raises")])
def test_repair_guards(code, rule):
    assert check(TEST, code, "value", None).rule == rule


@pytest.mark.parametrize("missing,code", [(True, "missing_dependency"), (False, "install_failed")])
def test_failed_install_precedes_generation(job, repo, reader, records, sandbox, monkeypatch, missing, code):
    from core_ai.services.test_generation.envs import InMemoryEnvRepo
    reader.add_file("manifest", "requirements.txt", file_type="support", content="absent==1")
    reader.add_version("project", 1, ["src", "manifest"])
    monkeypatch.setattr(sandbox, "install", lambda req: InstallOutput(False, missing=missing, output="pip failed"), raising=False)
    envs = InMemoryEnvRepo()
    result = preflight.run_preflight_pass(job, jobs=repo, reader=reader, records=records, envs=envs,
                                         executor=sandbox, adapter=adapter_for("python"))
    assert result.done and not result.handover
    assert records.list(job)[0]["reason_code"] == code
    assert repo.get(job)["status"] == "failed" and not repo.get(job).get("llm_requests")
    assert envs.get(repo.get(job)["preflight"]["env_key"])["status"] == "failed"


def test_temporary_install_failure_is_retried_and_cached(job, repo, reader, records, sandbox, monkeypatch):
    from core_ai.services.test_generation.envs import InMemoryEnvRepo
    reader.add_file("manifest", "requirements.txt", file_type="support", content="six")
    reader.add_version("project", 1, ["src", "manifest"])
    outputs = iter([InstallOutput(False, temporary=True), InstallOutput(True, volume="env")])
    monkeypatch.setattr(sandbox, "install", lambda req: next(outputs), raising=False)
    args = dict(jobs=repo, reader=reader, records=records, envs=InMemoryEnvRepo(),
                executor=sandbox, adapter=adapter_for("python"))
    assert preflight.run_preflight_pass(job, **args).countdown == 30
    assert preflight.run_preflight_pass(job, **args).handover
    assert repo.get(job)["preflight"]["install_tries"] == 2
    assert repo.get(job)["preflight"]["status"] == "installed"
    assert preflight.run_preflight_pass(job, **args).handover
    assert repo.get(job)["preflight"]["status"] == "reused"


def test_unavailable_flaky_runs_retry_once(job, repo, reader, records, attempts, runs, sandbox, snapshots_repo):
    start_generation(job, repo, reader, records, attempts, sandbox)
    sandbox.script.clear()
    sandbox.script["final"] = [None, {"start_error": "down"}, {"start_error": "down"}]
    for _ in range(8):
        if run_sandbox_pass(job, repo, records, runs, reader, sandbox, datetime.utcnow()).done:
            break
    j = repo.get(job)
    assert j["flaky"]["status"] == "inconclusive" and j["status"] == "completed_with_issues"
    assert j["notices"] == ["flaky_check_inconclusive"]
    assert records.list(job)[0]["status"] == "ready"
    assert snapshots_repo.get(job)["final_run_id"] == j["final_run_id"]


def test_exhausted_job_keeps_the_failure_without_requesting_repair(job, repo, reader, records, attempts, runs, sandbox):
    from django.conf import settings
    start_generation(job, repo, reader, records, attempts, sandbox)
    for _ in range(2):
        run_sandbox_pass(job, repo, records, runs, reader, sandbox, datetime.utcnow())
    repo.update(job, {"llm_requests": settings.TESTGEN_MAX_REQUESTS_PER_JOB})
    assert repair.run_repair_pass(job, jobs=repo, records=records, attempts=attempts, reader=reader, llm=None).handover
    rec = records.list(job)[0]
    assert (rec["status"], rec["reason_code"], rec["reason_detail"]) == ("test_failed", "repair_budget_exhausted", "assertion")


@pytest.mark.parametrize("reason,final_status", [
    ("collection_error", "generation_failed"), ("no_tests", "generation_failed"),
    ("syntax_error", "generation_failed"), ("forbidden_import", "generation_failed"),
    ("weak_test", "generation_failed"), ("assertion", "test_failed"), ("timeout", "test_failed"),
    ("skipped_test", "test_failed"), ("fails_with_others", "test_failed")])
def test_final_cause_after_repair_attempts(records, reason, final_status):
    from .helpers import put_record
    source = "generation_failed" if reason in ("syntax_error", "forbidden_import", "weak_test") else "test_failed"
    rid = put_record(records, status=source, attempts_used=2, reason_code=reason)
    repair.finalize(records, records.get(rid))
    result = records.get(rid)
    assert (result["status"], result["reason_code"], result["repair_closed"]) == (final_status, reason, True)


@pytest.mark.parametrize("stale,tries", [(False, 0), (True, 1)])
def test_preflight_waits_for_live_owner_and_recovers_stale_claim(job, repo, reader, records, sandbox, stale, tries):
    from datetime import timedelta
    from core_ai.services.test_generation.envs import InMemoryEnvRepo
    reader.add_file("manifest", "requirements.txt", file_type="support", content="six")
    reader.add_version("project", 1, ["src", "manifest"])
    envs = InMemoryEnvRepo()
    args = dict(jobs=repo, reader=reader, records=records, envs=envs, executor=sandbox, adapter=adapter_for("python"))
    preflight.run_preflight_pass(job, **args)
    key = repo.get(job)["preflight"]["env_key"]
    envs.items[key].update(status="building", owner="other", updated_at=datetime.utcnow() - timedelta(hours=int(stale)))
    sandbox.installs.clear()
    result = preflight.run_preflight_pass(job, **args)
    assert len(sandbox.installs) == tries
    assert result.handover if stale else result.countdown == 10
    assert not envs.finish(key, "obsolete-worker", status="failed")


@pytest.mark.parametrize("probe,reason", [
    ({"error_type": "ModuleNotFoundError", "missing_name": "requests", "msg": "absent"}, "missing_dependency"),
    ({"error_type": "ModuleNotFoundError", "missing_name": "other", "msg": "absent internally"}, "import_failed"),
    ({"error_type": "ImportError", "msg": "missing shared object"}, "import_failed"),
    ({}, None)])
def test_probe_classifies_direct_and_internal_failures(job, repo, reader, records, sandbox, probe, reason):
    reader.files["src"]["content"] = "import requests\n" + CODE
    sandbox.script["probe"] = {"requests": probe} if probe else {}
    preflight.run_preflight_pass(job, jobs=repo, records=records, envs=None, reader=reader,
                                 executor=sandbox, adapter=adapter_for("python"))
    assert records.list(job)[0]["reason_code"] == reason
    if not probe:
        assert repo.get(job)["preflight"]["probe"]["not_probed"] == ["requests"]
        assert repo.get(job)["stage"] == "generating"
