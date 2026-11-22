"""S3 workspace: the version's files and the test files that go into a run."""
import io
import tarfile

from core_ai.services.test_generation.sandbox import workspace
from core_ai.services.test_generation.readers import InMemoryAnalysisReader
from core_ai.tests.test_generation.conftest import PROJECT_ID


def job(version=2):
    return {"project_id": PROJECT_ID, "version_number": version}


def test_version_files_keeps_paths_and_content():
    reader = InMemoryAnalysisReader()
    reader.add_file("a", "demo/course.py", content="class Course: pass\n")
    reader.add_file("b", "demo/student.py", content="x = 1\n")
    reader.add_version(PROJECT_ID, 2, ["a", "b"])
    assert workspace.version_files(reader, job()) == {
        "demo/course.py": b"class Course: pass\n", "demo/student.py": b"x = 1\n"}


def test_only_the_jobs_version_is_used_never_a_later_one():
    reader = InMemoryAnalysisReader()
    reader.add_file("old", "demo/course.py", content="old\n")
    reader.add_file("new", "demo/course.py", content="new\n")
    reader.add_version(PROJECT_ID, 2, ["old"])
    reader.add_version(PROJECT_ID, 3, ["new"])
    assert workspace.version_files(reader, job(2)) == {"demo/course.py": b"old\n"}


def test_mongo_reader_gives_one_file_per_path_and_leaves_deleted_out(monkeypatch):
    """The real reader goes through project_versioning.visible_files: newest file per path, no deleted."""
    import core_ai.services.project_versioning as pv

    version = {"file_changes": [
        {"file_id": "1", "filepath": "demo/course.py", "version_number": 1, "status": "unchanged"},
        {"file_id": "2", "filepath": "demo/course.py", "version_number": 2, "status": "modified"},
        {"file_id": "3", "filepath": "demo/main.py", "version_number": 1, "status": "deleted"},
    ]}
    visible = pv.visible_files(version)
    assert [(e["file_id"], e["filepath"]) for e in visible] == [("2", "demo/course.py")]


def test_files_without_content_are_left_out():
    reader = InMemoryAnalysisReader()
    reader.add_file("a", "demo/course.py", content=None)
    reader.add_version(PROJECT_ID, 2, ["a"])
    assert workspace.version_files(reader, job()) == {}


def test_record_test_files_hold_the_tests_and_the_runner_config_only():
    files = workspace.record_test_files([{"test_path": "tests/generated/test_a__unit.py", "test_code": "def test_a(): pass"}])
    assert files == {"pytest.ini": workspace.PYTEST_INI, "generated/test_a__unit.py": b"def test_a(): pass"}
    assert b"pythonpath" not in files["pytest.ini"] or b"src" in files["pytest.ini"]


def test_tar_members_belong_to_the_run_user():
    data = workspace.to_tar({"generated/test_a.py": b"x", "pytest.ini": b"y"})
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        members = {m.name: m for m in tar.getmembers()}
    assert set(members) == {"generated", "generated/test_a.py", "pytest.ini"}
    assert {(m.uid, m.gid) for m in members.values()} == {(10001, 10001)}
    assert members["generated"].isdir() and members["pytest.ini"].mode == 0o644
