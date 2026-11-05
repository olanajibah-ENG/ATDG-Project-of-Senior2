"""
اختبارات الخطوة 8: BodyComparer (مقارنة جسم الدالة بين نسختين: الحالة، الفرق، والإشارات السلوكية).

    python -m pytest core_ai/tests/test_body_comparer.py -q
"""
import pytest

from core_ai.language_processors.java_processor import JavaProcessor
from core_ai.language_processors.python_processor import PythonProcessor
from core_ai.language_processors.tree_sitter_processor import TreeSitterProcessor
from core_ai.services.conflict_detection.ast_unifier import ASTUnifier
from core_ai.services.conflict_detection.body_comparer import BodyComparer, _normalize_lines
from core_ai.services.conflict_detection.orchestrator import ConflictOrchestrator
from core_ai.services.conflict_detection.schemas import MODULE_CLASS, ChangeType


def analysis(code, lang):
    p = {"python": PythonProcessor, "java": JavaProcessor}.get(lang, lambda: TreeSitterProcessor(lang))()
    a = p.parse_source_code(code)
    return {"class_diagram_data": p.generate_class_diagram_data(a, p.extract_features(a))}


def body_changes(before, after, lang="javascript"):
    da, db = (ASTUnifier.from_tree_sitter(analysis(c, lang)) for c in (before, after))
    return {(c.class_name, c.member): c for c in BodyComparer.compare_diagrams(da, db)}


def one(before, after, lang="javascript", member=None):
    ch = body_changes(before, after, lang)
    return next(c for (cls, m), c in ch.items() if member in (None, m))


# ─────────────────────────────────────────────────────────────────────
# 1. الحالة: unchanged / changed / unknown
# ─────────────────────────────────────────────────────────────────────

def test_comments_and_whitespace_only_is_unchanged():
    a = "export function f(x) {\n  return x + 1\n}"
    b = "export function f(x) {\n  // add one\n\n    return x + 1   \n}"
    assert one(a, b).status == "unchanged"


def test_real_change_is_changed_with_diff():
    c = one("export function f(x) {\n  return x + 1\n}", "export function f(x) {\n  return x + 2\n}")
    assert c.status == "changed" and c.lines_added == 1 and c.lines_removed == 1
    assert "-return x + 1" in c.diff and "+return x + 2" in c.diff


def test_abstract_method_without_body_is_unknown():
    code = "public abstract class A { public abstract int f(int x); }"
    assert one(code, code.replace("int x", "int y"), lang="java").status == "unknown"


def test_new_or_removed_methods_have_no_body_comparison():
    ch = body_changes("export class A { f() { return 1 } }", "export class A { g() { return 2 } h() {} }")
    assert set(m for _, m in ch) <= {"f"}            # g/h جداد، ما إلهن نسخة قديمة


def test_renamed_method_compared_with_its_new_name():
    a = "export class A { fetchUser(id) { return this.db.get(id) } }"
    b = "export class A { getUser(id) { return this.db.get(id, true) } }"
    res = ConflictOrchestrator.run_code_vs_code(analysis(a, "javascript"), analysis(b, "javascript"))
    renamed = [c for c in res.body_changes if c.member == "fetchUser"]
    assert renamed and renamed[0].new_member == "getUser" and renamed[0].status == "changed"


# ─────────────────────────────────────────────────────────────────────
# 2. الإشارات السلوكية (كل وحدة لحالها)
# ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("before, after, signal", [
    # change return
    ("export function f(x) {\n  return x\n}", "export function f(x) {\n  return x ?? null\n}", "return_changed"),
    # error handling
    ("export function f(x) {\n  return x\n}",
     "export function f(x) {\n  if (!x) throw new Error('missing')\n  return x\n}", "throw_added"),
    ("export function f(x) {\n  if (!x) throw new Error('missing')\n  return x\n}",
     "export function f(x) {\n  return x\n}", "throw_removed"),
    # change default
    ("export function f(o) {\n  const t = o.timeout || 1000\n  run(t)\n}",
     "export function f(o) {\n  const t = o.timeout || 5000\n  run(t)\n}", "literal_changed"),
    ("export function f() {\n  return cache(true)\n}", "export function f() {\n  return cache(false)\n}",
     "literal_changed"),
    # option handling
    ("export function f(options) {\n  go()\n}", "export function f(options) {\n  if (options?.strict) go()\n}",
     "option_access_changed"),
    # condition
    ("export function f(a) {\n  if (a > 0) go()\n}", "export function f(a) {\n  if (a >= 0) go()\n}",
     "condition_changed"),
    # calls
    ("export function f(x) {\n  return save(x)\n}", "export function f(x) {\n  validate(x)\n  return save(x)\n}",
     "call_added"),
    ("export function f(x) {\n  validate(x)\n  return save(x)\n}", "export function f(x) {\n  return save(x)\n}",
     "call_removed"),
])
def test_signals(before, after, signal):
    assert signal in one(before, after).signals


def test_python_raise_and_return():
    a = "def get(d, k):\n    return d.get(k)\n"
    b = "def get(d, k):\n    if k not in d:\n        raise KeyError(k)\n    return d[k]\n"
    c = one(a, b, lang="python")
    assert {"throw_added", "return_changed", "condition_changed"} <= set(c.signals)


def test_java_body_signals():
    a = "public class A { public int f(int x) { return x; } }"
    b = "public class A { public int f(int x) { if (x < 0) { throw new IllegalArgumentException(); } return x; } }"
    c = one(a, b, lang="java")
    assert c.status == "changed" and "throw_added" in c.signals


def test_no_false_literal_signal_when_line_shape_changes():
    # السطر تغيّر بشكل كامل، مش بس قيمته → مش literal_changed
    c = one("export function f(a) {\n  return a + 1\n}", "export function f(a) {\n  return compute(a, 1)\n}")
    assert "literal_changed" not in c.signals


# ─────────────────────────────────────────────────────────────────────
# 3. التطبيع، وإنه ما في تنبيهات جديدة
# ─────────────────────────────────────────────────────────────────────

def test_normalize_keeps_urls_and_drops_comments():
    lines = _normalize_lines('const u = "http://x.io" // the url\n/* block\n comment */\n# py comment\nreturn u')
    assert lines == ['const u = "http://x.io"', "return u"]


def test_body_changes_do_not_create_alerts():
    a = "export function f(x) {\n  return x\n}"
    b = "export function f(x) {\n  if (!x) throw new Error('no')\n  return x\n}"
    res = ConflictOrchestrator.run_code_vs_code(analysis(a, "javascript"), analysis(b, "javascript"))
    assert res.body_changes and res.body_changes[0].class_name == MODULE_CLASS
    assert not any(c.type in (ChangeType.BREAKING_CHANGE, ChangeType.BEHAVIOR_CHANGE, ChangeType.LOGIC_CHANGE)
                   for c in res.structural_conflicts)
