import re

from core_ai.services.test_generation.readers import InMemoryAnalysisReader
from core_ai.services.test_generation.repo import InMemoryJobRepo, new_job, new_job_id


def _job(**over):
    base = dict(user_id=7, project_id="p1", version_number=1, paths=[], levels=["unit"], files=[])
    base.update(over)
    return new_job(**base)


def test_job_id_format_and_uniqueness():
    ids = {new_job_id() for _ in range(200)}
    assert len(ids) == 200
    assert all(re.fullmatch(r"job_[0-9a-f]{12}", i) for i in ids)


def test_new_job_starts_pending_and_queued():
    job = _job()
    assert (job["status"], job["stage"]) == ("pending", "queued")
    assert job["user_id"] == "7"          # stored as a string
    assert job["plan"] is None and job["error"] is None


def test_create_get_update_roundtrip():
    repo = InMemoryJobRepo()
    job = repo.create(_job())
    assert repo.get(job["job_id"])["status"] == "pending"
    repo.update(job["job_id"], {"status": "running"})
    assert repo.get(job["job_id"])["status"] == "running"


def test_unknown_job_is_none():
    assert InMemoryJobRepo().get("job_000000000000") is None


def test_repo_returns_copies():
    repo = InMemoryJobRepo()
    job = repo.create(_job())
    fetched = repo.get(job["job_id"])
    fetched["status"] = "tampered"
    assert repo.get(job["job_id"])["status"] == "pending"


def test_reader_versions_and_files():
    reader = InMemoryAnalysisReader()
    reader.add_file("a", "pkg/a.py", analysis={"x": 1})
    reader.add_file("b", "pkg/b.py", analysis_status="PENDING")
    reader.add_version("p1", 1, ["a"])
    reader.add_version("p1", 2, ["a", "b"])       # "a" is unchanged since version 1

    assert reader.latest_version("p1") == 2
    assert reader.latest_version("nope") is None
    assert reader.version_exists("p1", 1) and not reader.version_exists("p1", 3)
    assert [f["path"] for f in reader.files_of_version("p1", 2)] == ["pkg/a.py", "pkg/b.py"]
    assert [f["path"] for f in reader.files_of_version("p1", 1)] == ["pkg/a.py"]


def test_reader_file_state_and_analysis():
    reader = InMemoryAnalysisReader()
    reader.add_file("a", "a.py", analysis={"x": 1})
    reader.add_file("b", "b.py", analysis_status="FAILED")

    assert reader.file_state("a") == {"analysis_status": "COMPLETED", "has_result": True,
                                      "last_attempt_started_at": None}
    assert reader.file_state("b")["has_result"] is False
    assert reader.file_state("missing")["analysis_status"] is None
    assert reader.analysis_of("a") == {"x": 1}
    assert reader.analysis_of("b") is None
