import json
from datetime import datetime

import pytest
from rest_framework.test import APIRequestFactory

from core_testing import views
from core_testing.runner import run_pass
from core_testing.tests.conftest import PROJECT_ID, make_token

factory = APIRequestFactory()


@pytest.fixture
def enqueued(monkeypatch):
    """Captures background passes instead of sending them to Celery."""
    calls = []
    monkeypatch.setattr(views, "_enqueue", calls.append)
    return calls


def _auth(user_id=7):
    return {"HTTP_AUTHORIZATION": f"Bearer {make_token(user_id=user_id)}"}


def _post(body, user_id=7, auth=True):
    extra = _auth(user_id) if auth else {}
    request = factory.post("/api/analysis/tests/jobs/", data=json.dumps(body),
                           content_type="application/json", **extra)
    response = views.JobListView.as_view()(request)
    response.render()
    return response


def _get(view, job_id, user_id=7, auth=True, header=None):
    extra = _auth(user_id) if auth else {}
    if header is not None:
        extra = {"HTTP_AUTHORIZATION": header}
    request = factory.get(f"/api/analysis/tests/jobs/{job_id}/", **extra)
    response = view.as_view()(request, job_id=job_id)
    response.render()
    return response


def _run(job_id, repo, reader):
    return run_pass(job_id, repo, reader, lambda file_id: None, datetime.utcnow())


# ── User Story 1: start a job, read the plan ────────────────────────────────

def test_start_with_only_project_id(repo, reader, make_project, enqueued):
    make_project({"game.py": "game.py"}, version=1)
    make_project({"game.py": "game.py", "app.js": None}, version=2)
    response = _post({"project_id": PROJECT_ID})

    assert response.status_code == 202
    assert set(response.data) == {"job_id", "status", "project_id", "version_number"}
    assert response.data["status"] == "pending"
    assert response.data["project_id"] == PROJECT_ID
    assert response.data["version_number"] == 2            # latest
    assert enqueued == [response.data["job_id"]]            # exactly one background pass

    job = repo.get(response.data["job_id"])
    assert job["user_id"] == "7"
    assert job["levels"] == ["unit", "edge", "integration"]
    assert [f["path"] for f in job["files"]] == ["game.py", "app.js"]


@pytest.mark.parametrize("body, field", [
    ({}, "project_id"),
    ({"project_id": PROJECT_ID, "version_number": 0}, "version_number"),
    ({"project_id": PROJECT_ID, "version_number": "two"}, "version_number"),
    ({"project_id": PROJECT_ID, "levels": ["smoke"]}, "levels"),
    ({"project_id": PROJECT_ID, "levels": ["unit", "unit"]}, "levels"),
    ({"project_id": PROJECT_ID, "levels": []}, "levels"),
    ({"project_id": PROJECT_ID, "paths": "game.py"}, "paths"),
])
def test_malformed_request_is_400(repo, reader, make_project, enqueued, body, field):
    make_project({"game.py": "game.py"})
    response = _post(body)
    assert response.status_code == 400
    assert response.data["error"]["code"] == "validation_error"
    assert field in response.data["error"]["details"]["fields"]
    assert enqueued == []


def test_snapshot_in_body_is_refused(repo, reader, make_project, enqueued):
    make_project({"game.py": "game.py"})
    response = _post({"project_id": PROJECT_ID, "snapshot": {"game.py": "print(1)"}})
    assert response.status_code == 400 and enqueued == []


def test_unknown_version_and_unknown_path_are_400(repo, reader, make_project, enqueued):
    make_project({"game.py": "game.py"})
    assert _post({"project_id": PROJECT_ID, "version_number": 999}).status_code == 400
    response = _post({"project_id": PROJECT_ID, "paths": ["nope.py"]})
    assert response.status_code == 400
    assert response.data["error"]["details"]["paths"] == ["nope.py"]
    assert _post({"project_id": "unknown-project"}).status_code == 400
    assert enqueued == []


def test_no_python_file_is_422_and_no_job_is_created(repo, reader, make_project, enqueued):
    make_project({"app.js": None})
    response = _post({"project_id": PROJECT_ID})
    assert response.status_code == 422
    assert response.data["error"]["code"] == "no_python_files"
    assert enqueued == [] and repo._jobs == {}


def test_plan_shape(repo, reader, make_project, enqueued):
    make_project({"game.py": "game.py", "app.js": None})
    job_id = _post({"project_id": PROJECT_ID}).data["job_id"]
    _run(job_id, repo, reader)

    response = _get(views.JobPlanView, job_id)
    assert response.status_code == 200
    assert set(response.data) == {"units", "skipped", "work_items_count"}
    assert len(response.data["units"]) == 14
    assert all(set(u) == {"id", "file", "kind"} for u in response.data["units"])    # no internals
    assert {"id": "game.py::Student.enroll", "file": "game.py", "kind": "method"} in response.data["units"]
    assert response.data["skipped"] == [{"path": "app.js", "reason": "unsupported_language"}]
    assert response.data["work_items_count"] == 42


def test_plan_before_the_first_pass_is_409(repo, reader, make_project, enqueued):
    make_project({"game.py": "game.py"})
    job_id = _post({"project_id": PROJECT_ID}).data["job_id"]
    response = _get(views.JobPlanView, job_id)
    assert response.status_code == 409
    assert response.data["error"]["code"] == "plan_not_ready"


def test_unknown_job_is_404(repo, reader):
    for view in (views.JobDetailView, views.JobPlanView):
        response = _get(view, "job_000000000000")
        assert response.status_code == 404
        assert response.data["error"]["code"] == "not_found"


# ── User Story 2: follow the job ────────────────────────────────────────────

def test_status_shape_right_after_start(repo, reader, make_project, enqueued):
    make_project({"game.py": "game.py"})
    job_id = _post({"project_id": PROJECT_ID}).data["job_id"]
    response = _get(views.JobDetailView, job_id)

    assert response.status_code == 200
    assert set(response.data) == {"job_id", "project_id", "version_number", "status", "stage",
                                  "progress", "files", "error"}
    assert (response.data["status"], response.data["stage"]) == ("pending", "queued")
    assert set(response.data["progress"]["by_status"]) == {
        "pending", "generated", "ready", "skipped", "generation_failed", "test_failed",
        "environment_error"}
    assert response.data["files"] == [{"path": "game.py", "status": "pending"}]
    assert response.data["error"] is None


def test_status_after_planning(repo, reader, make_project, enqueued):
    make_project({"game.py": "game.py", "app.js": None})
    job_id = _post({"project_id": PROJECT_ID}).data["job_id"]
    _run(job_id, repo, reader)
    data = _get(views.JobDetailView, job_id).data

    assert (data["status"], data["stage"]) == ("completed", "planned")
    assert data["progress"]["total"] == 42 and data["progress"]["done"] == 0
    assert data["progress"]["by_status"]["pending"] == 42
    assert data["progress"]["by_status"]["skipped"] == 1
    assert {"path": "app.js", "status": "skipped", "reason": "unsupported_language"} in data["files"]
    assert {"path": "game.py", "status": "pending"} in data["files"]


def test_status_hides_internal_fields(repo, reader, make_project, enqueued):
    make_project({"game.py": "game.py"})
    job_id = _post({"project_id": PROJECT_ID}).data["job_id"]
    _run(job_id, repo, reader)
    text = json.dumps(_get(views.JobDetailView, job_id).data, default=str)
    for hidden in ("file_id", "analysis_requests", "requested_at", "gate", "user_id", "body_hash"):
        assert hidden not in text


def test_waiting_file_shows_as_pending(repo, reader, make_project, enqueued):
    make_project({"game.py": "game.py", "late.py": None}, statuses={"late.py": "IN_PROGRESS"})
    job_id = _post({"project_id": PROJECT_ID}).data["job_id"]
    _run(job_id, repo, reader)
    data = _get(views.JobDetailView, job_id).data
    assert (data["status"], data["stage"]) == ("running", "waiting_analysis")
    assert {"path": "late.py", "status": "pending"} in data["files"]
    # the plan is partial but already readable
    assert len(_get(views.JobPlanView, job_id).data["units"]) == 14


# ── User Story 3: only the owner ────────────────────────────────────────────

def test_every_route_needs_a_token(repo, reader, make_project, enqueued):
    make_project({"game.py": "game.py"})
    job_id = _post({"project_id": PROJECT_ID}).data["job_id"]

    responses = [
        _post({"project_id": PROJECT_ID}, auth=False),
        _get(views.JobDetailView, job_id, auth=False),
        _get(views.JobPlanView, job_id, auth=False),
    ]
    for response in responses:
        assert response.status_code == 401
        assert response.data["error"]["code"] == "unauthorized"
        assert response["WWW-Authenticate"] == "Bearer"
    assert len(enqueued) == 1          # the unauthenticated POST created nothing


@pytest.mark.parametrize("header", ["Bearer garbage", "Token abc", "Bearer"])
def test_invalid_token_is_401(repo, reader, header):
    response = _get(views.JobDetailView, "job_000000000000", header=header)
    assert response.status_code == 401
    assert response.data["error"]["code"] == "unauthorized"


def test_another_user_gets_403_and_the_owner_gets_200(repo, reader, make_project, enqueued):
    make_project({"game.py": "game.py"})
    job_id = _post({"project_id": PROJECT_ID}, user_id=7).data["job_id"]
    _run(job_id, repo, reader)

    for view in (views.JobDetailView, views.JobPlanView):
        stranger = _get(view, job_id, user_id=8)
        assert stranger.status_code == 403
        assert stranger.data["error"]["code"] == "forbidden"
        assert _get(view, job_id, user_id=7).status_code == 200


def test_views_never_fall_back_to_allow_any():
    from rest_framework.permissions import IsAuthenticated

    from core_testing.auth import UpmJWTAuthentication

    for view in (views.JobListView, views.JobDetailView, views.JobPlanView):
        assert view.authentication_classes == [UpmJWTAuthentication]
        assert view.permission_classes == [IsAuthenticated]


def test_routes_are_mounted_under_api_analysis_tests():
    from django.urls import resolve

    assert resolve("/api/analysis/tests/jobs/").func.view_class is views.JobListView
    assert resolve("/api/analysis/tests/jobs/job_abc/").func.view_class is views.JobDetailView
    assert resolve("/api/analysis/tests/jobs/job_abc/plan/").func.view_class is views.JobPlanView


# ── A job the worker never picked up ────────────────────────────────────────

def test_job_never_picked_up_is_reported_as_failed(repo, reader, make_project, enqueued):
    from datetime import timedelta

    make_project({"game.py": "game.py"})
    job_id = _post({"project_id": PROJECT_ID}).data["job_id"]

    # right after the start it is simply pending
    assert _get(views.JobDetailView, job_id).data["status"] == "pending"

    # ... but if nothing has happened long after, the worker never ran it
    repo._jobs[job_id]["created_at"] = datetime.utcnow() - timedelta(minutes=10)
    data = _get(views.JobDetailView, job_id).data
    assert data["status"] == "failed"
    assert data["error"]["code"] == "worker_unavailable"
    assert repo.get(job_id)["status"] == "failed"           # saved

    plan = _get(views.JobPlanView, job_id)
    assert plan.status_code == 409
    assert "failed" in plan.data["error"]["message"]


def test_a_planned_job_is_never_turned_into_a_failure_by_age(repo, reader, make_project, enqueued):
    from datetime import timedelta

    make_project({"game.py": "game.py"})
    job_id = _post({"project_id": PROJECT_ID}).data["job_id"]
    _run(job_id, repo, reader)
    repo._jobs[job_id]["created_at"] = datetime.utcnow() - timedelta(days=30)
    repo._jobs[job_id]["updated_at"] = datetime.utcnow() - timedelta(days=30)
    assert _get(views.JobDetailView, job_id).data["status"] == "completed"
    assert _get(views.JobPlanView, job_id).status_code == 200
