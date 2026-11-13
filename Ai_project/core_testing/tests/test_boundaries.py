"""The boundary of the module, checked by reading the source:

1. core_testing imports no language-model client in this slice.
2. core_testing imports nothing from another feature (conflict detection, explanation engine).
3. Nothing in core_ai imports core_testing.
4. A whole job runs with the language model blocked.
"""
import ast
import os
from datetime import datetime

from core_testing import scope
from core_testing.repo import new_job
from core_testing.runner import run_pass
from core_testing.tests.conftest import PROJECT_ID

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_DIR = os.path.dirname(APP_DIR)

FORBIDDEN = ("core_ai.ai_engine", "core_ai.services.conflict_detection", "core_ai.services.evaluation_prompt")


def _python_files(root, skip_dirs=()):
    for folder, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in skip_dirs and d != "__pycache__"]
        for name in files:
            if name.endswith(".py"):
                yield os.path.join(folder, name)


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


def test_core_testing_imports_no_llm_client_and_no_other_feature():
    offenders = []
    for path in _python_files(APP_DIR, skip_dirs=("tests",)):
        for name in _imports(path):
            if "llm_client" in name or name.startswith(FORBIDDEN):
                offenders.append((os.path.relpath(path, PROJECT_DIR), name))
    assert offenders == []


def test_core_ai_never_imports_core_testing():
    offenders = []
    for path in _python_files(os.path.join(PROJECT_DIR, "core_ai")):
        if any(name == "core_testing" or name.startswith("core_testing.") for name in _imports(path)):
            offenders.append(os.path.relpath(path, PROJECT_DIR))
    assert offenders == []


def test_only_shared_parts_of_core_ai_are_used():
    allowed = ("core_ai.mongo_utils", "core_ai.celery_tasks.analyze_task")
    used = set()
    for path in _python_files(APP_DIR, skip_dirs=("tests",)):
        used.update(n for n in _imports(path) if n.startswith("core_ai"))
    assert all(name.startswith(allowed) for name in used), sorted(used)


def test_a_whole_job_runs_with_the_language_model_blocked(repo, reader, make_project, _no_real_llm):
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
