"""Feature 1 lives inside core_ai, laid out like the other features. Its boundary is no longer a
separate app, so it is checked here by reading the source:

1. Inside services/test_generation, only llm_facade.py imports the language-model client, and
   nothing is imported from another feature (explanation engine, conflict detection, evaluation).
2. The package uses only the shared parts of core_ai.
3. Outside the package, only Feature 1's own entry files import it. Conflict detection and the
   explanation engine do not depend on it.
4. Planning runs with the language model blocked.
"""
import ast
import os
from datetime import datetime

from core_ai.models.testgen import new_job
from core_ai.services.test_generation import scope
from core_ai.services.test_generation.runner import run_pass
from core_ai.tests.test_generation.conftest import PROJECT_ID

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
CORE_AI_DIR = os.path.dirname(os.path.dirname(TESTS_DIR))
PROJECT_DIR = os.path.dirname(CORE_AI_DIR)
PACKAGE_DIR = os.path.join(CORE_AI_DIR, "services", "test_generation")
PACKAGE = "core_ai.services.test_generation"

OTHER_FEATURES = ("core_ai.ai_engine", "core_ai.services.conflict_detection",
                  "core_ai.services.evaluation_prompt", "core_ai.services.preprocessing")
SHARED_ALLOWED = ("core_ai.mongo_utils", "core_ai.celery_tasks.analyze_task",
                  "core_ai.ai_engine.llm_client", "core_ai.models.testgen",
                  "core_ai.services.project_versioning", PACKAGE)
ENTRY_FILES = {
    "core_ai/views/testgen_views.py",
    "core_ai/serializers/testgen_serializer.py",
    "core_ai/celery_tasks/testgen_tasks.py",
}


def _python_files(root):
    for folder, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in files:
            if name.endswith(".py"):
                yield os.path.join(folder, name)


def _rel(path):
    return os.path.relpath(path, PROJECT_DIR).replace("\\", "/")


def _imports(path):
    with open(path, encoding="utf-8") as handle:
        tree = ast.parse(handle.read(), filename=path)
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
            found.update(f"{node.module}.{alias.name}" for alias in node.names)
    return found


def test_only_the_facade_imports_the_llm_client_and_no_other_feature_is_imported():
    offenders = []
    for path in _python_files(PACKAGE_DIR):
        is_facade = os.path.basename(path) == "llm_facade.py"
        for name in _imports(path):
            if "llm_client" in name:
                if not is_facade:
                    offenders.append((_rel(path), name))
            elif name.startswith(OTHER_FEATURES):
                offenders.append((_rel(path), name))
    assert offenders == []


def test_the_package_uses_only_shared_parts_of_core_ai():
    used = set()
    for path in _python_files(PACKAGE_DIR):
        used.update(name for name in _imports(path) if name.startswith("core_ai"))
    assert all(name.startswith(SHARED_ALLOWED) for name in used), sorted(used)


def test_only_feature_1_entry_files_import_the_package():
    offenders = []
    for path in _python_files(CORE_AI_DIR):
        rel = _rel(path)
        if rel.startswith(("core_ai/services/test_generation/", "core_ai/tests/")):   # tests may import anything
            continue
        if rel in ENTRY_FILES:
            continue
        if any(name == PACKAGE or name.startswith(PACKAGE + ".") for name in _imports(path)):
            offenders.append(rel)
    assert offenders == []


def test_planning_runs_with_the_language_model_blocked(repo, reader, make_project, _no_real_llm):
    make_project({"game.py": "game.py", "shop/models.py": "shop/models.py", "shop/service.py": "shop/service.py"})
    resolved = scope.resolve({"project_id": PROJECT_ID}, reader)
    files = [{"path": f["path"], "file_id": f["file_id"], "file_type": f["file_type"], "status": "pending",
              "reason": None, "analysis_requests": 0, "requested_at": None} for f in resolved.files]
    job = repo.create(new_job(user_id=1, project_id=PROJECT_ID, version_number=resolved.version_number,
                              paths=[], levels=resolved.levels, files=files))

    result = run_pass(job["job_id"], repo, reader, lambda file_id: None, datetime.utcnow())

    assert result.done is True
    assert repo.get(job["job_id"])["status"] == "completed"
    assert _no_real_llm == []        # the blocked client was never reached


# ── S3: who may write `ready`, and who may talk to the container engine ──────

def _calls_of(path, attr):
    with open(path, encoding="utf-8") as handle:
        tree = ast.parse(handle.read(), filename=path)
    return [n for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == attr]


def test_only_the_acceptance_gate_calls_accept_ready():
    callers = {_rel(p) for p in _python_files(CORE_AI_DIR)
               if "/tests/" not in _rel(p) and _calls_of(p, "accept_ready")}
    assert callers == {"core_ai/services/test_generation/acceptance.py"}


def test_only_the_docker_executor_imports_the_docker_sdk():
    importers = {_rel(p) for p in _python_files(CORE_AI_DIR)
                 if "/tests/" not in _rel(p) and any(i == "docker" or i.startswith("docker.") for i in _imports(p))}
    assert importers <= {"core_ai/services/test_generation/sandbox/docker_executor.py"}
