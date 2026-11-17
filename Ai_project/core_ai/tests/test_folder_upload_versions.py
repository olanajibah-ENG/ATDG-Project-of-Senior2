"""The upload view end to end, on a small in-memory stand-in for MongoDB.

Replays the scenario that showed the bug: a project is uploaded (version 1), then uploaded again
with course.py modified (version 2). Before the fix, version 2 listed course.py twice and the tree
pointed at the old one.
"""
import io
import os
import zipfile

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Ai_project.settings")
import django  # noqa: E402

django.setup()

import pytest  # noqa: E402
from bson import ObjectId  # noqa: E402
from django.core.files.uploadedfile import SimpleUploadedFile  # noqa: E402
from rest_framework.test import APIRequestFactory  # noqa: E402

from core_ai.views import folder_upload, project_tree_view  # noqa: E402

STUDENT = "from course import Course\n\nclass Student:\n    def enroll(self, c: Course):\n        c.add_student(self)\n"
COURSE_V1 = "class Course:\n    def add_student(self, s):\n        pass\n"
COURSE_V2 = "class Course:\n    def is_full(self):\n        return False\n\n    def add_student(self, s):\n        pass\n"
MAIN = "from student import Student\n\ndef register():\n    return Student()\n"
INIT = ""


# ── a minimal MongoDB stand-in ───────────────────────────────────────────────

def _matches(doc, query):
    for key, want in query.items():
        have = doc.get(key)
        if isinstance(want, dict) and "$in" in want:
            if have not in want["$in"]:
                return False
        elif have != want:
            return False
    return True


class _Inserted:
    def __init__(self, inserted_id):
        self.inserted_id = inserted_id


class FakeCollection:
    def __init__(self):
        self.docs = []

    def insert_one(self, doc):
        doc = dict(doc)
        doc.setdefault("_id", ObjectId())
        self.docs.append(doc)
        return _Inserted(doc["_id"])

    def find(self, query=None, projection=None, sort=None):
        rows = [dict(d) for d in self.docs if _matches(d, query or {})]
        for key, direction in reversed(sort or []):
            rows.sort(key=lambda d: d.get(key) or 0, reverse=direction < 0)
        return rows

    def find_one(self, query=None, projection=None, sort=None):
        rows = self.find(query, projection, sort)
        return rows[0] if rows else None


class FakeDB(dict):
    def __missing__(self, name):
        self[name] = FakeCollection()
        return self[name]


@pytest.fixture
def db(monkeypatch):
    fake = FakeDB()
    monkeypatch.setattr(folder_upload, "get_mongo_db", lambda: fake)
    monkeypatch.setattr(project_tree_view, "get_mongo_db", lambda: fake)
    monkeypatch.setattr(folder_upload, "save_to_gridfs", lambda **kw: str(ObjectId()))

    class _NoAnalysis:
        @staticmethod
        def delay(file_id):
            return None

    monkeypatch.setattr(folder_upload, "analyze_code_file_task", _NoAnalysis)
    return fake


# ── helpers ──────────────────────────────────────────────────────────────────

factory = APIRequestFactory()
PROJECT = "proj-1"


def zip_of(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        for path, text in files.items():
            z.writestr(path, text)
    return SimpleUploadedFile("project.zip", buffer.getvalue(), content_type="application/zip")


def upload(data_files=None, zip_files=None, **fields):
    data = {"project_name": "demo", "upm_project_id": PROJECT, "user_email": "x@example.com", **fields}
    if zip_files is not None:
        data["file"] = zip_of(zip_files)
    if data_files:
        data["files"] = [SimpleUploadedFile(name, text.encode()) for name, text in data_files]
    response = folder_upload.FolderUploadView.as_view()(factory.post("/x", data, format="multipart"))
    response.render()
    return response


def tree(version):
    request = factory.get(f"/x?version={version}")
    response = project_tree_view.ProjectTreeView.as_view()(request, upm_project_id=PROJECT)
    response.render()
    return response.data


def by_path(flat):
    return {f["filepath"]: f for f in flat}


V1 = {"demo/student.py": STUDENT, "demo/course.py": COURSE_V1, "demo/main.py": MAIN}
V2 = {"demo/student.py": STUDENT, "demo/course.py": COURSE_V2, "demo/main.py": MAIN}


# ── the scenario that showed the bug ─────────────────────────────────────────

def test_modified_file_appears_once_and_the_tree_points_at_the_new_one(db):
    r1 = upload(zip_files=V1)
    assert r1.status_code == 201 and r1.data["upload_mode"] == "full"
    ids_v1 = {f["filepath"]: f["file_id"] for f in r1.data["files"]}

    r2 = upload(zip_files=V2)
    assert r2.status_code == 201 and r2.data["version_number"] == 2
    assert r2.data["version_files"] == 3
    assert r2.data["changes"] == {"total_files": 3, "new_files": 0, "modified_files": 1,
                                  "unchanged_files": 2, "deleted_files": 0}
    ids_v2 = {f["filepath"]: f["file_id"] for f in r2.data["files"]}
    assert ids_v2["demo/student.py"] == ids_v1["demo/student.py"]       # reused, not re-analysed
    assert ids_v2["demo/main.py"] == ids_v1["demo/main.py"]
    assert ids_v2["demo/course.py"] != ids_v1["demo/course.py"]

    version2 = db["project_versions"].find_one({"version_number": 2})
    assert len(version2["file_ids"]) == 3

    t2 = tree(2)
    flat = by_path(t2["flat_files"])
    assert len(t2["flat_files"]) == 3
    assert flat["demo/course.py"]["file_id"] == ids_v2["demo/course.py"]
    assert flat["demo/course.py"]["status"] == "modified"
    assert flat["demo/student.py"]["status"] == "unchanged"
    assert t2["tree"]["demo"]["children"]["course.py"]["file_id"] == ids_v2["demo/course.py"]
    assert t2["deleted_files"] == []

    t1 = tree(1)                                                         # version 1 is untouched
    assert by_path(t1["flat_files"])["demo/course.py"]["file_id"] == ids_v1["demo/course.py"]


def test_test_generation_reads_one_file_per_path(db):
    from core_ai.services.test_generation.readers import MongoAnalysisReader

    upload(zip_files=V1)
    r2 = upload(zip_files=V2)
    files = MongoAnalysisReader(db=db).files_of_version(PROJECT, 2)
    assert [f["path"] for f in files] == ["demo/course.py", "demo/main.py", "demo/student.py"]
    course = next(f for f in files if f["path"] == "demo/course.py")
    assert course["file_id"] == next(f["file_id"] for f in r2.data["files"] if f["filepath"] == "demo/course.py")


# ── deletion ─────────────────────────────────────────────────────────────────

def test_zip_without_a_file_deletes_it(db):
    upload(zip_files=V1)
    r2 = upload(zip_files={"demo/student.py": STUDENT, "demo/course.py": COURSE_V1})
    assert r2.data["deleted"] == ["demo/main.py"] and r2.data["version_files"] == 2
    t2 = tree(2)
    assert "demo/main.py" not in by_path(t2["flat_files"])
    assert [d["filepath"] for d in t2["deleted_files"]] == ["demo/main.py"]
    assert "main.py" not in t2["tree"]["demo"]["children"]
    assert "demo/main.py" in by_path(tree(1)["flat_files"])               # still in version 1


def test_loose_files_change_only_what_was_sent(db):
    upload(zip_files=V1)
    r2 = upload(data_files=[("course.py", COURSE_V2)], paths='["demo/course.py"]')
    assert r2.status_code == 201 and r2.data["upload_mode"] == "partial"
    flat = by_path(tree(2)["flat_files"])
    assert set(flat) == {"demo/student.py", "demo/course.py", "demo/main.py"}
    assert flat["demo/course.py"]["status"] == "modified"


def test_partial_upload_can_only_delete(db):
    upload(zip_files=V1)
    r2 = upload(upload_mode="partial", deleted_paths='["demo/main.py"]')
    assert r2.status_code == 201 and r2.data["deleted"] == ["demo/main.py"]
    assert set(by_path(tree(2)["flat_files"])) == {"demo/student.py", "demo/course.py"}


def test_rename_from_github(db):
    upload(zip_files=V1)
    upload(data_files=[("enrolment.py", STUDENT)], paths='["demo/enrolment.py"]',
           upload_mode="partial", deleted_paths='["demo/student.py"]')
    t2 = tree(2)
    assert set(by_path(t2["flat_files"])) == {"demo/enrolment.py", "demo/course.py", "demo/main.py"}
    assert [d["filepath"] for d in t2["deleted_files"]] == ["demo/student.py"]


def test_github_paths_keep_their_folders(db):
    r = upload(data_files=[("models.py", COURSE_V1)], paths='["src/app/models.py"]')
    assert [f["filepath"] for f in r.data["files"]] == ["src/app/models.py"]


def test_paths_must_match_the_files(db):
    r = upload(data_files=[("a.py", MAIN), ("b.py", MAIN)], paths='["only/one.py"]')
    assert r.status_code == 400


# ── identity is the path ─────────────────────────────────────────────────────

def test_two_paths_with_the_same_content_stay_two_files(db):
    r = upload(zip_files={"pkg_a/__init__.py": INIT, "pkg_b/__init__.py": INIT, "pkg_a/m.py": MAIN})
    ids = {f["filepath"]: f["file_id"] for f in r.data["files"]}
    assert ids["pkg_a/__init__.py"] != ids["pkg_b/__init__.py"]
    assert len(by_path(tree(1)["flat_files"])) == 3


def test_reverting_a_file_is_reported_as_modified(db):
    upload(zip_files=V1)
    upload(zip_files=V2)
    r3 = upload(zip_files=V1)
    assert r3.data["changes"]["modified_files"] == 1
    assert by_path(tree(3)["flat_files"])["demo/course.py"]["status"] == "modified"


# ── data saved before the fix ────────────────────────────────────────────────

def test_a_version_saved_with_a_duplicate_is_shown_correctly(db):
    new, old = str(ObjectId()), str(ObjectId())
    db["project_versions"].insert_one({
        "project_id": PROJECT, "project_name": "demo", "version_number": 2,
        "file_ids": [new, old],
        "file_changes": [
            {"file_id": new, "filename": "course.py", "filepath": "demo/course.py", "file_type": "python",
             "version_number": 2, "status": "new_or_modified"},
            {"file_id": old, "filename": "course.py", "filepath": "demo/course.py", "file_type": "python",
             "version_number": 1, "status": "unchanged"},
        ],
    })
    t = tree(2)
    assert [f["file_id"] for f in t["flat_files"]] == [new]
    assert t["tree"]["demo"]["children"]["course.py"]["file_id"] == new
