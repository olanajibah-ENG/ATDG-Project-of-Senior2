"""
اختبارات الخطوة 7: SignatureComparer (قواعد متل AexPy) وتصليح كشف إعادة التسمية،
وقراءة معاملات TypeScript (اختياري / قيمة افتراضية / ...rest / destructuring).

    python -m pytest core_ai/tests/test_signature_comparer.py -q
"""
import pytest

from core_ai.language_processors.tree_sitter_processor import TreeSitterProcessor
from core_ai.services.conflict_detection.ast_unifier import ASTUnifier
from core_ai.services.conflict_detection.schemas import (
    MODULE_CLASS, ChangeType, MethodDetail, ParameterDetail, RiskLevel,
)
from core_ai.services.conflict_detection.signature_comparer import SignatureComparer
from core_ai.services.conflict_detection.structural_diff import StructuralDiff

C, W, I = RiskLevel.CRITICAL, RiskLevel.WARNING, RiskLevel.INFORMATIONAL


def P(name, default=None, kind="positional", type=None):
    return ParameterDetail(name=name, default=default, kind=kind, type=type)


def M(params, name="f", **kw):
    return MethodDetail(name=name, signature=f"{name}()", parameters=params, **kw)


def kinds(a, b):
    r = SignatureComparer.compare(a, b)
    return [(c.kind, c.risk) for c in r.changes]


# ─────────────────────────────────────────────────────────────────────
# 1. القواعد، وحدة وحدة (جدول الخطة)
# ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("before, after, expected", [
    # ما بيكسر
    ([P("a")], [P("a"), P("b", default="1")], [("parameter_added_optional", I)]),
    ([P("a")], [P("a"), P("b", default="undefined")], [("parameter_added_optional", I)]),     # TS: b?
    ([P("a")], [P("a"), P("more", kind="var_positional")], [("parameter_added_optional", I)]),
    ([P("a"), P("b")], [P("a"), P("b", default="0")], [("parameter_became_optional", I)]),
    ([P("name")], [P("label")], [("parameter_renamed", I)]),                                  # JS/TS/Java
    # تحذير
    ([P("name", kind="positional_or_keyword")], [P("label", kind="positional_or_keyword")],
     [("parameter_renamed", W)]),                                                            # Python
    # بيكسر
    ([P("a")], [P("a"), P("b")], [("parameter_added_required", C)]),
    ([P("a"), P("b")], [P("a")], [("parameter_removed", C)]),
    ([P("a", default="1")], [P("a")], [("parameter_became_required", C)]),
    ([P("a"), P("b")], [P("b"), P("a")], [("parameters_reordered", C)]),
    ([P("id", type="number")], [P("id", type="string")], [("parameter_type_changed", C)]),
])
def test_rules(before, after, expected):
    assert kinds(M(before), M(after)) == expected


def test_async_change_is_breaking():
    assert kinds(M([], is_async=False), M([], is_async=True)) == [("async_changed", C)]


def test_visibility_reduced_is_breaking_widened_is_not():
    assert kinds(M([], visibility="public"), M([], visibility="private")) == [("visibility_reduced", C)]
    assert kinds(M([], visibility="private"), M([], visibility="public")) == [("visibility_widened", I)]


def test_return_type_rules():
    assert kinds(M([], return_type="string"), M([], return_type="number")) == [("return_type_changed", C)]
    # بيرجّع null كمان → يلي عم يستعمل النتيجة ممكن يوقع (حالة حقيقية من NPM: awilix)
    assert kinds(M([], return_type="Array<Parameter>"),
                 M([], return_type="Array<Parameter> | null")) == [("return_type_changed", C)]
    assert kinds(M([], return_type="User | null"), M([], return_type="User")) == [("return_type_changed", I)]
    assert kinds(M([], return_type="Any"), M([], return_type="int")) == []          # مستنتج / غير معروف


def test_parameter_type_widened_is_not_breaking():
    assert kinds(M([P("v", type="string")]), M([P("v", type="string | number")])) == [("parameter_type_changed", I)]
    assert kinds(M([P("v", type="string | number")]), M([P("v", type="string")])) == [("parameter_type_changed", C)]
    # الـ | جوا <> ما بينحسب
    assert kinds(M([P("v", type="Map<string | number, T>")]),
                 M([P("v", type="Map<string, T>")])) == [("parameter_type_changed", C)]


def test_removed_parameter_absorbed_by_rest_is_not_breaking():
    r = SignatureComparer.compare(M([P("a"), P("b")]), M([P("a"), P("rest", kind="var_positional")]))
    assert not r.is_breaking


def test_python_keyword_only_matched_by_name():
    a = M([P("x", kind="positional_or_keyword"), P("strict", default="False", kind="keyword_only")])
    b = M([P("x", kind="positional_or_keyword"), P("strict", kind="keyword_only")])
    assert kinds(a, b) == [("parameter_became_required", C)]


def test_overall_risk_is_the_worst_change():
    r = SignatureComparer.compare(M([P("a")]), M([P("x"), P("b")]))      # rename (I) + required added (C)
    assert r.risk == C and r.is_breaking and "required parameter 'b' added" in r.describe()


def test_old_analysis_without_parameters_is_unknown():
    assert SignatureComparer.compare(MethodDetail(name="f", signature="f(a)"),
                                     MethodDetail(name="f", signature="f(a, b)")).known is False


# ─────────────────────────────────────────────────────────────────────
# 2. الربط بـ StructuralDiff (من الكود الحقيقي، TypeScript و JavaScript)
# ─────────────────────────────────────────────────────────────────────

def ts(code, lang="typescript"):
    p = TreeSitterProcessor(lang)
    a = p.parse_source_code(code)
    return ASTUnifier.from_tree_sitter({"class_diagram_data": p.generate_class_diagram_data(a, p.extract_features(a))})


def flagged(before, after, lang="typescript"):
    out = StructuralDiff.compare(ts(before, lang), ts(after, lang))
    return [c for c in out if c.type in (ChangeType.BREAKING_CHANGE, ChangeType.RENAMED)]


def test_optional_parameter_added_is_no_longer_breaking():
    # قبل الخطوة 7: عدد المعاملات تغيّر → البصمة تغيّرت → "كسر"
    assert flagged("export function fetch(url: string) { return url }",
                   "export function fetch(url: string, options: Opts = {}) { return url }") == []
    assert flagged("function fetch(url) { return url }",
                   "function fetch(url, options = {}) { return url }", lang="javascript") == []


def test_required_parameter_added_still_breaking():
    out = flagged("export class A { f(a: number) { return a } }",
                  "export class A { f(a: number, b: string) { return a } }")
    assert len(out) == 1 and out[0].risk_level == C and "required parameter 'b' added" in out[0].description


def test_default_removed_is_caught_even_if_signature_text_same():
    # نص التوقيع ما بيحمل القيمة الافتراضية: "f(a, b)" بالنسختين — قبل ما كان يبيّن شي
    out = flagged("export function f(a, b = 1) { return a }", "export function f(a, b) { return a }")
    assert len(out) == 1 and "became required" in out[0].description


def test_became_async_is_breaking():
    out = flagged("export function load(p: string) { return p }",
                  "export async function load(p: string) { return p }")
    assert len(out) == 1 and "async" in out[0].description


# ─────────────────────────────────────────────────────────────────────
# 3. كشف إعادة التسمية
# ─────────────────────────────────────────────────────────────────────

def test_rename_reported_once_as_breaking():
    out = StructuralDiff.compare(
        ts("export class A { fetchUser(id: number) { return this.db.get(id) } }"),
        ts("export class A { getUser(id: number) { return this.db.get(id) } }"))
    renames = [c for c in out if c.type == ChangeType.RENAMED]
    assert len(renames) == 1                                         # قبل: مرتين (تنبيهين لنفس الشي)
    assert renames[0].new_value == "getUser" and renames[0].risk_level == C


def test_no_fake_rename_between_methods_that_both_still_exist():
    # start() و stop() نفس الشكل؛ القديم كان يعتبرهن "إعادة تسمية" لأنه بيقارن البصمات بكل الملف
    code = "export class T { start() { this.on = true } stop() { this.on = false } }"
    after = "export class T { start() { this.on = 1 } stop() { this.on = false } }"
    assert [c for c in StructuralDiff.compare(ts(code), ts(after)) if c.type == ChangeType.RENAMED] == []


def test_same_shape_different_body_and_name_is_removal_not_rename():
    out = StructuralDiff.compare(ts("export class A { open() { return this.a } }"),
                                 ts("export class A { reset() { this.b = 0 } }"))
    assert {c.category for c in out} >= {"method_removed", "method_added"}
    assert not any(c.type == ChangeType.RENAMED for c in out)


# ─────────────────────────────────────────────────────────────────────
# 4. قراءة معاملات TypeScript / JavaScript
# ─────────────────────────────────────────────────────────────────────

def test_typescript_parameter_details():
    d = ts("""export class A {
  f(a: number, b: string = "x", c?: boolean, ...rest: any[]): void {}
  g({k, v}: Opts) {}
}""")
    f = next(m for m in d.classes[0].methods if m.name == "f")
    got = [(p.name, p.type, p.default, p.kind) for p in f.parameters]
    assert got == [("a", "number", None, "positional"), ("b", "string", '"x"', "positional"),
                   ("c", "boolean", "undefined", "positional"), ("rest", "any[]", None, "var_positional")]
    g = next(m for m in d.classes[0].methods if m.name == "g")
    assert [p.name for p in g.parameters] == ["{k, v}"]
    assert f.signature == "f(a, b, c)"          # نص التوقيع القديم ما تغيّر (نفس يلي قبل الخطوة 7)


def test_javascript_arrow_and_destructuring():
    d = ts("export const h = ({a, b}, c = 2) => a;\nexport const k = x => x;", lang="javascript")
    funcs = {m.name: m for c in d.classes if c.name == MODULE_CLASS for m in c.methods}
    assert [(p.name, p.default) for p in funcs["h"].parameters] == [("{a, b}", None), ("c", "2")]
    assert [p.name for p in funcs["k"].parameters] == ["x"]
