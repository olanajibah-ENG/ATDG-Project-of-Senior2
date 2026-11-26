import copy
from datetime import datetime

from django.conf import settings


def new_snapshot(job, partial):
    report = job["coverage"]
    totals = report.get("totals") or {}
    return dict(snapshot_id="s_" + job["job_id"], job_id=job["job_id"], project_id=job["project_id"],
                version_number=job["version_number"], source=job.get("source") or "manual", partial=partial,
                line_pct=totals.get("line_pct"), branch_pct=totals.get("branch_pct"), files=report.get("files", []),
                final_run_id=job["final_run_id"], created_at=datetime.utcnow())


class InMemorySnapshotRepo:
    def __init__(self):
        self.items = {}

    def add(self, snapshot):
        self.items.setdefault(snapshot["job_id"], copy.deepcopy(snapshot))

    def get(self, job_id):
        return copy.deepcopy(self.items.get(job_id))

    def list_for_project(self, project_id):
        return [self.get(k) for k, v in self.items.items() if v["project_id"] == project_id]


class MongoSnapshotRepo:
    def __init__(self):
        from core_ai.mongo_utils import get_mongo_db

        self.collection = get_mongo_db()[settings.TEST_COVERAGE_SNAPSHOTS_COLLECTION]
        self.collection.create_index("job_id", unique=True)
        self.collection.create_index([(k, 1) for k in ("project_id", "version_number", "source", "created_at")])

    def add(self, snapshot):
        from pymongo.errors import DuplicateKeyError

        try:
            self.collection.insert_one(dict(snapshot))
        except DuplicateKeyError:
            pass

    def get(self, job_id):
        return self.collection.find_one({"job_id": job_id}, {"_id": 0})

    def list_for_project(self, project_id):
        return list(self.collection.find({"project_id": project_id}, {"_id": 0}).sort("created_at", 1))


_repo = None


def get_snapshot_repo():
    global _repo
    if _repo is None:
        _repo = MongoSnapshotRepo()
    return _repo


def set_snapshot_repo(repo):
    global _repo
    _repo = repo
