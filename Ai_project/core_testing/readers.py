"""Read-only access to what analysis already stores.

Nothing here writes. The three collections belong to core_ai:
  project_versions  — which files make up a version
  code_files        — path, language, analysis status of one file
  analysis_results  — stored AST, class data and graph of one file
  analysis_jobs     — one document per analysis attempt (read for its start time only)
"""
import copy


def _file_state(analysis_status, has_result, last_attempt_started_at):
    return {
        "analysis_status": analysis_status,
        "has_result": bool(has_result),
        "last_attempt_started_at": last_attempt_started_at,
    }


class InMemoryAnalysisReader:
    """Test double. `files` maps file_id → {path, file_type, analysis_status, analysis, last_attempt_started_at}."""

    def __init__(self):
        self.versions = {}  # project_id -> {version_number: [file_id, ...]}
        self.files = {}

    def add_version(self, project_id, version_number, file_ids):
        self.versions.setdefault(project_id, {})[version_number] = list(file_ids)

    def add_file(self, file_id, path, file_type="python", analysis_status="COMPLETED", analysis=None,
                 last_attempt_started_at=None):
        self.files[file_id] = {
            "path": path,
            "file_type": file_type,
            "analysis_status": analysis_status,
            "analysis": analysis,
            "last_attempt_started_at": last_attempt_started_at,
        }

    # ── interface ────────────────────────────────────────────────────────────
    def latest_version(self, project_id):
        versions = self.versions.get(project_id)
        return max(versions) if versions else None

    def version_exists(self, project_id, version_number):
        return version_number in self.versions.get(project_id, {})

    def files_of_version(self, project_id, version_number):
        out = []
        for file_id in self.versions.get(project_id, {}).get(version_number, []):
            f = self.files[file_id]
            out.append({"file_id": file_id, "path": f["path"], "file_type": f["file_type"],
                        "analysis_status": f["analysis_status"]})
        return out

    def file_state(self, file_id):
        f = self.files.get(file_id)
        if f is None:
            return _file_state(None, False, None)
        return _file_state(f["analysis_status"], f["analysis"] is not None, f["last_attempt_started_at"])

    def analysis_of(self, file_id):
        f = self.files.get(file_id)
        return copy.deepcopy(f["analysis"]) if f and f["analysis"] is not None else None


class MongoAnalysisReader:
    def __init__(self, db=None):
        self._db = db

    def _database(self):
        if self._db is None:
            from core_ai.mongo_utils import get_mongo_db

            self._db = get_mongo_db()
            if self._db is None:
                raise RuntimeError("MongoDB is not reachable")
        return self._db

    def _col(self, setting_name, default):
        from django.conf import settings

        return self._database()[getattr(settings, setting_name, default)]

    @staticmethod
    def _oid(value):
        from bson import ObjectId

        try:
            return ObjectId(str(value))
        except Exception:
            return None

    # ── interface ────────────────────────────────────────────────────────────
    def latest_version(self, project_id):
        doc = self._database()["project_versions"].find_one(
            {"project_id": project_id}, sort=[("version_number", -1)]
        )
        return int(doc["version_number"]) if doc else None

    def version_exists(self, project_id, version_number):
        return self._database()["project_versions"].find_one(
            {"project_id": project_id, "version_number": version_number}, {"_id": 1}
        ) is not None

    def files_of_version(self, project_id, version_number):
        version = self._database()["project_versions"].find_one(
            {"project_id": project_id, "version_number": version_number}
        )
        if not version:
            return []
        ids = [oid for oid in (self._oid(i) for i in version.get("file_ids", [])) if oid is not None]
        docs = self._col("CODE_FILES_COLLECTION", "code_files").find(
            {"_id": {"$in": ids}},
            {"filepath": 1, "filename": 1, "file_type": 1, "analysis_status": 1},
        )
        out = [{
            "file_id": str(d["_id"]),
            "path": d.get("filepath") or d.get("filename") or "",
            "file_type": d.get("file_type") or "unknown",
            "analysis_status": d.get("analysis_status"),
        } for d in docs]
        out.sort(key=lambda f: f["path"])
        return out

    def file_state(self, file_id):
        oid = self._oid(file_id)
        doc = self._col("CODE_FILES_COLLECTION", "code_files").find_one(
            {"_id": oid}, {"analysis_status": 1, "analysis_id": 1}
        ) if oid else None
        if not doc:
            return _file_state(None, False, None)
        has_result = self._find_result(oid, doc.get("analysis_id"), projection={"_id": 1}) is not None
        attempt = self._col("ANALYSIS_JOBS_COLLECTION", "analysis_jobs").find_one(
            {"code_file_id": oid, "started_at": {"$ne": None}}, {"started_at": 1}, sort=[("started_at", -1)]
        )
        return _file_state(doc.get("analysis_status"), has_result, attempt.get("started_at") if attempt else None)

    def analysis_of(self, file_id):
        oid = self._oid(file_id)
        if not oid:
            return None
        doc = self._col("CODE_FILES_COLLECTION", "code_files").find_one({"_id": oid}, {"analysis_id": 1})
        if not doc:
            return None
        result = self._find_result(oid, doc.get("analysis_id"))
        if result:
            result.pop("_id", None)
        return result

    def _find_result(self, file_oid, analysis_id, projection=None):
        results = self._col("ANALYSIS_RESULTS_COLLECTION", "analysis_results")
        if analysis_id is not None:
            found = results.find_one({"_id": analysis_id}, projection)
            if found:
                return found
        return results.find_one({"code_file_id": file_oid}, projection, sort=[("analysis_completed_at", -1)])


_reader = None


def get_reader():
    global _reader
    if _reader is None:
        _reader = MongoAnalysisReader()
    return _reader


def set_reader(reader):
    """Tests install an in-memory reader here; pass None to go back to Mongo."""
    global _reader
    _reader = reader
