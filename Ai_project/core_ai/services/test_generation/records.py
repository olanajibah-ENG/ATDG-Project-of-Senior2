"""Storage of work items and of model requests.

  test_records   one document per (unit, level): status, reason, test path and test text
  test_attempts  one document per model request, or per reuse of an earlier answer

Each has a Mongo implementation for the service and an in-memory one for tests.
"""
import copy
from datetime import datetime

from core_ai.services.test_generation.statuses import (
    RECORD_STATUSES, REPAIRABLE_CAUSES, Actor, IllegalTransition, RecordStatus, sources_of,
)


from core_ai.models.testgen import new_attempt, new_record  # noqa: F401  (re-exported)


def empty_counts():
    return {name: 0 for name in RECORD_STATUSES}


def max_repair_attempts():
    try:
        from django.conf import settings

        return int(getattr(settings, "TESTGEN_MAX_REPAIR_ATTEMPTS", 2))
    except Exception:
        return 2


class ReadyNotAllowed(ValueError):
    """`ready` is written only through accept_ready(), which only the acceptance gate calls."""


class StatusNotAllowed(ValueError):
    """A status is changed only through transition() (or accept_ready() for `ready`)."""


def _refuse_ready(fields):
    if fields.get("status") == RecordStatus.READY:
        raise ReadyNotAllowed("a record becomes ready only through the acceptance gate")
    if "status" in fields:
        raise StatusNotAllowed("change a record's status through transition()")


def _matches_transition(item, to_status, actor):
    if item["status"] not in sources_of(to_status, actor):
        return False
    if actor == Actor.REPAIR and to_status == RecordStatus.GENERATED:
        return int(item.get("attempts_used") or 0) < max_repair_attempts()
    return True


def _repairable(item):
    return (item["status"] in (RecordStatus.TEST_FAILED, RecordStatus.GENERATION_FAILED)
            and item.get("reason_code") in REPAIRABLE_CAUSES
            and int(item.get("attempts_used") or 0) < max_repair_attempts()
            and not item.get("repair_closed"))


# ── records ─────────────────────────────────────────────────────────────────

class InMemoryRecordRepo:
    def __init__(self):
        self._items = []          # insertion order is the plan's order

    def create_many(self, records):
        self._items.extend(copy.deepcopy(r) for r in records)

    def get(self, record_id):
        for item in self._items:
            if item["record_id"] == record_id:
                return copy.deepcopy(item)
        return None

    def list(self, job_id, status=None, path=None, level=None):
        return [copy.deepcopy(i) for i in self._items
                if i["job_id"] == job_id
                and (status is None or i["status"] == status)
                and (path is None or i["file"] == path)
                and (level is None or i["level"] == level)]

    def next_pending(self, job_id, level):
        for item in self._items:
            if item["job_id"] == job_id and item["level"] == level and item["status"] == RecordStatus.PENDING:
                return copy.deepcopy(item)
        return None

    def next_generated(self, job_id):
        """The next record of level `unit` waiting to be run (S3), in plan order."""
        for item in self._items:
            if item["job_id"] == job_id and item["level"] == "unit" and item["status"] == RecordStatus.GENERATED:
                return copy.deepcopy(item)
        return None

    def update(self, record_id, fields):
        _refuse_ready(fields)
        self._write(record_id, fields)

    def accept_ready(self, record_id, fields):
        """Only the acceptance gate calls this."""
        self.transition(record_id, RecordStatus.READY, Actor.GATE, fields, _gate=True)

    def transition(self, record_id, to_status, actor, fields=None, _gate=False):
        """Change the status if the table allows it from the record's current status; else raise."""
        if to_status == RecordStatus.READY and not _gate:
            raise ReadyNotAllowed("a record becomes ready only through the acceptance gate")
        for item in self._items:
            if item["record_id"] == record_id:
                if not _matches_transition(item, to_status, actor):
                    raise IllegalTransition(f"{record_id}: {item['status']} → {to_status} by {actor}")
                item.update(copy.deepcopy(dict(fields or {}, status=to_status)))
                item["updated_at"] = datetime.utcnow()
                return
        raise IllegalTransition(f"{record_id}: no such record")

    def push_attempt(self, record_id, attempt):
        for item in self._items:
            if item["record_id"] == record_id:
                item.setdefault("attempts", []).append(copy.deepcopy(attempt))

    def update_attempt(self, record_id, n, fields):
        for item in self._items:
            if item["record_id"] == record_id:
                for attempt in item.get("attempts") or []:
                    if attempt.get("n") == n:
                        attempt.update(copy.deepcopy(fields))

    def next_repairable(self, job_id):
        for item in self._items:
            if item["job_id"] == job_id and item["level"] == "unit" and _repairable(item):
                return copy.deepcopy(item)
        return None

    def _write(self, record_id, fields):
        for item in self._items:
            if item["record_id"] == record_id:
                item.update(copy.deepcopy(fields))
                item["updated_at"] = datetime.utcnow()
                return

    def counts(self, job_id):
        out = empty_counts()
        for item in self._items:
            if item["job_id"] == job_id:
                out[item["status"]] = out.get(item["status"], 0) + 1
        return out


class MongoRecordRepo:
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
            self._collection = db[settings.TEST_RECORDS_COLLECTION]
        if not self._indexed:
            self._collection.create_index("record_id", unique=True)
            self._collection.create_index([("job_id", 1), ("level", 1), ("status", 1)])
            self._indexed = True
        return self._collection

    @staticmethod
    def _clean(doc):
        if doc is not None:
            doc.pop("_id", None)
        return doc

    def create_many(self, records):
        if records:
            self._col().insert_many([copy.deepcopy(r) for r in records])

    def get(self, record_id):
        return self._clean(self._col().find_one({"record_id": record_id}))

    def list(self, job_id, status=None, path=None, level=None):
        query = {"job_id": job_id}
        if status is not None:
            query["status"] = status
        if path is not None:
            query["file"] = path
        if level is not None:
            query["level"] = level
        return [self._clean(d) for d in self._col().find(query).sort("_id", 1)]

    def next_pending(self, job_id, level):
        return self._clean(self._col().find_one(
            {"job_id": job_id, "level": level, "status": RecordStatus.PENDING}, sort=[("_id", 1)]))

    def next_generated(self, job_id):
        return self._clean(self._col().find_one(
            {"job_id": job_id, "level": "unit", "status": RecordStatus.GENERATED}, sort=[("_id", 1)]))

    def update(self, record_id, fields):
        _refuse_ready(fields)
        self._write(record_id, fields)

    def accept_ready(self, record_id, fields):
        """Only the acceptance gate calls this."""
        self.transition(record_id, RecordStatus.READY, Actor.GATE, fields, _gate=True)

    def transition(self, record_id, to_status, actor, fields=None, _gate=False):
        """Atomic: the filter holds the allowed source statuses (and the attempt limit for repair)."""
        if to_status == RecordStatus.READY and not _gate:
            raise ReadyNotAllowed("a record becomes ready only through the acceptance gate")
        query = {"record_id": record_id, "status": {"$in": sorted(sources_of(to_status, actor))}}
        if actor == Actor.REPAIR and to_status == RecordStatus.GENERATED:
            query["$or"] = [{"attempts_used": {"$lt": max_repair_attempts()}},
                            {"attempts_used": {"$exists": False}}]
        update = dict(fields or {}, status=to_status, updated_at=datetime.utcnow())
        result = self._col().update_one(query, {"$set": update})
        if result.matched_count != 1:
            raise IllegalTransition(f"{record_id}: not allowed → {to_status} by {actor}")

    def push_attempt(self, record_id, attempt):
        self._col().update_one({"record_id": record_id}, {"$push": {"attempts": copy.deepcopy(attempt)}})

    def update_attempt(self, record_id, n, fields):
        self._col().update_one({"record_id": record_id, "attempts.n": n},
                               {"$set": {f"attempts.$.{k}": v for k, v in fields.items()}})

    def next_repairable(self, job_id):
        for doc in self._col().find(
                {"job_id": job_id, "level": "unit",
                 "status": {"$in": [RecordStatus.TEST_FAILED, RecordStatus.GENERATION_FAILED]},
                 "reason_code": {"$in": list(REPAIRABLE_CAUSES)}}, sort=[("_id", 1)]):
            if _repairable(doc):
                return self._clean(doc)
        return None

    def _write(self, record_id, fields):
        fields = dict(fields)
        fields["updated_at"] = datetime.utcnow()
        self._col().update_one({"record_id": record_id}, {"$set": fields})

    def counts(self, job_id):
        out = empty_counts()
        pipeline = [{"$match": {"job_id": job_id}}, {"$group": {"_id": "$status", "n": {"$sum": 1}}}]
        for row in self._col().aggregate(pipeline):
            out[row["_id"]] = row["n"]
        return out


# ── attempts ────────────────────────────────────────────────────────────────

class InMemoryAttemptRepo:
    def __init__(self):
        self._items = []

    def add(self, attempt):
        self._items.append(copy.deepcopy(attempt))

    def find_reusable(self, request_hash):
        for item in reversed(self._items):
            if item["request_hash"] == request_hash and item.get("answer_text"):
                return copy.deepcopy(item)
        return None

    def list(self, job_id):
        return [copy.deepcopy(i) for i in self._items if i["job_id"] == job_id]

    def set_validation(self, attempt_id, validation):
        for item in self._items:
            if item["attempt_id"] == attempt_id:
                item["validation"] = copy.deepcopy(validation)


class MongoAttemptRepo:
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
            self._collection = db[settings.TEST_ATTEMPTS_COLLECTION]
        if not self._indexed:
            self._collection.create_index("request_hash")
            self._indexed = True
        return self._collection

    def add(self, attempt):
        self._col().insert_one(copy.deepcopy(attempt))

    def find_reusable(self, request_hash):
        doc = self._col().find_one(
            {"request_hash": request_hash, "answer_text": {"$nin": [None, ""]}}, sort=[("_id", -1)])
        if doc is not None:
            doc.pop("_id", None)
        return doc

    def list(self, job_id):
        docs = list(self._col().find({"job_id": job_id}).sort("_id", 1))
        for doc in docs:
            doc.pop("_id", None)
        return docs

    def set_validation(self, attempt_id, validation):
        self._col().update_one({"attempt_id": attempt_id}, {"$set": {"validation": validation}})


_record_repo = None
_attempt_repo = None


def get_record_repo():
    global _record_repo
    if _record_repo is None:
        _record_repo = MongoRecordRepo()
    return _record_repo


def set_record_repo(repo):
    global _record_repo
    _record_repo = repo


def get_attempt_repo():
    global _attempt_repo
    if _attempt_repo is None:
        _attempt_repo = MongoAttemptRepo()
    return _attempt_repo


def set_attempt_repo(repo):
    global _attempt_repo
    _attempt_repo = repo
