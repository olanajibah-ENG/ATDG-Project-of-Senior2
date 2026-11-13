"""Storage of test jobs. One collection (`test_jobs`); the plan lives inside the job.

Two implementations of the same small interface:
- MongoJobRepo     — used by the service
- InMemoryJobRepo  — used by tests (the test container has no database)
"""
import copy
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


class InMemoryJobRepo:
    def __init__(self):
        self._jobs = {}

    def create(self, job):
        self._jobs[job["job_id"]] = copy.deepcopy(job)
        return copy.deepcopy(job)

    def get(self, job_id):
        job = self._jobs.get(job_id)
        return copy.deepcopy(job) if job is not None else None

    def update(self, job_id, fields):
        if job_id not in self._jobs:
            return
        self._jobs[job_id].update(copy.deepcopy(fields))
        self._jobs[job_id]["updated_at"] = datetime.utcnow()


class MongoJobRepo:
    def __init__(self, collection=None):
        self._collection = collection
        self._indexed = False

    def _col(self):
        if self._collection is None:
            from django.conf import settings
            from core_ai.mongo_utils import get_mongo_db

            db = get_mongo_db()
            if db is None:
                raise RuntimeError("MongoDB is not reachable")
            self._collection = db[settings.TEST_JOBS_COLLECTION]
        if not self._indexed:
            self._collection.create_index("job_id", unique=True)
            self._indexed = True
        return self._collection

    def create(self, job):
        doc = copy.deepcopy(job)
        self._col().insert_one(doc)
        doc.pop("_id", None)
        return doc

    def get(self, job_id):
        doc = self._col().find_one({"job_id": job_id})
        if doc is None:
            return None
        doc.pop("_id", None)
        return doc

    def update(self, job_id, fields):
        fields = dict(fields)
        fields["updated_at"] = datetime.utcnow()
        self._col().update_one({"job_id": job_id}, {"$set": fields})


_repo = None


def get_job_repo():
    global _repo
    if _repo is None:
        _repo = MongoJobRepo()
    return _repo


def set_job_repo(repo):
    """Tests install an in-memory repo here; pass None to go back to Mongo."""
    global _repo
    _repo = repo
