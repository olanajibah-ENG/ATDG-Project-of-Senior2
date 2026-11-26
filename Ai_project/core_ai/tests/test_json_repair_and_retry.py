"""
اختبارات تحسينات ما بعد تحليل CASCADE:
  1. إعادة المحاولة بأداة القياس بتطلب جواب جديد فعلاً (وبتضل قابلة للتكرار).
  2. قراءة JSON متساهلة لأجوبة الموديل يلي فيها كلام "تفكير" بالنص.

    python -m pytest core_ai/tests/test_json_repair_and_retry.py -q
"""
import json

import pytest

from core_ai.services.conflict_detection.doc_semantic_analyzer import parse_response, repair_json
from evaluation.harness import evaluate as ev
from evaluation.harness.llm_recorder import LLMCallError, LLMClient as Recorder

# ─────────────────────────────────────────────────────────────────────
# 2. قراءة JSON متساهلة — أمثلة حقيقية من أجوبة cohere/north-mini-code على CASCADE
# ─────────────────────────────────────────────────────────────────────

REAL_STRAY_LINE = """{
  "results": [
    {
      "id": "A.f",
      "not_implemented": [],
      "conflicting": [],
      probably missing a comma? Actually we need to ensure
      "undocumented": []
    }
  ]
}"""

REAL_STRAY_PREFIX = """{
  "results": [
    {
      "id": "A.f",
      "not_implemented": [],
      probably: "conflicting": [
        {"doc_snippet": "x", "code_snippet": "y", "confidence": 0.9}
      ],
      "undocumented": []
    }
  ]
}"""

TRAILING_COMMA = '{"results": [{"id": "A.f", "conflicting": [], "undocumented": [],}],}'


@pytest.mark.parametrize("raw", [REAL_STRAY_LINE, REAL_STRAY_PREFIX, TRAILING_COMMA])
def test_broken_answers_are_repaired(raw):
    with pytest.raises(json.JSONDecodeError):
        json.loads(raw)                                   # قبل: ما بينقرا
    data = parse_response(raw)                            # هلق: بينقرا
    assert data["results"][0]["id"] == "A.f"


def test_repair_keeps_values():
    data = parse_response(REAL_STRAY_PREFIX)
    assert data["results"][0]["conflicting"][0] == {"doc_snippet": "x", "code_snippet": "y", "confidence": 0.9}


def test_valid_json_untouched_and_literals_kept():
    raw = '{"results": [{"id": "A.f", "flag": true, "x": null,\n  "y": false}]}'
    assert parse_response(raw) == json.loads(raw)
    assert repair_json('{\n  "a": 1,\n  true\n}').count("true") == 1      # سطر true ما بينشال


def test_really_broken_still_fails():
    with pytest.raises(json.JSONDecodeError):
        parse_response('{"results": [{"id": "A.f", "conflicting": [ {"doc_snippet": "x" "code": 1} ]}]}')


# ─────────────────────────────────────────────────────────────────────
# 1. إعادة المحاولة بأداة القياس
# ─────────────────────────────────────────────────────────────────────

@pytest.fixture
def replay(tmp_path, monkeypatch):
    """أداة القياس مع حفظ بمجلد مؤقت، وموديل مزيّف بيعدّ الطلبات الحقيقية."""
    live = {"n": 0}

    def fake_live(system_prompt, user_prompt, **kw):
        live["n"] += 1
        Recorder._calls.append({"ok": True, "served_model": "fake"})
        return f"answer-{live['n']}"

    monkeypatch.setattr(ev, "LLM_CACHE", tmp_path)
    monkeypatch.setattr(Recorder, "call_model", staticmethod(fake_live))
    monkeypatch.setattr(Recorder, "model", "fake/model")
    monkeypatch.setattr(Recorder, "offline", False)
    monkeypatch.setattr(Recorder, "_calls", [])
    Recorder.start_sample("s1")
    return live


def test_retry_asks_for_a_new_answer(replay):
    ev._enable_replay_cache()
    first = Recorder.call_model("sys", "user", use_cache=True)
    retry = Recorder.call_model("sys", "user", use_cache=False)
    assert first == "answer-1" and retry == "answer-2" and replay["n"] == 2   # قبل: retry == answer-1


def test_rerun_replays_every_attempt_for_free(replay):
    ev._enable_replay_cache()
    run1 = [Recorder.call_model("sys", "user", use_cache=c) for c in (True, False, False)]
    ev._enable_replay_cache()                              # تشغيل تاني للقياس (عدّاد جديد)
    Recorder.start_sample("s1")
    calls_before = replay["n"]
    run2 = [Recorder.call_model("sys", "user", use_cache=c) for c in (True, False, False)]
    assert run2 == run1 and replay["n"] == calls_before      # نفس الأجوبة، وبدون ولا طلب


def test_replay_only_never_calls_the_model(replay):
    ev._enable_replay_cache(replay_only=True)
    with pytest.raises(LLMCallError):
        Recorder.call_model("sys", "never asked", use_cache=True)
    assert replay["n"] == 0
