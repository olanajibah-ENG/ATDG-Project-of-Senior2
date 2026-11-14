"""LLMClient after adding call_model_ex: the old call_model must behave exactly as before.

HTTP is replaced by a fake `requests.post`; nothing leaves the test.
The shared conftest blocks LLMClient.call_model for every test, so the real functions are taken
from the class at import time, before that block is installed.
"""
import pytest

from core_ai.ai_engine import llm_client
from core_ai.ai_engine.llm_client import LLMClient, LLMUnavailable

REAL_CALL_MODEL = LLMClient.__dict__["call_model"].__func__
REAL_CALL_MODEL_EX = LLMClient.__dict__["call_model_ex"].__func__


class FakeResponse:
    def __init__(self, status_code=200, content="ANSWER", usage=None, headers=None):
        self.status_code = status_code
        self._content = content
        self._usage = usage
        self.headers = headers or {}
        self.text = "body"

    def json(self):
        data = {"choices": [{"message": {"content": self._content}}]}
        if self._usage is not None:
            data["usage"] = self._usage
        return data


@pytest.fixture
def http(monkeypatch):
    from django.conf import settings
    from django.core.cache import cache

    cache.clear()
    sent = []
    state = {"response": FakeResponse(usage={"prompt_tokens": 120, "completion_tokens": 80})}

    def fake_post(url, headers=None, json=None, timeout=None):
        sent.append(json)
        response = state["response"]
        return response(json) if callable(response) else response

    monkeypatch.setattr(llm_client.requests, "post", fake_post)
    monkeypatch.setattr(llm_client.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", "test-key", raising=False)
    yield sent, state
    cache.clear()


def test_call_model_still_returns_only_the_text(http):
    sent, _ = http
    assert REAL_CALL_MODEL("sys", "user", use_cache=False) == "ANSWER"
    assert sent[0]["max_tokens"] == 4000 and sent[0]["temperature"] == 0.7
    assert [m["role"] for m in sent[0]["messages"]] == ["system", "user"]


def test_call_model_still_serves_a_repeated_prompt_from_its_cache(http):
    sent, _ = http
    assert REAL_CALL_MODEL("sys", "same prompt") == "ANSWER"
    assert REAL_CALL_MODEL("sys", "same prompt") == "ANSWER"
    assert len(sent) == 1


def test_call_model_ex_returns_text_model_and_tokens(http):
    sent, _ = http
    result = REAL_CALL_MODEL_EX("sys", "user", temperature=0.0, max_tokens=1500)
    assert result == {"text": "ANSWER", "model": sent[0]["model"], "prompt_tokens": 120, "completion_tokens": 80}
    assert sent[0]["temperature"] == 0.0 and sent[0]["max_tokens"] == 1500


def test_call_model_ex_does_not_use_the_cache(http):
    sent, _ = http
    REAL_CALL_MODEL_EX("sys", "same prompt")
    REAL_CALL_MODEL_EX("sys", "same prompt")
    assert len(sent) == 2
    REAL_CALL_MODEL("sys", "same prompt")          # and it did not fill call_model's cache either
    assert len(sent) == 3


def test_missing_usage_gives_zero_tokens(http):
    _, state = http
    state["response"] = FakeResponse(usage=None)
    result = REAL_CALL_MODEL_EX("sys", "user")
    assert (result["prompt_tokens"], result["completion_tokens"]) == (0, 0)


def test_preferred_model_is_tried_first(http):
    sent, _ = http
    REAL_CALL_MODEL_EX("sys", "user", model="vendor/chosen:free")
    assert sent[0]["model"] == "vendor/chosen:free"


def test_next_model_is_tried_when_one_is_rate_limited(http):
    sent, state = http
    first = {"seen": False}

    def respond(payload):
        if not first["seen"]:
            first["seen"] = True
            return FakeResponse(status_code=429)
        return FakeResponse(usage={"prompt_tokens": 1, "completion_tokens": 2})

    state["response"] = respond
    result = REAL_CALL_MODEL_EX("sys", "user")
    assert len(sent) == 2 and sent[0]["model"] != sent[1]["model"]
    assert result["model"] == sent[1]["model"]


def test_all_models_busy_raises_llm_unavailable_which_is_still_an_exception(http):
    _, state = http
    state["response"] = FakeResponse(status_code=429)
    with pytest.raises(LLMUnavailable):
        REAL_CALL_MODEL_EX("sys", "user", force_request=True)
    with pytest.raises(Exception) as info:
        REAL_CALL_MODEL("sys", "user", use_cache=False, force_request=True)
    assert isinstance(info.value, LLMUnavailable) and "busy" in str(info.value)


def test_missing_api_key_raises_llm_unavailable(http, monkeypatch):
    from django.conf import settings

    monkeypatch.setattr(settings, "OPENROUTER_API_KEY", None, raising=False)
    with pytest.raises(LLMUnavailable):
        REAL_CALL_MODEL_EX("sys", "user")
