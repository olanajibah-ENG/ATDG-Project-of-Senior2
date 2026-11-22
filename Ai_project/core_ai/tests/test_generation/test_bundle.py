"""bundle.py: the ZIP of a finished job — only ready tests, a manifest whose hashes match."""
import hashlib
import io
import json
import zipfile

from core_ai.services.test_generation import bundle

HEADER = "# status:    generated and checked for form only — NOT RUN YET"


def rec(rid, unit, status, reason=None):
    r = {"record_id": rid, "unit_id": f"demo/course.py::{unit}", "level": "unit", "status": status,
         "reason_code": reason, "reason_detail": None, "run_id": f"sbx_{rid}",
         "test_path": f"tests/generated/test_demo_course_{unit.replace('.', '_')}__unit.py",
         "test_code": f"# head\n{HEADER}\n\ndef test_x():\n    assert True\n"}
    if status == "ready":
        r["evidence"] = {"run_id": f"sbx_{rid}", "version_number": 10}
    return r


JOB = {"job_id": "job_1", "project_id": "p-1", "version_number": 10, "status": "completed_with_issues",
       "final_run_id": "sbx_final_1", "plan": {"units": [], "skipped": []},
       "coverage": {"available": True, "totals": {"line_pct": 80.0}}}
RECORDS = [rec("t_1", "Course.__init__", "ready"), rec("t_2", "Course.is_full", "test_failed", "assertion"),
           rec("t_3", "Course.add_student", "environment_error", "missing_dependency")]
FINAL = {"junit_xml": "<testsuites><testsuite tests='1'/></testsuites>"}


def open_zip():
    name, data = bundle.build_bundle(JOB, RECORDS, FINAL)
    return name, zipfile.ZipFile(io.BytesIO(data))


def test_name_and_file_list():
    name, z = open_zip()
    assert name == "job_1_p-1_v10.zip"
    assert sorted(z.namelist()) == sorted([
        "MANIFEST.json", "junit_results.xml", "coverage_report.json", "plan.json", "records_summary.json",
        "pytest.ini", "tests/generated/unit/test_demo_course_Course___init____unit.py"])


def test_only_ready_tests_and_failures_only_in_the_summary():
    _, z = open_zip()
    assert not any("is_full" in n or "add_student" in n for n in z.namelist())
    assert not any(n.startswith("tests/quarantine") for n in z.namelist())
    summary = {s["record_id"]: s for s in json.loads(z.read("records_summary.json"))}
    assert (summary["t_2"]["status"], summary["t_2"]["reason_code"], summary["t_2"]["test_path"]) == (
        "test_failed", "assertion", None)
    assert summary["t_3"]["reason_code"] == "missing_dependency"
    assert summary["t_1"]["test_path"] in z.namelist()          # the summary points inside the package


def test_ready_test_header_says_it_ran():
    _, z = open_zip()
    text = z.read("tests/generated/unit/test_demo_course_Course___init____unit.py").decode()
    assert "NOT RUN YET" not in text and "ready — passed in isolated run sbx_t_1 on version 10" in text


def test_manifest_hashes_match_every_file():
    _, z = open_zip()
    manifest = json.loads(z.read("MANIFEST.json"))
    assert manifest["job_id"] == "job_1" and manifest["version_number"] == 10
    listed = {f["path"]: f["sha256"] for f in manifest["files"]}
    assert set(listed) == set(z.namelist()) - {"MANIFEST.json"}
    for path, digest in listed.items():
        assert hashlib.sha256(z.read(path)).hexdigest() == digest


def test_runner_config_results_and_coverage():
    _, z = open_zip()
    ini = z.read("pytest.ini").decode()
    assert "pythonpath = src" in ini and "-p no:cacheprovider" in ini
    assert z.read("junit_results.xml").decode() == FINAL["junit_xml"]
    assert json.loads(z.read("coverage_report.json"))["totals"]["line_pct"] == 80.0


def test_no_source_and_no_secret():
    _, z = open_zip()
    assert not any(n.startswith("src/") for n in z.namelist())
    blob = b"".join(z.read(n) for n in z.namelist()).lower()
    for word in (b"openrouter", b"secret_key", b"password"):
        assert word not in blob
