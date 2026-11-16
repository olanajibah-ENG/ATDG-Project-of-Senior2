from datetime import datetime, timedelta

from core_ai.services.test_generation import gate

NOW = datetime(2026, 11, 13, 12, 0, 0)
DEADLINE = NOW + timedelta(minutes=10)


def _state(status, has_result=False, started=None):
    return {"analysis_status": status, "has_result": has_result, "last_attempt_started_at": started}


def _decide(state, requests=0, requested_at=None, now=NOW, is_python=True):
    return gate.decide(is_python=is_python, file_state=state, analysis_requests=requests,
                       requested_at=requested_at, now=now, deadline=DEADLINE)


def test_non_python_is_skipped_without_any_request():
    d = _decide({}, is_python=False)
    assert (d.action, d.reason) == (gate.SKIP, "unsupported_language")


def test_completed_with_result_is_ready():
    assert _decide(_state("COMPLETED", True)).action == gate.READY
    assert _decide(_state("COMPLETED_WITH_ERRORS", True)).action == gate.READY


def test_running_analysis_waits():
    assert _decide(_state("PENDING")).action == gate.WAIT
    assert _decide(_state("IN_PROGRESS")).action == gate.WAIT


def test_missing_or_failed_analysis_is_requested():
    assert _decide(_state(None)).action == gate.REQUEST
    assert _decide(_state("FAILED")).action == gate.REQUEST
    assert _decide(_state("COMPLETED", has_result=False)).action == gate.REQUEST


def test_request_not_picked_up_yet_waits_instead_of_counting_a_failure():
    # We asked 5 s ago; the worker has not started that attempt, so FAILED is still the OLD failure.
    asked = NOW - timedelta(seconds=5)
    old_attempt = NOW - timedelta(hours=1)
    assert _decide(_state("FAILED", started=old_attempt), requests=1, requested_at=asked).action == gate.WAIT
    assert _decide(_state("FAILED", started=None), requests=1, requested_at=asked).action == gate.WAIT


def test_first_requested_attempt_failed_is_requested_once_more():
    asked = NOW - timedelta(seconds=30)
    attempt = NOW - timedelta(seconds=20)          # started after our request, and it failed
    assert _decide(_state("FAILED", started=attempt), requests=1, requested_at=asked).action == gate.REQUEST


def test_failed_after_two_requests_is_skipped():
    asked = NOW - timedelta(seconds=30)
    attempt = NOW - timedelta(seconds=20)
    d = _decide(_state("FAILED", started=attempt), requests=2, requested_at=asked)
    assert (d.action, d.reason) == (gate.SKIP, "analysis_failed")


def test_past_the_deadline_a_waiting_file_is_skipped():
    late = DEADLINE + timedelta(seconds=1)
    for state, kwargs in [
        (_state("PENDING"), {}),
        (_state("IN_PROGRESS"), {}),
        (_state("FAILED"), {"requests": 1, "requested_at": NOW}),
        (_state(None), {}),
    ]:
        d = _decide(state, now=late, **kwargs)
        assert (d.action, d.reason) == (gate.SKIP, "analysis_failed")


def test_ready_file_stays_ready_after_the_deadline():
    assert _decide(_state("COMPLETED", True), now=DEADLINE + timedelta(hours=1)).action == gate.READY
