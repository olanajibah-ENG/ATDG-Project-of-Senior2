import pytest
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.test import APIRequestFactory

from core_testing import errors
from core_testing.auth import UpmJWTAuthentication, require_owner
from core_testing.tests.conftest import make_token


def _auth(header=None):
    extra = {"HTTP_AUTHORIZATION": header} if header is not None else {}
    request = APIRequestFactory().get("/api/analysis/tests/jobs/x/", **extra)
    return UpmJWTAuthentication().authenticate(request)


def test_valid_access_token_gives_a_user_with_string_id():
    user, claims = _auth(f"Bearer {make_token(user_id=42, role_type='DEVELOPER')}")
    assert user.id == "42"
    assert user.is_authenticated is True
    assert claims["role_type"] == "DEVELOPER"


def test_no_header_means_no_credentials():
    # DRF then answers 401 because authenticate_header() is not empty.
    assert _auth() is None
    assert UpmJWTAuthentication().authenticate_header(None) == "Bearer"


@pytest.mark.parametrize("header", [
    "Bearer",                       # no token
    "Token abc",                    # wrong scheme
    "Bearer a b",                   # too many parts
    "Bearer not-a-jwt",
])
def test_malformed_header_is_rejected(header):
    with pytest.raises(AuthenticationFailed):
        _auth(header)


def test_wrong_signature_is_rejected():
    with pytest.raises(AuthenticationFailed):
        _auth(f"Bearer {make_token(key='another-key-another-key-another-key-0000')}")


def test_expired_token_is_rejected():
    with pytest.raises(AuthenticationFailed):
        _auth(f"Bearer {make_token(lifetime_seconds=-10)}")


def test_refresh_token_is_rejected():
    with pytest.raises(AuthenticationFailed):
        _auth(f"Bearer {make_token(token_type='refresh')}")


def test_token_without_user_id_is_rejected():
    with pytest.raises(AuthenticationFailed):
        _auth(f"Bearer {make_token(user_id=None)}")


def test_empty_signing_key_fails_closed(monkeypatch):
    from django.conf import settings

    good = make_token()
    monkeypatch.setattr(settings, "CORE_TESTING_JWT_SIGNING_KEY", "")
    with pytest.raises(AuthenticationFailed):
        _auth(f"Bearer {good}")


def test_require_owner():
    class User:
        id = "7"

    require_owner({"user_id": "7"}, User())
    with pytest.raises(errors.ApiError) as info:
        require_owner({"user_id": "8"}, User())
    assert (info.value.http_status, info.value.code) == (403, "forbidden")
