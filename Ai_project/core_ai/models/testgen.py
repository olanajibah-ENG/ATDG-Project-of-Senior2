"""Documents of Feature 1 (Generate Trusted Tests), as they are stored in MongoDB.

  test_jobs      one request for tests, with its plan inside        → new_job
  test_records   one work item: a unit at a level                   → new_record
  test_attempts  one request to the language model, or one reuse    → new_attempt

Field by field: specs/001-test-job-plan/data-model.md and specs/002-unit-test-generation/data-model.md
"""
import uuid
from datetime import datetime


def new_job_id():
    """`job_` + 12 hexadecimal characters. This is the id used in URLs and responses."""
    return "job_" + uuid.uuid4().hex[:12]


def new_job(*, user_id, project_id, version_number, paths, levels, files, now=None):
    """A fresh job document (see specs/001-test-job-plan/data-model.md)."""
    now = now or datetime.utcnow()
    return {
        "job_id": new_job_id(),
        "user_id": str(user_id),
        "project_id": project_id,
        "version_number": version_number,
        "paths": list(paths),
        "levels": list(levels),
        "status": "pending",
        "stage": "queued",
        "files": files,
        "plan": None,
        "progress": None,
        "gate": {"deadline_at": None, "passes": 0},
        "error": None,
        "created_at": now,
        "updated_at": now,
    }


def new_record(job_id, unit, level, now=None):
    now = now or datetime.utcnow()
    return {
        "record_id": "t_" + uuid.uuid4().hex[:10],
        "job_id": job_id,
        "unit_id": unit["id"],
        "file": unit["file"],
        "level": level,
        "status": "pending",
        "reason_code": None,
        "reason_detail": None,
        "test_path": None,
        "test_code": None,
        "body_hash": unit.get("body_hash"),
        "model": None,
        "prompt_version": None,
        "reused": False,
        "created_at": now,
        "updated_at": now,
    }


def new_attempt(*, job_id, record_id, unit_id, level, purpose, prompt_version, request_hash, now=None):
    return {
        "attempt_id": "a_" + uuid.uuid4().hex[:10],
        "job_id": job_id,
        "record_id": record_id,
        "unit_id": unit_id,
        "level": level,
        "purpose": purpose,
        "prompt_version": prompt_version,
        "request_hash": request_hash,
        "reused": False,
        "model": None,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "duration_ms": 0,
        "outcome": None,
        "answer_text": None,
        "validation": None,
        "created_at": now or datetime.utcnow(),
    }
