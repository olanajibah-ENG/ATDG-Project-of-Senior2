from datetime import datetime, timedelta

from core_ai.services.test_generation import scope
from core_ai.services.test_generation.repo import new_job
from core_ai.services.test_generation.runner import run_pass
from core_ai.tests.test_generation.conftest import PROJECT_ID, analysis_for

NOW = datetime(2026, 11, 13, 12, 0, 0)


def _start(repo, reader, **data):
    data.setdefault("project_id", PROJECT_ID)
    resolved = scope.resolve(data, reader)
    files = [{"path": f["path"], "file_id": f["file_id"], "file_type": f["file_type"],
              "status": "pending", "reason": None, "analysis_requests": 0, "requested_at": None}
             for f in resolved.files]
    job = repo.create(new_job(user_id=7, project_id=resolved.project_id,
                              version_number=resolved.version_number, paths=resolved.paths,
                              levels=resolved.levels, files=files, now=NOW))
    return job["job_id"]


class Requests(list):
    def __call__(self, file_id):
        self.append(file_id)


def _pass(job_id, repo, reader, requests=None, now=NOW, max_wait=600):
    requests = requests if requests is not None else Requests()
    return run_pass(job_id, repo, reader, requests, now, max_wait_seconds=max_wait), requests


def _file(job, path):
    return next(f for f in job["files"] if f["path"] == path)


# ── User Story 1: planning ──────────────────────────────────────────────────

def test_one_pass_plans_an_analysed_project(repo, reader, make_project):
    make_project({"game.py": "game.py"})
    job_id = _start(repo, reader)
    result, requests = _pass(job_id, repo, reader)

    job = repo.get(job_id)
    assert result.done is True and requests == []
    assert (job["status"], job["stage"]) == ("completed", "planned")
    assert len(job["plan"]["units"]) == 14 and job["plan"]["skipped"] == []
    assert job["plan"]["work_items_count"] == 42
    assert job["progress"] == {"total": 42, "done": 0, "by_status": {
        "pending": 42, "generated": 0, "ready": 0, "skipped": 0,
        "generation_failed": 0, "test_failed": 0, "environment_error": 0}}
    assert job["error"] is None


def test_non_python_file_is_skipped_and_the_rest_is_planned(repo, reader, make_project):
    make_project({"game.py": "game.py", "app.js": None})
    job_id = _start(repo, reader)
    _pass(job_id, repo, reader)

    job = repo.get(job_id)
    assert job["status"] == "completed"
    assert len(job["plan"]["units"]) == 14
    assert job["plan"]["skipped"] == [{"path": "app.js", "reason": "unsupported_language"}]
    assert (_file(job, "app.js")["status"], _file(job, "app.js")["reason"]) == ("skipped", "unsupported_language")
    assert _file(job, "game.py")["status"] == "pending"
    assert job["progress"]["by_status"]["skipped"] == 1


def test_paths_restrict_the_plan(repo, reader, make_project):
    make_project({"a/game.py": "game.py", "b/game.py": "game.py"})
    job_id = _start(repo, reader, paths=["b/game.py"])
    _pass(job_id, repo, reader)
    assert {u["file"] for u in repo.get(job_id)["plan"]["units"]} == {"b/game.py"}


def test_requested_levels_drive_the_work_item_count(repo, reader, make_project):
    make_project({"game.py": "game.py"})
    job_id = _start(repo, reader, levels=["unit"])
    _pass(job_id, repo, reader)
    assert repo.get(job_id)["plan"]["work_items_count"] == 14


def test_file_without_functions_is_reported_as_no_units(repo, reader, make_project):
    make_project({"game.py": "game.py", "no_units.py": "no_units.py"})
    job_id = _start(repo, reader)
    _pass(job_id, repo, reader)
    job = repo.get(job_id)
    assert (_file(job, "no_units.py")["status"], _file(job, "no_units.py")["reason"]) == ("skipped", "no_units")
    assert job["status"] == "completed"


def test_a_pass_is_idempotent(repo, reader, make_project):
    make_project({"game.py": "game.py", "app.js": None})
    job_id = _start(repo, reader)
    _pass(job_id, repo, reader)
    first = repo.get(job_id)
    result, requests = _pass(job_id, repo, reader)
    second = repo.get(job_id)
    assert result.done is True and requests == []
    for key in ("status", "stage", "plan", "progress", "files", "gate"):
        assert first[key] == second[key]


def test_unknown_job_is_done(repo, reader):
    result, _ = _pass("job_000000000000", repo, reader)
    assert result.done is True


def test_planned_units_know_their_callees(repo, reader, make_project):
    make_project({"game.py": "game.py"})
    job_id = _start(repo, reader)
    _pass(job_id, repo, reader)
    by_id = {u["id"]: u for u in repo.get(job_id)["plan"]["units"]}
    assert by_id["game.py::Student.enroll"]["callees"] == ["game.py::Course.add_student"]


# ── User Story 2: files that wait for their analysis ────────────────────────

def test_file_without_analysis_is_requested_once_and_the_rest_is_planned(repo, reader, make_project):
    make_project({"game.py": "game.py", "late.py": None}, statuses={"late.py": None})
    job_id = _start(repo, reader)
    result, requests = _pass(job_id, repo, reader)

    job = repo.get(job_id)
    assert result.done is False
    assert requests == [_file(job, "late.py")["file_id"]]
    assert (job["status"], job["stage"]) == ("running", "waiting_analysis")
    assert len(job["plan"]["units"]) == 14                 # the analysed file is already planned
    assert _file(job, "late.py")["status"] == "pending"

    # 5 s later the worker has not picked the request up: nothing new is requested.
    result, requests = _pass(job_id, repo, reader, requests, now=NOW + timedelta(seconds=5))
    assert result.done is False and len(requests) == 1


def test_units_join_the_plan_when_the_analysis_completes(repo, reader, make_project):
    make_project({"game.py": "game.py", "late.py": None}, statuses={"late.py": None})
    job_id = _start(repo, reader)
    _, requests = _pass(job_id, repo, reader)
    late_id = requests[0]

    reader.files[late_id].update(analysis_status="COMPLETED", analysis=analysis_for("shop/models.py"),
                                 last_attempt_started_at=NOW + timedelta(seconds=2))
    result, requests = _pass(job_id, repo, reader, requests, now=NOW + timedelta(seconds=5))

    job = repo.get(job_id)
    assert result.done is True and len(requests) == 1
    assert (job["status"], job["stage"]) == ("completed", "planned")
    assert "late.py::Cart.add" in {u["id"] for u in job["plan"]["units"]}
    assert len(job["plan"]["units"]) == 14 + 6


def test_file_being_analysed_waits_without_a_request(repo, reader, make_project):
    make_project({"game.py": "game.py", "slow.py": None}, statuses={"slow.py": "IN_PROGRESS"})
    job_id = _start(repo, reader)
    result, requests = _pass(job_id, repo, reader)
    assert result.done is False and requests == []
    assert repo.get(job_id)["stage"] == "waiting_analysis"


def test_failed_twice_is_skipped_and_the_job_still_completes(repo, reader, make_project):
    make_project({"game.py": "game.py", "bad.py": None}, statuses={"bad.py": "FAILED"})
    job_id = _start(repo, reader)

    _, requests = _pass(job_id, repo, reader)                       # request 1
    bad_id = requests[0]
    reader.files[bad_id]["last_attempt_started_at"] = NOW + timedelta(seconds=1)   # attempt 1 failed
    _, requests = _pass(job_id, repo, reader, requests, now=NOW + timedelta(seconds=5))   # request 2
    assert len(requests) == 2
    reader.files[bad_id]["last_attempt_started_at"] = NOW + timedelta(seconds=6)   # attempt 2 failed
    result, requests = _pass(job_id, repo, reader, requests, now=NOW + timedelta(seconds=10))

    job = repo.get(job_id)
    assert result.done is True and len(requests) == 2
    assert job["status"] == "completed"
    assert (_file(job, "bad.py")["status"], _file(job, "bad.py")["reason"]) == ("skipped", "analysis_failed")
    assert {"path": "bad.py", "reason": "analysis_failed"} in job["plan"]["skipped"]
    assert len(job["plan"]["units"]) == 14


def test_job_fails_when_no_python_file_can_be_analysed(repo, reader, make_project):
    make_project({"bad.py": None, "app.js": None}, statuses={"bad.py": "FAILED"})
    job_id = _start(repo, reader)
    _, requests = _pass(job_id, repo, reader)
    bad_id = requests[0]
    reader.files[bad_id]["last_attempt_started_at"] = NOW + timedelta(seconds=1)
    _, requests = _pass(job_id, repo, reader, requests, now=NOW + timedelta(seconds=5))
    reader.files[bad_id]["last_attempt_started_at"] = NOW + timedelta(seconds=6)
    result, _ = _pass(job_id, repo, reader, requests, now=NOW + timedelta(seconds=10))

    job = repo.get(job_id)
    assert result.done is True
    assert job["status"] == "failed"
    assert job["error"]["code"] == "analysis_failed"
    assert job["plan"]["units"] == []


def test_waiting_file_is_skipped_at_the_deadline(repo, reader, make_project):
    make_project({"game.py": "game.py", "slow.py": None}, statuses={"slow.py": "IN_PROGRESS"})
    job_id = _start(repo, reader)
    _pass(job_id, repo, reader, max_wait=60)
    result, _ = _pass(job_id, repo, reader, now=NOW + timedelta(seconds=61), max_wait=60)

    job = repo.get(job_id)
    assert result.done is True
    assert job["status"] == "completed"
    assert _file(job, "slow.py")["reason"] == "analysis_failed"


def test_deadline_is_set_once_on_the_first_pass(repo, reader, make_project):
    make_project({"game.py": "game.py", "slow.py": None}, statuses={"slow.py": "IN_PROGRESS"})
    job_id = _start(repo, reader)
    _pass(job_id, repo, reader, max_wait=600)
    first = repo.get(job_id)["gate"]
    _pass(job_id, repo, reader, now=NOW + timedelta(seconds=5), max_wait=600)
    second = repo.get(job_id)["gate"]
    assert first["deadline_at"] == second["deadline_at"] == NOW + timedelta(seconds=600)
    assert (first["passes"], second["passes"]) == (1, 2)
