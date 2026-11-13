from django.urls import path

from core_testing.views import JobDetailView, JobListView, JobPlanView

# Mounted at /api/analysis/tests/ (see Ai_project/urls.py)
urlpatterns = [
    path("jobs/", JobListView.as_view(), name="test-jobs"),
    path("jobs/<str:job_id>/", JobDetailView.as_view(), name="test-job-detail"),
    path("jobs/<str:job_id>/plan/", JobPlanView.as_view(), name="test-job-plan"),
]
