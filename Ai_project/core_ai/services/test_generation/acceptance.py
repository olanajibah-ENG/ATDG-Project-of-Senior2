"""The acceptance gate: the ONLY place where a record becomes `ready` (Principle II).

`accept()` writes `ready` together with its evidence, and only for a verdict that says every test of
the record passed in an isolated run on the job's version. Everything that did not pass goes through
`reject()`, which keeps the real reason. A boundary test checks no other module calls accept_ready().
"""
import hashlib
from datetime import datetime

from core_ai.services.test_generation.statuses import Actor, RecordStatus


class NotAcceptable(ValueError):
    """accept() was called with a verdict that does not prove the record."""


def test_sha256(test_code):
    return hashlib.sha256((test_code or "").encode("utf-8")).hexdigest()


def _last_attempt_n(record):
    attempts = record.get("attempts") or []
    return attempts[-1].get("n") if attempts else None


def _close_attempt(record_repo, record, run_id, outcome, cause=None):
    n = _last_attempt_n(record)
    if n is not None and hasattr(record_repo, "update_attempt"):
        fields = {"run_id": run_id, "outcome": outcome}
        if cause:
            fields["cause"] = cause
        record_repo.update_attempt(record["record_id"], n, fields)


def accept(record_repo, record, *, job, run_id, verdict, duration_s, contribution=None, now=None):
    if not verdict.acceptable:
        raise NotAcceptable(f"{record['record_id']}: verdict {verdict.status}/{verdict.reason} is not a pass")
    passed = sum(1 for t in verdict.tests if t["outcome"] == "passed")
    used = int(record.get("attempts_used") or 0)
    evidence = {
        "run_id": run_id,
        "version_number": job["version_number"],
        "body_hash": record.get("body_hash"),
        "test_sha256": test_sha256(record.get("test_code")),
        "tests": len(verdict.tests),
        "passed": passed,
        "duration_s": round(float(duration_s or 0), 3),
        "accepted_at": now or datetime.utcnow(),
        "repaired": used > 0,
        "attempt": used + 1,
    }
    record_repo.accept_ready(record["record_id"], {
        "reason_code": None, "reason_detail": None, "evidence": evidence,
        "coverage_contribution": contribution,
    })
    _close_attempt(record_repo, record, run_id, "ready")
    return evidence


def reject(record_repo, record, *, verdict, actor=Actor.RUN, run_id=None):
    """Record a run that did not pass (actor run), or a ready record that failed later (final_run, flaky)."""
    if verdict.status not in (RecordStatus.TEST_FAILED, RecordStatus.ENVIRONMENT_ERROR):
        raise ValueError(f"reject() needs a failure status, got {verdict.status}")
    record_repo.transition(record["record_id"], verdict.status, actor, {
        "reason_code": verdict.reason, "reason_detail": verdict.detail,
        "evidence": None, "coverage_contribution": None,
    })
    if actor == Actor.RUN:
        _close_attempt(record_repo, record, run_id, verdict.status, verdict.reason)
