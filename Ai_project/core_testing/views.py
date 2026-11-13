"""The three routes of S1. Thin: validate, call the logic, shape the answer.

    POST /api/analysis/tests/jobs/                 start a job            → 202
    GET  /api/analysis/tests/jobs/{job_id}/        status, stage, progress, files
    GET  /api/analysis/tests/jobs/{job_id}/plan/   units, skipped, work_items_count
"""
import logging

from rest_framework import exceptions
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core_testing import errors, serializers
from core_testing import repo as repo_module
from core_testing import readers as readers_module
from core_testing import scope as scope_module
from core_testing.auth import UpmJWTAuthentication, require_owner
from core_testing.statuses import FileStatus

logger = logging.getLogger(__name__)


def _enqueue(job_id):
    from core_testing import tasks

    tasks.enqueue_advance(job_id)


class JobApiView(APIView):
    """Every test route: a UPM token is required, and every error uses the common body."""

    authentication_classes = [UpmJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def handle_exception(self, exc):
        if isinstance(exc, errors.ApiError):
            return errors.to_response(exc)
        if isinstance(exc, (exceptions.NotAuthenticated, exceptions.AuthenticationFailed)):
            return errors.to_response(errors.unauthorized(str(exc.detail)))
        if isinstance(exc, exceptions.PermissionDenied):
            return errors.to_response(errors.forbidden(str(exc.detail)))
        if isinstance(exc, exceptions.ParseError):
            return errors.to_response(errors.validation_error("The request body is not valid JSON."))
        return super().handle_exception(exc)

    def _owned_job(self, request, job_id):
        job = repo_module.get_job_repo().get(job_id)
        if job is None:
            raise errors.not_found()
        require_owner(job, request.user)
        return job


class JobListView(JobApiView):
    def post(self, request):
        data = serializers.validate_start_request(request.data)
        scope = scope_module.resolve(data, readers_module.get_reader())

        files = [{
            "path": f["path"], "file_id": f["file_id"], "file_type": f["file_type"],
            "status": FileStatus.PENDING, "reason": None,
            "analysis_requests": 0, "requested_at": None,
        } for f in scope.files]

        job = repo_module.get_job_repo().create(repo_module.new_job(
            user_id=request.user.id,
            project_id=scope.project_id,
            version_number=scope.version_number,
            paths=scope.paths,
            levels=scope.levels,
            files=files,
        ))
        _enqueue(job["job_id"])
        logger.info("[TESTS] job %s created: project=%s version=%s files=%d",
                    job["job_id"], scope.project_id, scope.version_number, len(files))
        return Response(serializers.start_response(job), status=202)


class JobDetailView(JobApiView):
    def get(self, request, job_id):
        return Response(serializers.status_response(self._owned_job(request, job_id)))


class JobPlanView(JobApiView):
    def get(self, request, job_id):
        job = self._owned_job(request, job_id)
        if job.get("plan") is None:
            raise errors.plan_not_ready()
        return Response(serializers.plan_response(job))
