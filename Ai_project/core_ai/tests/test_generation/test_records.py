import re

import pytest

from core_ai.services.test_generation.llm_facade import LLMFacade, ModelUnavailable
from core_ai.services.test_generation.records import InMemoryAttemptRepo, InMemoryRecordRepo, new_attempt, new_record

UNIT_A = {"id": "a.py::f", "file": "a.py", "body_hash": "h1"}
UNIT_B = {"id": "b.py::g", "file": "b.py", "body_hash": "h2"}


def _filled():
    repo = InMemoryRecordRepo()
    repo.create_many([new_record("job_1", unit, level) for unit in (UNIT_A, UNIT_B) for level in ("unit", "edge")])
    repo.create_many([new_record("job_2", UNIT_A, "unit")])
    return repo


# ── records ──────────────────────────────────────────────────────────────────

def test_new_record_shape():
    record = new_record("job_1", UNIT_A, "unit")
    assert re.fullmatch(r"t_[0-9a-f]{10}", record["record_id"])
    assert (record["status"], record["level"], record["unit_id"], record["file"]) == ("pending", "unit", "a.py::f", "a.py")
    assert record["body_hash"] == "h1" and record["test_code"] is None and record["reused"] is False


def test_list_and_filters():
    repo = _filled()
    assert len(repo.list("job_1")) == 4
    assert len(repo.list("job_1", level="unit")) == 2
    assert [r["file"] for r in repo.list("job_1", path="b.py")] == ["b.py", "b.py"]
    assert len(repo.list("job_1", level="unit", path="a.py")) == 1
    assert repo.list("job_1", status="generated") == []
    assert len(repo.list("job_2")) == 1


def test_next_pending_follows_plan_order_and_level():
    repo = _filled()
    first = repo.next_pending("job_1", "unit")
    assert first["unit_id"] == "a.py::f"
    repo.transition(first["record_id"], "generated", "generate")
    assert repo.next_pending("job_1", "unit")["unit_id"] == "b.py::g"
    repo.transition(repo.next_pending("job_1", "unit")["record_id"], "generation_failed", "generate")
    assert repo.next_pending("job_1", "unit") is None
    assert repo.next_pending("job_1", "edge") is not None


def test_get_update_and_counts():
    repo = _filled()
    record = repo.list("job_1")[0]
    repo.transition(record["record_id"], "generated", "generate", {"test_path": "tests/generated/x.py"})
    assert repo.get(record["record_id"])["test_path"] == "tests/generated/x.py"
    assert repo.get("t_0000000000") is None
    counts = repo.counts("job_1")
    assert (counts["generated"], counts["pending"], counts["ready"]) == (1, 3, 0)
    assert sum(counts.values()) == 4


# ── attempts ─────────────────────────────────────────────────────────────────

def _attempt(request_hash, answer=None):
    attempt = new_attempt(job_id="job_1", record_id="t_1", unit_id="a.py::f", level="unit",
                          purpose="generate", prompt_version="unit-v1", request_hash=request_hash)
    attempt["answer_text"] = answer
    return attempt


def test_find_reusable_returns_the_latest_answer_and_ignores_empty_ones():
    repo = InMemoryAttemptRepo()
    repo.add(_attempt("h", "first"))
    repo.add(_attempt("h", None))            # a failed request has no answer
    repo.add(_attempt("other", "x"))
    assert repo.find_reusable("h")["answer_text"] == "first"
    repo.add(_attempt("h", "second"))
    assert repo.find_reusable("h")["answer_text"] == "second"
    assert repo.find_reusable("unknown") is None


# ── the facade ───────────────────────────────────────────────────────────────

COMMON = dict(job_id="job_1", record_id="t_1", unit_id="a.py::f", level="unit", purpose="generate",
              request_hash="hash1", prompt_version="unit-v1")


def test_facade_calls_the_client_deterministically_and_records_the_attempt():
    seen = {}

    def client(system, user, *, model=None, temperature=None, max_tokens=None):
        seen.update(system=system, user=user, model=model, temperature=temperature, max_tokens=max_tokens)
        return {"text": "ANSWER", "model": "vendor/model", "prompt_tokens": 120, "completion_tokens": 80}

    attempts = InMemoryAttemptRepo()
    result = LLMFacade(client, attempts, max_tokens=1500, model="vendor/model").complete(
        system="SYS", user="USR", **COMMON)

    assert seen == {"system": "SYS", "user": "USR", "model": "vendor/model", "temperature": 0.0, "max_tokens": 1500}
    assert (result.text, result.model, result.prompt_tokens, result.completion_tokens) == ("ANSWER", "vendor/model", 120, 80)
    assert result.reused is False

    (attempt,) = attempts.list("job_1")
    assert attempt["attempt_id"] == result.attempt_id and re.fullmatch(r"a_[0-9a-f]{10}", attempt["attempt_id"])
    assert (attempt["purpose"], attempt["outcome"], attempt["reused"]) == ("generate", "answered", False)
    assert (attempt["model"], attempt["prompt_tokens"], attempt["completion_tokens"]) == ("vendor/model", 120, 80)
    assert attempt["request_hash"] == "hash1" and attempt["prompt_version"] == "unit-v1"
    assert attempt["answer_text"] == "ANSWER" and attempt["duration_ms"] >= 0


@pytest.mark.parametrize("error", [RuntimeError("All free models are busy"), ConnectionError("network down"),
                                   Exception("OPENROUTER_API_KEY missing in settings.")])
def test_any_failure_to_answer_becomes_model_unavailable_and_is_recorded(error):
    def client(system, user, **kwargs):
        raise error

    attempts = InMemoryAttemptRepo()
    with pytest.raises(ModelUnavailable):
        LLMFacade(client, attempts).complete(system="S", user="U", **COMMON)
    (attempt,) = attempts.list("job_1")
    assert attempt["outcome"] == "model_unavailable" and attempt["answer_text"] is None
    assert attempts.find_reusable("hash1") is None          # a failed request is never reused


def test_reuse_records_an_attempt_without_calling_the_client():
    def client(*args, **kwargs):
        raise AssertionError("the client must not be called for a reuse")

    attempts = InMemoryAttemptRepo()
    earlier = {"answer_text": "OLD", "model": "vendor/model"}
    result = LLMFacade(client, attempts).reuse(earlier, **COMMON)
    assert (result.text, result.model, result.reused, result.prompt_tokens) == ("OLD", "vendor/model", True, 0)
    (attempt,) = attempts.list("job_1")
    assert attempt["reused"] is True and attempt["prompt_tokens"] == 0 and attempt["completion_tokens"] == 0
