"""The package of a finished job (S3, US5): one ZIP built in memory, never stored.

Only `ready` tests go in. A test that is not `ready` is in no folder of the package; it appears in
records_summary.json with its status and reason. No project source, no secret.
"""
import hashlib
import io
import json
import posixpath
import zipfile

READY_HEADER_OLD = "# status:    generated and checked for form only — NOT RUN YET"
PYTEST_INI = "[pytest]\npythonpath = src\naddopts = -p no:cacheprovider\n"


def bundle_name(job):
    project = (job.get("project_name") or job["project_id"]).replace("/", "_")
    return f"{job['job_id']}_{project}_v{job['version_number']}.zip"


def ready_test_text(record):
    """The test as stored, with its header saying what is now true: it ran and passed."""
    evidence = record.get("evidence") or {}
    new = (f"# status:    ready — passed in isolated run {evidence.get('run_id')} "
           f"on version {evidence.get('version_number')}")
    return (record.get("test_code") or "").replace(READY_HEADER_OLD, new, 1)


def bundle_test_path(record):
    """Where a ready test sits inside the package: tests/generated/<level>/<file>."""
    return f"tests/generated/{record['level']}/{posixpath.basename(record['test_path'])}"


def _json(value):
    return json.dumps(value, ensure_ascii=False, indent=2, default=str).encode("utf-8")


def build_bundle(job, records, final_run):
    """→ (file name, zip bytes)."""
    files = {}
    for record in records:
        if record["status"] == "ready" and record.get("test_path"):
            files[bundle_test_path(record)] = ready_test_text(record).encode("utf-8")

    files["junit_results.xml"] = ((final_run or {}).get("junit_xml") or
                                  '<?xml version="1.0" encoding="utf-8"?><testsuites/>').encode("utf-8")
    files["coverage_report.json"] = _json(job.get("coverage") or {"available": False, "reason": "no_ready_tests"})
    files["plan.json"] = _json(job.get("plan") or {})
    files["records_summary.json"] = _json([{
        "record_id": r["record_id"], "unit_id": r["unit_id"], "level": r["level"], "status": r["status"],
        "reason_code": r.get("reason_code"), "reason_detail": r.get("reason_detail"),
        # the path inside this package (only ready tests are in it)
        "test_path": bundle_test_path(r) if r["status"] == "ready" and r.get("test_path") else None,
        "run_id": r.get("run_id"), "explanation": r.get("explanation"),
        "attempts": [{k: a.get(k) for k in ("n", "purpose", "outcome", "cause")} for a in r.get("attempts") or []],
        "changed_assertions": [c for a in r.get("attempts") or [] for c in a.get("changed_assertions") or []],
    } for r in records])
    files["pytest.ini"] = PYTEST_INI.encode("utf-8")

    manifest = {
        "job_id": job["job_id"], "project_id": job["project_id"], "version_number": job["version_number"],
        "status": job["status"], "final_run_id": job.get("final_run_id"),
        "how_to_run": "copy the code of this version next to this folder as src/, then run: pytest",
        "files": [{"path": path, "sha256": hashlib.sha256(data).hexdigest()} for path, data in sorted(files.items())],
    }
    files["MANIFEST.json"] = _json(manifest)

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, data in sorted(files.items()):
            archive.writestr(path, data)
    return bundle_name(job), buffer.getvalue()
