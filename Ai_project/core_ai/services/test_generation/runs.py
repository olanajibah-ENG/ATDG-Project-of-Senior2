"""Storage of runs (`test_runs`): one document per container run, kept for audit.

A record points at its last run; the job points at the final run its coverage came from.
"""
import copy
from datetime import datetime


def new_run(*, run_id, job_id, record_id, kind, version_number, test_paths, output, verdict, coverage=None,
            tests=None, now=None, keep_junit=False):
    """`output` is a sandbox RunOutput; `verdict` a results.Verdict (or None for a final run)."""
    now = now or datetime.utcnow()
    return {
        "run_id": run_id,
        "job_id": job_id,
        "record_id": record_id,
        "kind": kind,                                   # "record" | "final"
        "version_number": version_number,
        "test_paths": list(test_paths),
        "started": output.started,
        "exit_code": output.exit_code,
        "timed_out": output.timed_out,
        "duration_s": output.duration_s,
        "tests": list(tests or []),
        "output": output.output,
        "start_error": output.start_error,
        "coverage": coverage,
        "verdict": ({"status": verdict.status, "reason": verdict.reason, "detail": verdict.detail}
                    if verdict is not None else None),
        "options": dict(output.options or {}),
        # the final run's junit goes into the bundle as junit_results.xml
        "junit_xml": output.junit_xml if keep_junit else None,
        "created_at": now,
    }


class InMemoryRunRepo:
    def __init__(self):
        self._items = []

    def add(self, run):
        self._items.append(copy.deepcopy(run))

    def get(self, run_id):
        for item in self._items:
            if item["run_id"] == run_id:
                return copy.deepcopy(item)
        return None

    def list(self, job_id, kind=None):
        return [copy.deepcopy(i) for i in self._items
                if i["job_id"] == job_id and (kind is None or i["kind"] == kind)]


class MongoRunRepo:
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
            self._collection = db[settings.TEST_RUNS_COLLECTION]
        if not self._indexed:
            self._collection.create_index("run_id", unique=True)
            self._collection.create_index([("job_id", 1), ("kind", 1)])
            self._indexed = True
        return self._collection

    @staticmethod
    def _clean(doc):
        if doc is not None:
            doc.pop("_id", None)
        return doc

    def add(self, run):
        self._col().insert_one(copy.deepcopy(run))

    def get(self, run_id):
        return self._clean(self._col().find_one({"run_id": run_id}))

    def list(self, job_id, kind=None):
        query = {"job_id": job_id}
        if kind is not None:
            query["kind"] = kind
        return [self._clean(d) for d in self._col().find(query).sort("_id", 1)]


_run_repo = None


def get_run_repo():
    global _run_repo
    if _run_repo is None:
        _run_repo = MongoRunRepo()
    return _run_repo


def set_run_repo(repo):
    global _run_repo
    _run_repo = repo
