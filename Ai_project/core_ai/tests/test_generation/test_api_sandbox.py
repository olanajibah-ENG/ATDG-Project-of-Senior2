"""S3 routes: coverage and bundle (200, 409 with the shared error body, 403, 401)."""
import io
import zipfile

import pytest
from rest_framework.test import APIRequestFactory

from core_ai.models.testgen import new_job
from core_ai.services.test_generation import records as records_module
from core_ai.services.test_generation.records import InMemoryRecordRepo
from core_ai.tests.test_generation.conftest import PROJECT_ID, make_token
from core_ai.views import testgen_views as views

factory = APIRequestFactory()


@pytest.fixture
def job(repo, runs):
    record_repo = InMemoryRecordRepo()
    records_module.set_record_repo(record_repo)
    j = new_job(user_id=7, project_id=PROJECT_ID, version_number=10, paths=[], levels=["unit"], files=[])
    j.update(status="running", stage="final_run", plan={"units": [], "skipped": []},
             coverage={"available": True, "totals": {"line_pct": 90.0, "branch_pct": 80.0, "combined_pct": 88.0}})
    repo.create(j)
    yield j["job_id"]
    records_module.set_record_repo(None)


def call(view, job_id, user_id=7, auth=True):
    extra = {"HTTP_AUTHORIZATION": f"Bearer {make_token(user_id=user_id)}"} if auth else {}
    response = view.as_view()(factory.get("/x", **extra), job_id=job_id)
    if hasattr(response, "render"):
        response.render()
    return response


@pytest.mark.parametrize("view, code", [(views.JobCoverageView, "coverage_not_ready"),
                                        (views.JobBundleView, "bundle_not_ready")])
def test_409_before_the_job_is_finished_with_the_shared_error_body(job, view, code):
    response = call(view, job)
    assert response.status_code == 409
    body = response.data
    assert set(body) == {"error"} and set(body["error"]) == {"code", "message", "details"}
    assert body["error"]["code"] == code


@pytest.mark.parametrize("view", [views.JobCoverageView, views.JobBundleView])
def test_another_users_job_is_403_and_no_token_is_401(job, view):
    assert call(view, job, user_id=99).status_code == 403
    assert call(view, job, auth=False).status_code == 401


def test_coverage_of_a_finished_job(job, repo):
    repo.update(job, {"status": "completed"})
    response = call(views.JobCoverageView, job)
    assert response.status_code == 200 and response.data["totals"]["line_pct"] == 90.0


def test_job_status_shows_coverage_totals(job, repo):
    repo.update(job, {"status": "completed"})
    request = factory.get("/x", HTTP_AUTHORIZATION=f"Bearer {make_token(user_id=7)}")
    response = views.JobDetailView.as_view()(request, job_id=job)
    assert response.data["coverage"] == {"line_pct": 90.0, "branch_pct": 80.0, "combined_pct": 88.0}


def test_bundle_of_a_finished_job_is_a_zip(job, repo):
    repo.update(job, {"status": "completed"})
    response = call(views.JobBundleView, job)
    assert response.status_code == 200 and response["Content-Type"] == "application/zip"
    assert response["Content-Disposition"] == f'attachment; filename="{job}_{PROJECT_ID}_v10.zip"'
    assert "MANIFEST.json" in zipfile.ZipFile(io.BytesIO(response.content)).namelist()
