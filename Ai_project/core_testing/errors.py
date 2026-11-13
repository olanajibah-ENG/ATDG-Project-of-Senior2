"""Error codes of the test routes and the one body shape every error uses."""


class ApiError(Exception):
    def __init__(self, http_status, code, message, details=None):
        super().__init__(message)
        self.http_status = http_status
        self.code = code
        self.message = message
        self.details = details or {}

    def body(self):
        return {"error": {"code": self.code, "message": self.message, "details": self.details}}


def validation_error(message, details=None):
    return ApiError(400, "validation_error", message, details)


def unauthorized(message="A valid access token is required."):
    return ApiError(401, "unauthorized", message)


def forbidden(message="This job belongs to another user."):
    return ApiError(403, "forbidden", message)


def not_found(message="No job with that id."):
    return ApiError(404, "not_found", message)


def plan_not_ready(message="The plan is not ready yet. Poll the job and try again."):
    return ApiError(409, "plan_not_ready", message)


def no_python_files(message="The selection contains no Python file."):
    return ApiError(422, "no_python_files", message)


def to_response(err):
    from rest_framework.response import Response

    response = Response(err.body(), status=err.http_status)
    if err.http_status == 401:
        response["WWW-Authenticate"] = "Bearer"
    return response
