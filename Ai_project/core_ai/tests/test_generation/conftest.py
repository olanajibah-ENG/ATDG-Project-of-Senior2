"""Shared setup of the core_ai.services.test_generation tests.

- Django is set up once (views and token checks need the app registry).
- No test may reach a real language model: LLMClient.call_model raises on any call.
- Storage is in memory: the test container has no MongoDB.
"""
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Ai_project.settings")

import django  # noqa: E402

django.setup()

import pytest  # noqa: E402

from core_ai.services.test_generation import readers as readers_module  # noqa: E402
from core_ai.services.test_generation import repo as repo_module  # noqa: E402
from core_ai.services.test_generation.readers import InMemoryAnalysisReader  # noqa: E402
from core_ai.services.test_generation.repo import InMemoryJobRepo  # noqa: E402
from core_ai.tests.test_generation import helpers  # noqa: E402

TEST_KEY = "core-testing-unit-test-signing-key-0123456789"
PROJECT_ID = "3f2b6c1e-8a4d-4c0b-9d57-1e2a7f6b9c10"


class LLMCalled(AssertionError):
    pass


@pytest.fixture(autouse=True)
def _no_real_llm(monkeypatch):
    from core_ai.ai_engine.llm_client import LLMClient

    calls = []

    def _blocked(*args, **kwargs):
        calls.append((args, kwargs))
        raise LLMCalled("a language model was called inside core_ai.services.test_generation tests")

    monkeypatch.setattr(LLMClient, "call_model", staticmethod(_blocked))
    return calls


@pytest.fixture(autouse=True)
def _signing_key(monkeypatch):
    from django.conf import settings

    monkeypatch.setattr(settings, "TESTGEN_JWT_SIGNING_KEY", TEST_KEY, raising=False)


class FakeProjectAccess:
    """Stands in for UPM's project check. `status` is what UPM would answer (None = no answer)."""

    def __init__(self, status=200):
        self.status = status
        self.calls = []

    def status_of(self, project_id, token):
        self.calls.append((project_id, token))
        return self.status


@pytest.fixture(autouse=True)
def upm_access():
    """Every test runs as the project's owner unless it changes `upm_access.status`."""
    from core_ai.services.test_generation import project_access

    fake = FakeProjectAccess()
    project_access.set_project_access(fake)
    yield fake
    project_access.set_project_access(None)


@pytest.fixture
def repo():
    instance = InMemoryJobRepo()
    repo_module.set_job_repo(instance)
    yield instance
    repo_module.set_job_repo(None)


@pytest.fixture
def reader():
    instance = InMemoryAnalysisReader()
    readers_module.set_reader(instance)
    yield instance
    readers_module.set_reader(None)


_analysis_cache = {}


def analysis_for(source_name):
    if source_name not in _analysis_cache:
        _analysis_cache[source_name] = helpers.build_analysis(helpers.load_source(source_name))
    import copy

    return copy.deepcopy(_analysis_cache[source_name])


@pytest.fixture
def make_project(reader):
    """make_project({"pkg/game.py": "game.py", "app.js": None}, version=1, statuses={path: "FAILED"})

    A value is the name of a fixture source to analyse, or None for a file with no analysis.
    Non-.py paths get file_type "javascript".
    """

    def _make(files, version=1, project_id=PROJECT_ID, statuses=None):
        statuses = statuses or {}
        ids = []
        for index, (path, source_name) in enumerate(files.items()):
            file_id = f"f{version}_{index}"
            python = path.endswith(".py")
            analysis = analysis_for(source_name) if (python and source_name) else None
            default_status = "COMPLETED" if analysis is not None else ("PENDING" if python else None)
            reader.add_file(
                file_id, path,
                file_type="python" if python else "javascript",
                analysis_status=statuses.get(path, default_status),
                analysis=analysis if statuses.get(path, "COMPLETED") == "COMPLETED" else None,
            )
            ids.append(file_id)
        reader.add_version(project_id, version, ids)
        return project_id

    return _make


def make_token(user_id=7, token_type="access", key=TEST_KEY, lifetime_seconds=3600, **extra):
    import time

    from rest_framework_simplejwt.backends import TokenBackend

    now = int(time.time())
    claims = {"token_type": token_type, "user_id": user_id, "iat": now, "exp": now + lifetime_seconds,
              "jti": "test"}
    claims.update(extra)
    return TokenBackend("HS256", key).encode(claims)


@pytest.fixture
def token():
    return make_token


# ── S2: records, attempts and a scripted model ──────────────────────────────

@pytest.fixture
def records():
    from core_ai.services.test_generation import records as records_module

    instance = records_module.InMemoryRecordRepo()
    records_module.set_record_repo(instance)
    yield instance
    records_module.set_record_repo(None)


@pytest.fixture
def attempts():
    from core_ai.services.test_generation import records as records_module

    instance = records_module.InMemoryAttemptRepo()
    records_module.set_attempt_repo(instance)
    yield instance
    records_module.set_attempt_repo(None)
