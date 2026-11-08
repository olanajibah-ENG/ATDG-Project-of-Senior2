"""
اختبارات الخطوة 11: BehaviorAnalyzer (الذكاء الاصطناعي بـ Code vs Code، بس على الدوال المرشّحة).
الـ LLM مزيّف (أجوبة مكتوبة بإيدنا).

    python -m pytest core_ai/tests/test_behavior_analyzer.py -q
"""
import json

import pytest

from core_ai.language_processors.tree_sitter_processor import TreeSitterProcessor
from core_ai.services.conflict_detection import behavior_analyzer as ba
from core_ai.services.conflict_detection.orchestrator import ConflictOrchestrator
from core_ai.services.conflict_detection.schemas import ChangeDecision, ChangeType, RiskLevel

BEFORE = """export function load(path, options = {}) {
  const data = read(path)
  return data
}
export function size(x) {
  return x.length
}"""
AFTER = """export function load(path, options = {}) {
  const data = read(path)
  if (!data) throw new Error('missing')
  return data
}
export function size(x) {
  return x.length
}"""


def analysis(code, lang="javascript"):
    p = TreeSitterProcessor(lang)
    a = p.parse_source_code(code)
    return {"class_diagram_data": p.generate_class_diagram_data(a, p.extract_features(a))}


def fake_llm(monkeypatch, *responses):
    calls = []
    seq = list(responses)

    def call_model(system_prompt, user_prompt, temperature=0.0, use_cache=True, **kw):
        calls.append({"user": user_prompt, "use_cache": use_cache})
        r = seq.pop(0) if len(seq) > 1 else seq[0]
        if isinstance(r, Exception):
            raise r
        return r if isinstance(r, str) else json.dumps(r)
    monkeypatch.setattr(ba.LLMClient, "call_model", staticmethod(call_model))
    return calls


def run(monkeypatch, before=BEFORE, after=AFTER, enabled=True):
    monkeypatch.setenv("BEHAVIOR_LLM_ENABLED", "1" if enabled else "0")
    return ConflictOrchestrator.run_code_vs_code(analysis(before), analysis(after))


def finding(**kw):
    base = {"id": "<module>.load", "before": "returns data", "after": "throws if no data",
            "observable_change": True, "change_type": "error_handling", "breaking": True,
            "explanation": "now throws when the file is empty", "old_snippet": "",
            "new_snippet": "if (!data) throw new Error('missing')", "confidence": 0.9}
    return {"results": [{**base, **kw}]}


# ─────────────────────────────────────────────────────────────────────
# 1. متى بينبعت طلب
# ─────────────────────────────────────────────────────────────────────

def test_no_candidates_no_request(monkeypatch):
    calls = fake_llm(monkeypatch, AssertionError("must not be called"))
    res = run(monkeypatch, BEFORE, BEFORE.replace("// x", ""))          # ما تغيّر شي
    assert calls == [] and res.semantic_conflicts == [] and res.behavior_analysis["requests"] == 0


def test_trivial_change_not_sent(monkeypatch):
    calls = fake_llm(monkeypatch, AssertionError("must not be called"))
    run(monkeypatch, BEFORE, BEFORE.replace("const data = read(path)", "console.log(path)\n  const data = read(path)"))
    assert calls == []


def test_disabled_makes_no_calls(monkeypatch):
    calls = fake_llm(monkeypatch, AssertionError("must not be called"))
    res = run(monkeypatch, enabled=False)
    assert calls == [] and res.behavior_analysis is None


def test_request_contains_before_after_diff_and_only_candidates(monkeypatch):
    calls = fake_llm(monkeypatch, {"results": []})
    run(monkeypatch)
    assert len(calls) == 1
    user = calls[0]["user"]
    assert "ITEM id=<module>.load" in user and "[BEFORE]" in user and "[AFTER]" in user and "[DIFF]" in user
    assert "throw_added" in user                       # الإشارات كتلميح
    assert "ITEM id=<module>.size" not in user         # size ما تغيّرت


# ─────────────────────────────────────────────────────────────────────
# 2. الفلترة
# ─────────────────────────────────────────────────────────────────────

def test_breaking_change_becomes_alert(monkeypatch):
    fake_llm(monkeypatch, finding())
    res = run(monkeypatch)
    assert len(res.semantic_conflicts) == 1
    c = res.semantic_conflicts[0]
    assert c.type == ChangeType.BEHAVIOR_CHANGE and c.risk_level == RiskLevel.CRITICAL
    assert c.category == "behavior_error_handling" and c.member == "load"
    assert c.decision == ChangeDecision.BEHAVIORAL_CANDIDATE and "throw new Error" in c.evidence


def test_invented_quote_is_dropped(monkeypatch):
    fake_llm(monkeypatch, finding(new_snippet="if (data === null) return undefined"))
    res = run(monkeypatch)
    assert res.semantic_conflicts == [] and res.behavior_analysis["dropped_quote"] == 1


def test_quote_needed(monkeypatch):
    fake_llm(monkeypatch, finding(old_snippet="", new_snippet=""))
    assert run(monkeypatch).semantic_conflicts == []


def test_quote_with_line_numbers_accepted(monkeypatch):
    fake_llm(monkeypatch, finding(new_snippet="   3 |   if (!data) throw new Error('missing')"))
    assert len(run(monkeypatch).semantic_conflicts) == 1


@pytest.mark.parametrize("kw, stat", [
    ({"breaking": False}, "non_breaking"),
    ({"confidence": 0.5}, "below_threshold"),
    ({"observable_change": False}, "not_observable"),
])
def test_hidden_findings(monkeypatch, kw, stat):
    fake_llm(monkeypatch, finding(**kw))
    res = run(monkeypatch)
    assert res.semantic_conflicts == [] and res.behavior_analysis[stat] == 1


def test_threshold_from_env(monkeypatch):
    fake_llm(monkeypatch, finding(confidence=0.6))
    monkeypatch.setenv("BEHAVIOR_CONFIDENCE_THRESHOLD", "0.5")
    assert len(run(monkeypatch).semantic_conflicts) == 1


def test_unknown_change_type_becomes_other(monkeypatch):
    fake_llm(monkeypatch, finding(change_type="weird"))
    assert run(monkeypatch).semantic_conflicts[0].category == "behavior_other"


def test_unknown_item_id_ignored(monkeypatch):
    fake_llm(monkeypatch, finding(id="Nope.nothing"))
    res = run(monkeypatch)
    assert res.semantic_conflicts == [] and res.behavior_analysis["unknown_item_ids"] == 1


# ─────────────────────────────────────────────────────────────────────
# 3. الفشل، والتقسيم، وإنه نتائج الخطوات 7-10 بتضل
# ─────────────────────────────────────────────────────────────────────

def test_failure_keeps_structural_results(monkeypatch):
    calls = fake_llm(monkeypatch, ConnectionError("down"))
    before = BEFORE + "\nexport function gone(a) { return a }"
    res = run(monkeypatch, before, AFTER)
    assert len(calls) == 3 and [c["use_cache"] for c in calls] == [True, False, False]
    assert res.behavior_analysis["failed_requests"] == 1 and res.semantic_conflicts == []
    assert any(c.category == "method_removed" for c in res.structural_conflicts)


def test_retry_after_bad_json(monkeypatch):
    fake_llm(monkeypatch, "not json", finding())
    assert len(run(monkeypatch).semantic_conflicts) == 1


def test_large_change_split_into_requests(monkeypatch):
    calls = fake_llm(monkeypatch, {"results": []})
    monkeypatch.setattr(ba, "MAX_REQUEST_CHARS", 600)
    before = "\n".join(f"export function f{i}(x) {{\n  return x + {i}\n}}" for i in range(4))
    after = "\n".join(f"export function f{i}(x) {{\n  if (!x) throw new Error('e{i}')\n  return x + {i}\n}}"
                      for i in range(4))
    run(monkeypatch, before, after)
    assert len(calls) > 1
    joined = "".join(c["user"] for c in calls)
    assert all(f"ITEM id=<module>.f{i}" in joined for i in range(4))
