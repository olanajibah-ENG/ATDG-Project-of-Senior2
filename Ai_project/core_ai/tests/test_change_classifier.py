"""
اختبارات الخطوة 9: ChangeClassifier (قرار لكل دالة: توقيع × جسم، فلترة التغييرات التافهة، ودرجة الأهمية).

    python -m pytest core_ai/tests/test_change_classifier.py -q
"""
import pytest

from core_ai.language_processors.python_processor import PythonProcessor
from core_ai.language_processors.tree_sitter_processor import TreeSitterProcessor
from core_ai.services.conflict_detection.change_classifier import ChangeClassifier, priority, trivial_reason
from core_ai.services.conflict_detection.orchestrator import ConflictOrchestrator
from core_ai.services.conflict_detection.schemas import BodyChange, ChangeDecision, ChangeType


def analysis(code, lang="javascript"):
    p = PythonProcessor() if lang == "python" else TreeSitterProcessor(lang)
    a = p.parse_source_code(code)
    return {"class_diagram_data": p.generate_class_diagram_data(a, p.extract_features(a))}


def run(before, after, lang="javascript"):
    return ConflictOrchestrator.run_code_vs_code(analysis(before, lang), analysis(after, lang))


def body_of(res, member):
    return next(b for b in res.body_changes if b.member == member)


def fn(body, sig="(x)"):
    return f"export function f{sig} {{\n{body}\n}}"


# ─────────────────────────────────────────────────────────────────────
# 1. القرار: توقيع × جسم
# ─────────────────────────────────────────────────────────────────────

def test_no_change():
    res = run(fn("  return x"), fn("  // same\n  return x"))
    assert body_of(res, "f").decision == ChangeDecision.NO_CHANGE.value


def test_behavioral_candidate():
    b = body_of(run(fn("  return x"), fn("  if (!x) throw new Error('no')\n  return x")), "f")
    assert b.decision == ChangeDecision.BEHAVIORAL_CANDIDATE.value and b.priority > 0


def test_structural_only():
    res = run(fn("  return x", "(x)"), fn("  return x", "(x, y)"))
    assert body_of(res, "f").decision == ChangeDecision.STRUCTURAL_ONLY.value
    sig = next(c for c in res.structural_conflicts if c.category == "method_signature_changed")
    assert sig.decision == ChangeDecision.STRUCTURAL_ONLY


def test_structural_and_behavioral():
    res = run(fn("  return x", "(x)"), fn("  return x * y", "(x, y)"))
    assert body_of(res, "f").decision == ChangeDecision.STRUCTURAL_AND_BEHAVIORAL.value
    sig = next(c for c in res.structural_conflicts if c.category == "method_signature_changed")
    assert sig.decision == ChangeDecision.STRUCTURAL_AND_BEHAVIORAL


def test_removed_method_is_structural_only():
    res = run("export class A { f() { return 1 } g() { return 2 } }", "export class A { f() { return 1 } }")
    removed = next(c for c in res.structural_conflicts if c.category == "method_removed")
    assert removed.decision == ChangeDecision.STRUCTURAL_ONLY


def test_unknown_body_never_sent():
    b = BodyChange(class_name="A", member="f", status="unknown")
    assert ChangeClassifier.classify(b, signature_changed=False).decision == ChangeDecision.NO_CHANGE.value
    assert ChangeClassifier.classify(b, signature_changed=True).decision == ChangeDecision.STRUCTURAL_ONLY.value


# ─────────────────────────────────────────────────────────────────────
# 2. التغييرات التافهة
# ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("before, after, reason", [
    ("  return x", "  console.log('got', x)\n  return x", "logging_only"),
    ("  logger.debug(x)\n  return x", "  this.logger.info('x=' + x)\n  return x", "logging_only"),
    ("  if (!x) throw new Error('bad id')\n  return x", "  if (!x) throw new Error('invalid id')\n  return x",
     "message_only"),
    ("  const r = g(x)\n  return r", "  const res = g(x)\n  return res", "local_rename_only"),
])
def test_trivial_changes(before, after, reason):
    b = body_of(run(fn(before), fn(after)), "f")
    assert b.trivial_reason == reason and b.decision == ChangeDecision.NO_CHANGE.value and b.priority == 0


def test_one_real_line_makes_it_not_trivial():
    # سطر طباعة + سطر منطق → مش تافه
    b = body_of(run(fn("  return x"), fn("  console.log(x)\n  return x + 1")), "f")
    assert b.trivial_reason is None and b.decision == ChangeDecision.BEHAVIORAL_CANDIDATE.value


def test_property_or_call_rename_is_not_local_rename():
    # options.timeout → options.delay = خاصية تانية (سلوك)، مش اسم متغيّر محلي
    b = body_of(run(fn("  return options.timeout", "(options)"), fn("  return options.delay", "(options)")), "f")
    assert b.trivial_reason is None
    b = body_of(run(fn("  return load(x)"), fn("  return fetch(x)")), "f")
    assert b.trivial_reason is None


def test_external_name_swap_is_not_local_rename():
    # حالة حقيقية من NPM (rxjs): صارت تبعت دالة تانية → تغيير سلوك، مش اسم متغيّر
    b = body_of(run(fn("  return subscribe(x, openBuffer)"), fn("  return subscribe(x, noop)")), "f")
    assert b.trivial_reason is None and b.decision == ChangeDecision.BEHAVIORAL_CANDIDATE.value


def test_parameter_rename_used_in_body_is_trivial():
    # حالة حقيقية من NPM (formatjs): blacklist → blocklist، معامل الدالة نفسه
    b = body_of(run(fn("  return blacklist.includes(x)", "(x, blacklist)"),
                    fn("  return blocklist.includes(x)", "(x, blocklist)")), "f")
    assert b.trivial_reason == "local_rename_only"


def test_python_trivial_print():
    p = "def f(x):\n    return x\n"
    q = "def f(x):\n    print('debug', x)\n    return x\n"
    assert body_of(run(p, q, "python"), "f").trivial_reason == "logging_only"


# ─────────────────────────────────────────────────────────────────────
# 3. درجة الأهمية، وإنه ما في تنبيهات جديدة
# ─────────────────────────────────────────────────────────────────────

def test_priority_ranks_strong_signals_higher():
    weak = BodyChange(class_name="A", member="a", status="changed", lines_added=1, lines_removed=1,
                      signals=["call_added"])
    strong = BodyChange(class_name="A", member="b", status="changed", lines_added=1, lines_removed=1,
                        signals=["option_access_changed", "call_removed"])
    assert priority(strong) > priority(weak) > 0


def test_trivial_reason_needs_a_diff():
    assert trivial_reason(BodyChange(class_name="A", member="f", status="changed", truncated=True,
                                     diff="-console.log(1)\n+console.log(2)")) is None


def test_classifier_adds_no_alerts():
    res = run(fn("  return x"), fn("  if (!x) throw new Error('no')\n  return x"))
    assert not any(c.type in (ChangeType.BREAKING_CHANGE, ChangeType.BEHAVIOR_CHANGE, ChangeType.LOGIC_CHANGE)
                   for c in res.structural_conflicts)
