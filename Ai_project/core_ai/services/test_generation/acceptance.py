"""The acceptance gate: the ONLY place where a record becomes `ready` (Principle II).

`accept()` writes `ready` together with its evidence, and only for a verdict that says every test of
the record passed in an isolated run on the job's version. Everything that did not pass goes through
`reject()`, which keeps the real reason. A boundary test checks no other module calls accept_ready().
"""
import hashlib
from datetime import datetime

from core_ai.services.test_generation.statuses import RecordStatus


class NotAcceptable(ValueError):
    """accept() was called with a verdict that does not prove the record."""


def test_sha256(test_code):
    return hashlib.sha256((test_code or "").encode("utf-8")).hexdigest()


def accept(record_repo, record, *, job, run_id, verdict, duration_s, contribution=None, now=None):
    if not verdict.acceptable:
        raise NotAcceptable(f"{record['record_id']}: verdict {verdict.status}/{verdict.reason} is not a pass")
    passed = sum(1 for t in verdict.tests if t["outcome"] == "passed")
    evidence = {
        "run_id": run_id,
        "version_number": job["version_number"],
        "body_hash": record.get("body_hash"),
        "test_sha256": test_sha256(record.get("test_code")),
        "tests": len(verdict.tests),
        "passed": passed,
        "duration_s": round(float(duration_s or 0), 3),
        "accepted_at": now or datetime.utcnow(),
    }
    record_repo.accept_ready(record["record_id"], {
        "reason_code": None, "reason_detail": None, "evidence": evidence,
        "coverage_contribution": contribution,
    })
    return evidence


def reject(record_repo, record, *, verdict):
    """Record a run that did not pass (or a ready record that failed with the others)."""
    if verdict.status not in (RecordStatus.TEST_FAILED, RecordStatus.ENVIRONMENT_ERROR):
        raise ValueError(f"reject() needs a failure status, got {verdict.status}")
    record_repo.update(record["record_id"], {
        "status": verdict.status, "reason_code": verdict.reason, "reason_detail": verdict.detail,
        "evidence": None, "coverage_contribution": None,
    })
