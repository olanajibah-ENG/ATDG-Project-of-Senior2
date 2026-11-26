"""Who is calling a test route, and may they read this job.

UPM issues the tokens (HS256, signed with UPM's own key). This service has no table of UPM users,
so the token is checked by signature and expiry only and the user is built from its claims.

A job is read only by its creator (require_owner). Who may START a job on a project is decided by
UPM, with the caller's token, in project_access.py (added 18/11/2026; it closes the gap noted in
specs/001-test-job-plan/research.md, R1).
"""
from django.conf import settings
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.exceptions import AuthenticationFailed

from core_ai.services.test_generation import errors


class TokenUser:
    """Light user built from token claims. Never touches a database."""

    is_authenticated = True
    is_anonymous = False

    def __init__(self, claims):
        self.claims = dict(claims)
        self.id = str(claims.get("user_id"))

    def __str__(self):
        return f"TokenUser({self.id})"


class UpmJWTAuthentication(BaseAuthentication):
    keyword = b"bearer"

    def authenticate_header(self, request):
        # A non-empty value makes DRF answer 401 (not 403) when no credentials were sent.
        return "Bearer"

    def authenticate(self, request):
        parts = get_authorization_header(request).split()
        if not parts:
            return None
        if parts[0].lower() != self.keyword or len(parts) != 2:
            raise AuthenticationFailed("Malformed Authorization header.")

        signing_key = getattr(settings, "TESTGEN_JWT_SIGNING_KEY", "")
        if not signing_key:
            # Fail closed: without the key no token can be trusted.
            raise AuthenticationFailed("Token verification is not configured.")

        from rest_framework_simplejwt.backends import TokenBackend
        from rest_framework_simplejwt.exceptions import TokenBackendError

        try:
            claims = TokenBackend("HS256", signing_key).decode(parts[1].decode("utf-8"), verify=True)
        except (TokenBackendError, UnicodeDecodeError, ValueError) as exc:
            raise AuthenticationFailed("Invalid or expired token.") from exc

        if claims.get("token_type") != "access":
            raise AuthenticationFailed("An access token is required.")
        if claims.get("user_id") in (None, ""):
            raise AuthenticationFailed("The token carries no user id.")

        return TokenUser(claims), claims


def require_owner(job, user):
    """A job is readable only by the user who created it."""
    if str(job.get("user_id")) != str(getattr(user, "id", None)):
        raise errors.forbidden()
