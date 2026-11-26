"""Analysis gate — one decision per selected file, no I/O.

Rules (specs/001-test-job-plan/research.md, R2):
  not Python                              → skip  unsupported_language
  analysed, result present                → ready
  being analysed                          → wait
  no analysis / failed, < 2 requests made → request analysis (then wait)
  failed after 2 requests                 → skip  analysis_failed
  still not complete at the deadline      → skip  analysis_failed

A request made by this job is "outstanding" until an analysis attempt that started after the
request shows up. While it is outstanding the file's old FAILED status says nothing new, so we wait.
"""
from dataclasses import dataclass
from typing import Optional

from core_ai.services.test_generation.statuses import SkipReason

READY = "ready"
WAIT = "wait"
REQUEST = "request_analysis"
SKIP = "skip"

MAX_ANALYSIS_REQUESTS = 2

_DONE = ("COMPLETED", "COMPLETED_WITH_ERRORS")
_RUNNING = ("PENDING", "IN_PROGRESS")


@dataclass
class Decision:
    action: str
    reason: Optional[str] = None


def decide(*, is_python, file_state, analysis_requests, requested_at, now, deadline):
    if not is_python:
        return Decision(SKIP, SkipReason.UNSUPPORTED_LANGUAGE)

    status = file_state.get("analysis_status")
    if status in _DONE and file_state.get("has_result"):
        return Decision(READY)

    past_deadline = deadline is not None and now >= deadline

    request_outstanding = False
    if requested_at is not None:
        started = file_state.get("last_attempt_started_at")
        request_outstanding = started is None or started < requested_at

    if status in _RUNNING or request_outstanding:
        return Decision(SKIP, SkipReason.ANALYSIS_FAILED) if past_deadline else Decision(WAIT)

    # Here the file has no usable analysis: never analysed, failed, or "done" with no result.
    if analysis_requests >= MAX_ANALYSIS_REQUESTS or past_deadline:
        return Decision(SKIP, SkipReason.ANALYSIS_FAILED)
    return Decision(REQUEST)
