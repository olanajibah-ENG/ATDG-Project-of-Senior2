import ast
from datetime import datetime, timedelta

from core_ai.services.test_generation import scope
from core_ai.services.test_generation.generation import run_generation_pass
from core_ai.services.test_generation.llm_facade import LLMFacade
from core_ai.services.test_generation.repo import new_job
from core_ai.services.test_generation.runner import run_pass
from core_ai.tests.test_generation.conftest import PROJECT_ID, analysis_for
from core_ai.tests.test_generation.fakes import FakeModel, context_in

NOW = datetime(2026, 11, 13, 12, 0, 0)


def start(repo, reader, **data):
    data.setdefault("project_id", PROJECT_ID)
    resolved = scope.resolve(data, reader)
    files = [{"path": f["path"], "file_id": f["file_id"], "file_type": f["file_type"], "status": "pending",
              "reason": None, "analysis_requests": 0, "requested_at": None} for f in resolved.files]
    return repo.create(new_job(user_id=7, project_id=PROJECT_ID, version_number=resolved.version_number,
                               paths=resolved.paths, levels=resolved.levels, files=files, now=NOW))["job_id"]


def run_to_end(job_id, repo, reader, records, attempts, model, max_requests=20, max_passes=200):
    """Planning pass, then generation passes until the job says it is done. → number of generation passes."""
    run_pass(job_id, repo, reader, lambda file_id: None, NOW, then_generate=True, record_repo=records)
    facade = LLMFacade(model, attempts, max_tokens=2000)
    passes = 0
    # S3: generation ends by handing over to the run stage (status running, stage sandbox_run)
    while (repo.get(job_id)["status"] == "running" and repo.get(job_id)["stage"] != "sandbox_run"
           and passes < max_passes):
        run_generation_pass(job_id, repo, records, attempts, reader, facade, NOW, max_requests=max_requests)
        passes += 1
    return passes


# ── User Story 1 ─────────────────────────────────────────────────────────────

def test_planning_hands_over_to_generation(repo, reader, records, make_project):
    make_project({"game.py": "game.py"})
    job_id = start(repo, reader)
    result = run_pass(job_id, repo, reader, lambda f: None, NOW, then_generate=True, record_repo=records)

    job = repo.get(job_id)
    assert result.done is False
    assert (job["status"], job["stage"]) == ("running", "preflight")
    assert len(records.list(job_id)) == 42
    assert len(records.list(job_id, level="unit")) == 14
    assert {r["status"] for r in records.list(job_id)} == {"pending"}
    assert job["progress"]["total"] == 42 and job["progress"]["done"] == 0
    assert job["llm_requests"] == 0


def test_records_are_created_once(repo, reader, records, make_project):
    make_project({"game.py": "game.py"})
    job_id = start(repo, reader)
    for _ in range(2):
        run_pass(job_id, repo, reader, lambda f: None, NOW, then_generate=True, record_repo=records)
    assert len(records.list(job_id)) == 42


def test_one_unit_per_pass_until_all_are_generated(repo, reader, records, attempts, make_project):
    make_project({"game.py": "game.py"})
    job_id = start(repo, reader)
    model = FakeModel()
    passes = run_to_end(job_id, repo, reader, records, attempts, model)

    job = repo.get(job_id)
    assert passes == 15                               # 14 units + the pass that finds none left
    assert len(model.calls) == 14                     # one request per unit, never more
    assert (job["status"], job["stage"], job["error"]) == ("running", "sandbox_run", None)   # handed to S3
    assert job["llm_requests"] == 14

    unit_records = records.list(job_id, level="unit")
    assert {r["status"] for r in unit_records} == {"generated"}
    for record in unit_records:
        ast.parse(record["test_code"])
        assert record["test_path"].startswith("tests/generated/test_game_") and record["test_path"].endswith("__unit.py")
        assert (record["model"], record["prompt_version"], record["reused"]) == ("fake/model", "unit-v3", False)
        assert "NOT RUN YET" in record["test_code"]
    enroll = next(r for r in unit_records if r["unit_id"] == "game.py::Student.enroll")
    assert "def test_Student_enroll__unit_1():" in enroll["test_code"]
    assert "def test_Student_enroll__unit_2():" in enroll["test_code"]


def test_other_levels_stay_pending_and_nothing_is_ever_ready(repo, reader, records, attempts, make_project):
    make_project({"game.py": "game.py"})
    job_id = start(repo, reader)
    run_to_end(job_id, repo, reader, records, attempts, FakeModel())

    assert {r["status"] for r in records.list(job_id, level="edge")} == {"pending"}
    assert {r["status"] for r in records.list(job_id, level="integration")} == {"pending"}
    assert records.list(job_id, status="ready") == []
    progress = repo.get(job_id)["progress"]
    assert progress["total"] == 42 and progress["done"] == 14
    assert (progress["by_status"]["generated"], progress["by_status"]["pending"], progress["by_status"]["ready"]) == (14, 28, 0)


def test_progress_grows_by_one_per_pass(repo, reader, records, attempts, make_project):
    make_project({"game.py": "game.py"})
    job_id = start(repo, reader, levels=["unit"])
    run_pass(job_id, repo, reader, lambda f: None, NOW, then_generate=True, record_repo=records)
    facade = LLMFacade(FakeModel(), attempts)
    seen = []
    for _ in range(3):
        run_generation_pass(job_id, repo, records, attempts, reader, facade, NOW)
        seen.append(repo.get(job_id)["progress"]["done"])
    assert seen == [1, 2, 3]
    assert repo.get(job_id)["stage"] == "generating"


def test_one_bad_answer_fails_only_its_unit(repo, reader, records, attempts, make_project):
    make_project({"game.py": "game.py"})
    job_id = start(repo, reader, levels=["unit"])
    model = FakeModel(answers={"Course.add_student": "I am sorry, I cannot help with that."})
    run_to_end(job_id, repo, reader, records, attempts, model)

    job = repo.get(job_id)
    assert (job["status"], job["stage"], job["error"]) == ("running", "sandbox_run", None)   # handed to S3
    failed = records.list(job_id, status="generation_failed")
    assert [(r["unit_id"], r["reason_code"]) for r in failed] == [("game.py::Course.add_student", "no_code")]
    assert failed[0]["test_code"] is None and failed[0]["test_path"] is None
    assert len(records.list(job_id, status="generated")) == 13
    assert len(model.calls) == 14                       # no second request for the failed unit


def test_each_failure_reason_is_recorded(repo, reader, records, attempts, make_project):
    make_project({"game.py": "game.py"})
    job_id = start(repo, reader, levels=["unit"])
    fence = "```python\n{}\n```"
    model = FakeModel(answers={
        "Person.__init__": fence.format("def test_x(:\n    pass"),
        "Course.__init__": fence.format("import numpy\n\ndef test_x():\n    assert True"),
        "GPS.none": "",
        "Course.add_student": fence.format("import subprocess\n\ndef test_x():\n    assert True"),
        "Course.remove_student": fence.format("from game import Course\n\ndef test_x():\n    assert Course"),
    })
    run_to_end(job_id, repo, reader, records, attempts, model)
    reasons = {r["unit_id"].split("::")[1]: r["reason_code"] for r in records.list(job_id, status="generation_failed")}
    assert reasons == {"Person.__init__": "syntax_error", "Course.__init__": "forbidden_import",
                       "Course.add_student": "unsafe_code", "Course.remove_student": "weak_test"}
    validations = [a["validation"] for a in attempts.list(job_id)]
    assert all(v is not None for v in validations) and sum(1 for v in validations if not v["ok"]) == 4


def test_job_without_the_unit_level_ends_as_in_s1(repo, reader, records, attempts, make_project):
    make_project({"game.py": "game.py"})
    job_id = start(repo, reader, levels=["edge"])
    model = FakeModel()
    result = run_pass(job_id, repo, reader, lambda f: None, NOW, then_generate=True, record_repo=records)
    job = repo.get(job_id)
    assert result.done is True and (job["status"], job["stage"]) == ("completed", "planned")
    assert records.list(job_id) == [] and model.calls == []


def test_run_pass_without_then_generate_is_unchanged(repo, reader, records, make_project):
    make_project({"game.py": "game.py"})
    job_id = start(repo, reader)
    result = run_pass(job_id, repo, reader, lambda f: None, NOW)
    job = repo.get(job_id)
    assert result.done is True and (job["status"], job["stage"]) == ("completed", "planned")
    assert records.list(job_id) == [] and "records_created" not in job


def test_the_model_only_sees_the_context(repo, reader, records, attempts, make_project):
    make_project({"shop/models.py": "shop/models.py", "shop/service.py": "shop/service.py"})
    job_id = start(repo, reader, levels=["unit"], paths=["shop/service.py", "shop/models.py"])
    model = FakeModel()
    run_to_end(job_id, repo, reader, records, attempts, model)

    receipt = next(c for c in model.calls if context_in(c["user"])["unit"]["id"] == "shop/service.py::Checkout.receipt")
    ctx = context_in(receipt["user"])
    assert {c["id"] for c in ctx["callees"]} == {"shop/models.py::Cart.total", "shop/models.py::format_price"}
    assert "sum(p.price" not in receipt["user"]          # Cart.total's body is not sent
    assert all(c["temperature"] == 0.0 and c["max_tokens"] == 2000 for c in model.calls)


# ── stopping early ───────────────────────────────────────────────────────────

def test_model_unavailable_stops_the_job_and_fails_nothing(repo, reader, records, attempts, make_project):
    make_project({"game.py": "game.py"})
    job_id = start(repo, reader, levels=["unit"])
    model = FakeModel(fail_from=4)
    run_to_end(job_id, repo, reader, records, attempts, model)

    job = repo.get(job_id)
    assert (job["status"], job["stage"]) == ("running", "sandbox_run")   # generated tests still run (S3)
    assert job["error"]["code"] == "model_unavailable" and "pending" in job["error"]["message"]
    assert len(model.calls) == 4                         # it did not go on to try the other units
    assert len(records.list(job_id, status="generated")) == 3
    assert len(records.list(job_id, status="pending")) == 11
    assert records.list(job_id, status="generation_failed") == []
    assert job["llm_requests"] == 3
    assert attempts.list(job_id)[-1]["outcome"] == "model_unavailable"


def test_request_limit_stops_the_job(repo, reader, records, attempts, make_project):
    make_project({"game.py": "game.py"})
    job_id = start(repo, reader, levels=["unit"])
    model = FakeModel()
    run_to_end(job_id, repo, reader, records, attempts, model, max_requests=5)

    job = repo.get(job_id)
    assert job["status"] == "running" and job["error"]["code"] == "request_limit_reached"   # S3 runs what exists
    assert len(model.calls) == 5 and job["llm_requests"] == 5
    assert len(records.list(job_id, status="generated")) == 5
    assert len(records.list(job_id, status="pending")) == 9


def test_a_finished_job_is_left_alone(repo, reader, records, attempts, make_project):
    make_project({"game.py": "game.py"})
    job_id = start(repo, reader, levels=["unit"])
    model = FakeModel()
    run_to_end(job_id, repo, reader, records, attempts, model)
    before = repo.get(job_id)
    result = run_generation_pass(job_id, repo, records, attempts, reader, LLMFacade(model, attempts),
                                 NOW + timedelta(hours=1))
    assert result.done is True and len(model.calls) == 14
    assert repo.get(job_id)["progress"] == before["progress"]


# ── User Story 2: reuse ──────────────────────────────────────────────────────

def test_second_job_on_the_same_code_spends_no_request(repo, reader, records, attempts, make_project):
    make_project({"game.py": "game.py"})
    model = FakeModel()
    first = start(repo, reader, levels=["unit"])
    run_to_end(first, repo, reader, records, attempts, model)
    second = start(repo, reader, levels=["unit"])
    run_to_end(second, repo, reader, records, attempts, model)

    assert len(model.calls) == 14                        # all from the first job
    job = repo.get(second)
    assert (job["status"], job["stage"]) == ("running", "sandbox_run") and job["llm_requests"] == 0
    second_records = records.list(second, level="unit")
    assert {r["status"] for r in second_records} == {"generated"} and all(r["reused"] for r in second_records)
    second_attempts = attempts.list(second)
    assert len(second_attempts) == 14
    assert all(a["reused"] and a["prompt_tokens"] == 0 and a["completion_tokens"] == 0 for a in second_attempts)


def test_a_later_job_finishes_what_a_stopped_job_left(repo, reader, records, attempts, make_project):
    make_project({"game.py": "game.py"})
    first = start(repo, reader, levels=["unit"])
    run_to_end(first, repo, reader, records, attempts, FakeModel(fail_from=6))
    assert len(records.list(first, status="generated")) == 5

    model = FakeModel()
    second = start(repo, reader, levels=["unit"])
    run_to_end(second, repo, reader, records, attempts, model)
    assert len(model.calls) == 9                         # only the 9 units the first job never reached
    assert repo.get(second)["stage"] == "sandbox_run" and repo.get(second)["llm_requests"] == 9


def test_changing_one_body_asks_again_for_that_unit_only(repo, reader, records, attempts, make_project):
    make_project({"game.py": "game.py"})
    model = FakeModel()
    run_to_end(start(repo, reader, levels=["unit"]), repo, reader, records, attempts, model)

    changed = analysis_for("game.py")
    for cls in changed["class_diagram_data"]["classes"]:
        for method in cls["methods"]:
            if (cls["name"], method["name"]) == ("Course", "add_student"):
                method["body"] += "\nreturn True"
    reader.files["f1_0"]["analysis"] = changed

    second = start(repo, reader, levels=["unit"])
    run_to_end(second, repo, reader, records, attempts, model)
    assert len(model.calls) == 15
    assert context_in(model.calls[-1]["user"])["unit"]["id"] == "game.py::Course.add_student"
    assert repo.get(second)["llm_requests"] == 1


def test_a_reused_bad_answer_fails_again_without_a_new_request(repo, reader, records, attempts, make_project):
    make_project({"game.py": "game.py"})
    model = FakeModel(answers={"Course.add_student": "no code here"})
    run_to_end(start(repo, reader, levels=["unit"]), repo, reader, records, attempts, model)
    second = start(repo, reader, levels=["unit"])
    run_to_end(second, repo, reader, records, attempts, model)
    assert len(model.calls) == 14
    failed = records.list(second, status="generation_failed")
    assert [(r["unit_id"], r["reason_code"], r["reused"]) for r in failed] == [("game.py::Course.add_student", "no_code", True)]


def test_a_cut_off_answer_is_not_reused_but_asked_again(repo, reader, records, attempts, make_project):
    make_project({"game.py": "game.py"})
    cut = "```python\nfrom game import Course\n\ndef test_a():\n    c = Course('m',"
    first = start(repo, reader, levels=["unit"])
    run_to_end(first, repo, reader, records, attempts, FakeModel(answers={"Course.add_student": cut}))
    failed = records.list(first, status="generation_failed")
    assert [(r["unit_id"], r["reason_code"]) for r in failed] == [("game.py::Course.add_student", "syntax_error")]
    assert "cut off" in failed[0]["reason_detail"]

    model = FakeModel()                                   # this time the model finishes its answer
    second = start(repo, reader, levels=["unit"])
    run_to_end(second, repo, reader, records, attempts, model)
    assert len(model.calls) == 1                          # only the cut-off unit was asked again
    assert context_in(model.calls[0]["user"])["unit"]["id"] == "game.py::Course.add_student"
    assert repo.get(second)["stage"] == "sandbox_run"
    assert len(records.list(second, status="generated")) == 14
