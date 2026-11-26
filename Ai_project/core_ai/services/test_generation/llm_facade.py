"""The one door to the language model.

This is the only module of core_ai.services.test_generation allowed to import the model client (checked by
tests/test_boundaries.py). Every request made through it is recorded as an attempt: who it was
for, which model answered, what it cost and how long it took.
"""
import time
from dataclasses import dataclass

from core_ai.services.test_generation.records import new_attempt


class ModelUnavailable(Exception):
    """The model could not answer for a reason that has nothing to do with the unit: every model
    busy, quota used up, no API key, network down."""


@dataclass
class LLMResult:
    text: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    attempt_id: str
    reused: bool = False


def default_client():
    """The service's real client. Imported lazily so tests never load it by accident."""
    from core_ai.ai_engine.llm_client import LLMClient

    return LLMClient.call_model_ex


class LLMFacade:
    def __init__(self, client, attempt_repo, *, max_tokens=2000, model=None):
        self._client = client
        self._attempts = attempt_repo
        self._max_tokens = max_tokens
        self._model = model

    def complete(self, *, job_id, record_id, unit_id, level, purpose, system, user,
                 request_hash, prompt_version, repair_of=None):
        attempt = new_attempt(job_id=job_id, record_id=record_id, unit_id=unit_id, level=level,
                              purpose=purpose, prompt_version=prompt_version, request_hash=request_hash)
        if repair_of is not None:
            attempt['repair_of'] = repair_of
        started = time.monotonic()
        try:
            answer = self._client(system, user, model=self._model, temperature=0.0,
                                  max_tokens=self._max_tokens)
        except Exception as exc:  # the client raises plain exceptions for every "cannot answer" case
            attempt["duration_ms"] = int((time.monotonic() - started) * 1000)
            attempt["outcome"] = "model_unavailable"
            attempt["error"] = str(exc)[:500]
            self._attempts.add(attempt)
            raise ModelUnavailable(str(exc)) from exc

        attempt.update(
            duration_ms=int((time.monotonic() - started) * 1000),
            outcome="answered",
            model=answer.get("model"),
            prompt_tokens=int(answer.get("prompt_tokens") or 0),
            completion_tokens=int(answer.get("completion_tokens") or 0),
            answer_text=answer.get("text") or "",
        )
        self._attempts.add(attempt)
        return LLMResult(text=attempt["answer_text"], model=attempt["model"],
                         prompt_tokens=attempt["prompt_tokens"],
                         completion_tokens=attempt["completion_tokens"],
                         attempt_id=attempt["attempt_id"])

    def reuse(self, earlier, *, job_id, record_id, unit_id, level, purpose, request_hash, prompt_version, repair_of=None):
        """Records that an earlier answer was used again. No request is sent."""
        attempt = new_attempt(job_id=job_id, record_id=record_id, unit_id=unit_id, level=level,
                              purpose=purpose, prompt_version=prompt_version, request_hash=request_hash)
        if repair_of is not None:
            attempt['repair_of'] = repair_of
        attempt.update(reused=True, outcome="answered", model=earlier.get("model"),
                       answer_text=earlier.get("answer_text"))
        self._attempts.add(attempt)
        return LLMResult(text=earlier.get("answer_text") or "", model=earlier.get("model"),
                         prompt_tokens=0, completion_tokens=0,
                         attempt_id=attempt["attempt_id"], reused=True)
