"""Only the project's owner may start a test job on it. UPM decides, with the caller's own token.

    python -m pytest core_ai/tests/test_generation/test_project_access.py -q
"""
import json

import pytest
from rest_framework.test import APIRequestFactory

from core_ai.services.test_generation import project_access
from core_ai.tests.test_generation.conftest import PROJECT_ID, make_token
from core_ai.views import testgen_views as views

factory = APIRequestFactory()


@pytest.fixture
def enqueued(monkeypatch):
    calls = []
    monkeypatch.setattr(views, "_enqueue", calls.append)
    return calls


def _post(body, token):
    request = factory.post("/api/analysis/tests/jobs/", data=json.dumps(body),
                           content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {token}")
    response = views.JobListView.as_view()(request)
    response.render()
    return response


# ── the route ───────────────────────────────────────────────────────────────

def test_owner_starts_a_job(repo, reader, make_project, enqueued, upm_access):
    make_project({"game.py": "game.py"})
    response = _post({"project_id": PROJECT_ID}, make_token(user_id=7))
    assert response.status_code == 202
    assert len(repo._jobs) == 1


def test_the_callers_own_token_is_sent_to_upm(repo, reader, make_project, enqueued, upm_access):
    make_project({"game.py": "game.py"})
    token = make_token(user_id=7)
    _post({"project_id": PROJECT_ID}, token)
    assert upm_access.calls == [(PROJECT_ID, token)]


@pytest.mark.parametrize("upm_status", [404, 403])
def test_someone_elses_project_is_not_found_and_no_job_is_made(repo, reader, make_project, enqueued,
                                                               upm_access, upm_status):
    make_project({"game.py": "game.py"})
    upm_access.status = upm_status
    response = _post({"project_id": PROJECT_ID}, make_token(user_id=99))
    assert response.status_code == 404
    assert json.loads(response.content)["error"]["code"] == "not_found"
    assert repo._jobs == {} and enqueued == []


def test_upm_not_answering_refuses_with_503(repo, reader, make_project, enqueued, upm_access):
    make_project({"game.py": "game.py"})
    upm_access.status = None
    response = _post({"project_id": PROJECT_ID}, make_token(user_id=7))
    assert response.status_code == 503
    assert json.loads(response.content)["error"]["code"] == "service_unavailable"
    assert repo._jobs == {} and enqueued == []


def test_upm_refusing_the_token_is_401(repo, reader, make_project, enqueued, upm_access):
    make_project({"game.py": "game.py"})
    upm_access.status = 401
    response = _post({"project_id": PROJECT_ID}, make_token(user_id=7))
    assert response.status_code == 401
    assert repo._jobs == {}


def test_upm_is_asked_before_anything_about_the_project_is_read(repo, reader, enqueued, upm_access):
    # no project in the reader at all: the answer must still be UPM's 404, not "unknown project"
    upm_access.status = 404
    response = _post({"project_id": "someone-elses-project"}, make_token(user_id=99))
    assert response.status_code == 404


# ── the real UPM client, with HTTP faked ────────────────────────────────────

class _Resp:
    def __init__(self, status_code):
        self.status_code = status_code


def test_client_calls_the_upm_project_route_with_the_token(monkeypatch):
    import requests

    seen = {}

    def fake_get(url, headers=None, timeout=None):
        seen.update(url=url, headers=headers, timeout=timeout)
        return _Resp(200)

    monkeypatch.setattr(requests, "get", fake_get)
    client = project_access.UpmProjectAccess(base_url="http://upm:8000/")
    assert client.status_of("p-1", "tok") == 200
    assert seen["url"] == "http://upm:8000/api/upm/projects/p-1/"
    assert seen["headers"] == {"Authorization": "Bearer tok"}
    assert seen["timeout"] == project_access.TIMEOUT_SECONDS


def test_client_returns_none_when_upm_does_not_answer(monkeypatch):
    import requests

    def fake_get(url, headers=None, timeout=None):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(requests, "get", fake_get)
    assert project_access.UpmProjectAccess(base_url="http://upm:8000").status_of("p-1", "tok") is None
