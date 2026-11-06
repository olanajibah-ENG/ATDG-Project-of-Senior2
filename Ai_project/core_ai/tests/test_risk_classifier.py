"""
اختبارات الخطوة 10: RiskClassifier (مستوى خطر لكل تنبيه، والأعضاء الخاصين = معلومة متل AexPy)،
وقراءة الـ exports بـ JS / TS.

    python -m pytest core_ai/tests/test_risk_classifier.py -q
"""
import pytest

from core_ai.language_processors.java_processor import JavaProcessor
from core_ai.language_processors.python_processor import PythonProcessor
from core_ai.language_processors.tree_sitter_processor import TreeSitterProcessor
from core_ai.services.conflict_detection.orchestrator import ConflictOrchestrator
from core_ai.services.conflict_detection.risk_classifier import INTERNAL_HINT, is_private_name
from core_ai.services.conflict_detection.schemas import ChangeType, RiskLevel

BREAKING = (ChangeType.BREAKING_CHANGE, ChangeType.RENAMED)


def data(code, lang):
    p = {"python": PythonProcessor, "java": JavaProcessor}.get(lang, lambda: TreeSitterProcessor(lang))()
    a = p.parse_source_code(code)
    return p.generate_class_diagram_data(a, p.extract_features(a))


def run(before, after, lang="typescript"):
    res = ConflictOrchestrator.run_code_vs_code({"class_diagram_data": data(before, lang)},
                                                {"class_diagram_data": data(after, lang)})
    return res.structural_conflicts


def item(items, category, member=None):
    return next(c for c in items if c.category == category and (member is None or c.member == member))


# ─────────────────────────────────────────────────────────────────────
# 1. الأعضاء الخاصين = معلومة
# ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name, private", [
    ("_helper", True), ("#cache", True), ("__init__", False), ("__eq__", False), ("helper", False),
    ("_Internal<T>", True),
])
def test_private_names(name, private):
    assert is_private_name(name) is private


def test_underscore_method_removed_is_informational():
    out = run("export class A { run() { return 1 } _prepare() { return 2 } }",
              "export class A { run() { return 1 } }")
    c = item(out, "method_removed", "_prepare")
    assert c.risk_level == RiskLevel.INFORMATIONAL and c.type not in BREAKING


def test_private_keyword_method_signature_is_informational():
    out = run("export class A { private load(a: number) { return a } }",
              "export class A { private load(a: number, b: string) { return a } }")
    c = item(out, "method_signature_changed", "load")
    assert c.risk_level == RiskLevel.INFORMATIONAL and c.type not in BREAKING


def test_python_underscore_and_dunder():
    before = "class A:\n    def _cache(self, k):\n        return k\n    def __eq__(self, o):\n        return True\n"
    after = "class A:\n    def _cache(self, k, ttl):\n        return k\n    def __eq__(self, o, strict):\n        return True\n"
    out = run(before, after, "python")
    assert item(out, "method_signature_changed", "_cache").risk_level == RiskLevel.INFORMATIONAL
    eq = item(out, "method_signature_changed", "__eq__")
    assert eq.risk_level == RiskLevel.CRITICAL and eq.type == ChangeType.BREAKING_CHANGE


def test_java_private_method_removed():
    before = "public class A { public int f() { return 1; } private int g() { return 2; } }"
    out = run(before, "public class A { public int f() { return 1; } }", "java")
    assert item(out, "method_removed", "g").risk_level == RiskLevel.INFORMATIONAL


# ─────────────────────────────────────────────────────────────────────
# 2. مستوى الخطر للعام
# ─────────────────────────────────────────────────────────────────────

def test_public_removal_is_critical():
    out = run("export class A { run() { return 1 } stop() { return 2 } }", "export class A { run() { return 1 } }")
    c = item(out, "method_removed", "stop")
    assert c.risk_level == RiskLevel.CRITICAL and c.type == ChangeType.BREAKING_CHANGE


def test_every_alert_gets_a_risk_level():
    out = run("export class A { x: number; f(a: number) { return a } g() {} }\nexport class B {}",
              "export class A { f(a: number, b = 1) { return a } h() { return this.y } }")
    assert out and all(c.risk_level is not None for c in out)
    assert item(out, "method_added", "h").risk_level == RiskLevel.INFORMATIONAL


def test_signature_risk_from_step7_is_kept():
    out = run("export function f(a: number) { return a }", "export function f(a: number, b = 1) { return a }")
    assert item(out, "method_signature_changed", "f").risk_level == RiskLevel.INFORMATIONAL


# ─────────────────────────────────────────────────────────────────────
# 3. بدون export بنفس الملف = تحذير، بس بيضل كسر (ما منخسر الكشف)
# ─────────────────────────────────────────────────────────────────────

def test_not_exported_is_warning_but_still_breaking():
    out = run("function helper(a) { return a }\nexport function api(x) { return helper(x) }",
              "function helper(a, b) { return a }\nexport function api(x) { return helper(x, 1) }", "javascript")
    c = item(out, "method_signature_changed", "helper")
    assert c.risk_level == RiskLevel.WARNING and c.type == ChangeType.BREAKING_CHANGE
    assert INTERNAL_HINT in c.impact


def test_exported_stays_critical():
    out = run("export function api(a) { return a }", "export function api(a, b) { return a }", "javascript")
    assert item(out, "method_signature_changed", "api").risk_level == RiskLevel.CRITICAL


def test_export_star_means_unknown_so_no_downgrade():
    out = run("export * from './other'\nfunction f(a) { return a }",
              "export * from './other'\nfunction f(a, b) { return a }", "javascript")
    assert item(out, "method_signature_changed", "f").risk_level == RiskLevel.CRITICAL


@pytest.mark.parametrize("code, names", [
    ("export function a() {}\nexport const b = () => 1\nexport class C {}", {"a", "b", "C"}),
    ("function a() {}\nconst b = 1\nexport { a, b as c }", {"a"}),
    ("class K {}\nexport default K", {"K"}),
    ("function a() {}\nmodule.exports = { a, b: other }", {"a", "b", "other"}),
    ("exports.run = function () {}\nmodule.exports.stop = 1", {"run", "stop"}),
])
def test_exported_names(code, names):
    assert names <= set(data(code, "javascript")["exported_names"])


def test_python_has_no_export_info():
    assert "exported_names" not in data("def f():\n    return 1\n", "python")
