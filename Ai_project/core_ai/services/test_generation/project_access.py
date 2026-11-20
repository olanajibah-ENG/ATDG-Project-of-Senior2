"""May this user start a test job on this project? UPM decides.

This service has no table of UPM projects or owners. UPM does: its route
`GET /api/upm/projects/<id>/` answers 200 only to the project's owner and 404 to anyone else.
So before a job is created we call that route with the caller's own token, from inside the
docker network (settings.UPM_INTERNAL_URL), and follow its answer:

    200        → allowed
    403 / 404  → 404 "Project not found" (we do not say whether it exists)
    401        → 401 (the token was refused by UPM)
    no answer  → 503: we refuse rather than allow

Nothing is stored here: UPM stays the only source of who owns what.
"""
import logging

from django.conf import settings

from core_ai.services.test_generation import errors

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 5


class UpmProjectAccess:
    def __init__(self, base_url=None, timeout=TIMEOUT_SECONDS):
        self.base_url = (base_url or getattr(settings, "UPM_INTERNAL_URL", "http://web:8000")).rstrip("/")
        self.timeout = timeout

    def status_of(self, project_id, token):
        """HTTP status UPM gives this token for this project, or None when UPM does not answer."""
        import requests

        url = f"{self.base_url}/api/upm/projects/{project_id}/"
        try:
            response = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=self.timeout)
        except requests.RequestException as exc:
            logger.warning("[TESTS] UPM did not answer the project check: %s", exc)
            return None
        return response.status_code


_access = None


def get_project_access():
    global _access
    if _access is None:
        _access = UpmProjectAccess()
    return _access


def set_project_access(access):
    """For tests: put a fake in place (None puts the real one back on next use)."""
    global _access
    _access = access


def ensure_can_use_project(project_id, token):
    status = get_project_access().status_of(project_id, token)
    if status == 200:
        return
    if status in (403, 404):
        raise errors.not_found("Project not found.")
    if status == 401:
        raise errors.unauthorized("UPM refused the token.")
    logger.warning("[TESTS] project check for %s got %s", project_id, status)
    raise errors.service_unavailable("Could not check the project with UPM. Try again shortly.")
