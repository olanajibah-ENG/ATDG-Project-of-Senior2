# core_ai/services/conflict_detection/signature_comparer.py
"""
بيقارن توقيع دالة بين نسختين (الخطوة 7)، معامل معامل، بدل مقارنة نص التوقيع.

قبل: أي تغيير بالبصمة (عدد المعاملات / أنواعها / الإرجاع) = كسر. فإضافة معامل اختياري
     `f(a)` → `f(a, b = 1)` كانت تنحسب كسر، وهي ما بتكسر ولا استدعاء.
هلق: قواعد متل AexPy، معدّلة لـ JavaScript/TypeScript:
    حرج (CRITICAL)        = بيكسر الاستدعاءات الموجودة
    تحذير (WARNING)       = ممكن يكسر حسب طريقة الاستدعاء (إعادة تسمية معامل بـ Python)
    معلومة (INFORMATIONAL) = ما بيكسر

بتعتمد على حقول الخطوة 1 (parameters / return_type / is_async). إذا التحليل قديم وما فيه
parameters → known = False، والمستدعي بيرجع للطريقة القديمة.
"""
from typing import List, Optional

from pydantic import BaseModel, Field

from .schemas import MethodDetail, ParameterDetail, RiskLevel

_POSITIONAL = {"positional", "positional_only", "positional_or_keyword"}
_VISIBILITY_RANK = {"public": 3, "+": 3, "protected": 2, "#": 2, "internal": 2, "package": 2, "~": 2,
                    "private": 1, "-": 1}
_UNKNOWN_TYPES = {"", "any", "object", "none", "void", "unknown"}
_RANK = {RiskLevel.INFORMATIONAL: 0, RiskLevel.WARNING: 1, RiskLevel.CRITICAL: 2}


class SignatureChange(BaseModel):
    kind:   str                 # parameter_added_required, parameter_removed, ...
    detail: str
    risk:   RiskLevel


class SignatureComparison(BaseModel):
    known:   bool = True                     # False = ما في معلومات معاملات بالنسختين
    changes: List[SignatureChange] = Field(default_factory=list)

    @property
    def risk(self) -> Optional[RiskLevel]:
        return max((c.risk for c in self.changes), key=_RANK.get, default=None)

    @property
    def is_breaking(self) -> bool:
        return self.risk == RiskLevel.CRITICAL

    def describe(self) -> str:
        return "; ".join(c.detail for c in self.changes)


def _norm_type(t: Optional[str]) -> str:
    return " ".join((t or "").split()).lower()


def _known_type(t: Optional[str]) -> bool:
    return _norm_type(t) not in _UNKNOWN_TYPES


def _union(t: Optional[str]) -> set:
    """`A | B | null` → {"a", "b", "null"} (على المستوى الأعلى بس، مش جوا <> أو () أو {})."""
    parts, depth, cur = [], 0, ""
    for ch in _norm_type(t):
        if ch in "<([{":
            depth += 1
        elif ch in ">)]}":
            depth -= 1
        if ch == "|" and depth == 0:
            parts.append(cur); cur = ""
        else:
            cur += ch
    parts.append(cur)
    return {x.strip() for x in parts if x.strip()}


def _optional(p: ParameterDetail) -> bool:
    return p.default is not None or p.kind in ("var_positional", "var_keyword")


class SignatureComparer:

    @staticmethod
    def compare(a: MethodDetail, b: MethodDetail) -> SignatureComparison:
        if a.parameters is None or b.parameters is None:
            return SignatureComparison(known=False)
        out: List[SignatureChange] = []
        add = lambda kind, detail, risk: out.append(SignatureChange(kind=kind, detail=detail, risk=risk))

        # ── الظهور (public → private بيكسر) ──
        va, vb = _VISIBILITY_RANK.get(a.visibility, 3), _VISIBILITY_RANK.get(b.visibility, 3)
        if vb < va:
            add("visibility_reduced", f"visibility reduced: {a.visibility} → {b.visibility}", RiskLevel.CRITICAL)
        elif vb > va:
            add("visibility_widened", f"visibility widened: {a.visibility} → {b.visibility}", RiskLevel.INFORMATIONAL)

        # ── async ↔ sync: الإرجاع بيصير Promise أو بيبطّل ──
        if a.is_async != b.is_async and not (a.is_constructor or b.is_constructor):
            add("async_changed", "became async (returns a Promise)" if b.is_async else "no longer async",
                RiskLevel.CRITICAL)

        SignatureComparer._compare_positional(a, b, add)
        SignatureComparer._compare_by_kind(a, b, add, "keyword_only")
        SignatureComparer._compare_variadic(a, b, add)

        # ── نوع الإرجاع (ما منقارن إذا واحد منهم غير معروف) ──
        # بيرجّع أقل من قبل (A | null → A) = يلي عم يستعمل النتيجة لسا شغّال؛
        # بيرجّع أكتر أو شي تاني (A → A | null، أو Array → Object) = بيكسر يلي عم يستعمل النتيجة.
        if (_known_type(a.return_type) and _known_type(b.return_type)
                and _norm_type(a.return_type) != _norm_type(b.return_type)):
            narrowed = _union(b.return_type) < _union(a.return_type)
            add("return_type_changed", f"return type changed: {a.return_type} → {b.return_type}",
                RiskLevel.INFORMATIONAL if narrowed else RiskLevel.CRITICAL)
        return SignatureComparison(changes=out)

    # ─────────────────────────────────────────────────────────────────
    @staticmethod
    def _compare_positional(a: MethodDetail, b: MethodDetail, add) -> None:
        pa = [p for p in a.parameters if p.kind in _POSITIONAL]
        pb = [p for p in b.parameters if p.kind in _POSITIONAL]

        # نفس الأسماء بترتيب تاني = ترتيب تغيّر (بيكسر لأنه المعاملات بتنبعت بالترتيب)
        names_a, names_b = [p.name for p in pa], [p.name for p in pb]
        if len(pa) > 1 and names_a != names_b and sorted(names_a) == sorted(names_b):
            add("parameters_reordered", f"parameters reordered: ({', '.join(names_a)}) → ({', '.join(names_b)})",
                RiskLevel.CRITICAL)
            return

        for i in range(max(len(pa), len(pb))):
            old = pa[i] if i < len(pa) else None
            new = pb[i] if i < len(pb) else None
            if old is None:
                if _optional(new):
                    add("parameter_added_optional", f"optional parameter '{new.name}' added", RiskLevel.INFORMATIONAL)
                else:
                    add("parameter_added_required", f"required parameter '{new.name}' added", RiskLevel.CRITICAL)
                continue
            if new is None:
                # اتشال، بس إذا صار في ...rest بالنسخة الجديدة بيضل الاستدعاء شغّال
                absorbed = any(p.kind == "var_positional" for p in b.parameters)
                add("parameter_removed", f"parameter '{old.name}' removed",
                    RiskLevel.INFORMATIONAL if absorbed else RiskLevel.CRITICAL)
                continue
            if old.name != new.name:
                # Python: ممكن حدا عم يستدعي بالاسم f(name=...)؛ باقي اللغات بالترتيب بس
                risk = RiskLevel.WARNING if old.kind == "positional_or_keyword" else RiskLevel.INFORMATIONAL
                add("parameter_renamed", f"parameter renamed: '{old.name}' → '{new.name}'", risk)
            if _known_type(old.type) and _known_type(new.type) and _norm_type(old.type) != _norm_type(new.type):
                # المعامل بيقبل أكتر من قبل (A → A | B) = الاستدعاءات القديمة شغّالة؛ غير هيك بيكسر
                widened = _union(old.type) < _union(new.type)
                add("parameter_type_changed", f"parameter '{new.name}' type changed: {old.type} → {new.type}",
                    RiskLevel.INFORMATIONAL if widened else RiskLevel.CRITICAL)
            if _optional(old) and not _optional(new):
                add("parameter_became_required", f"parameter '{new.name}' became required", RiskLevel.CRITICAL)
            elif not _optional(old) and _optional(new):
                add("parameter_became_optional", f"parameter '{new.name}' became optional", RiskLevel.INFORMATIONAL)

    @staticmethod
    def _compare_by_kind(a: MethodDetail, b: MethodDetail, add, kind: str) -> None:
        """keyword_only (Python): بينطابقوا بالاسم مش بالترتيب."""
        ka = {p.name: p for p in a.parameters if p.kind == kind}
        kb = {p.name: p for p in b.parameters if p.kind == kind}
        for name in ka.keys() - kb.keys():
            add("parameter_removed", f"keyword parameter '{name}' removed", RiskLevel.CRITICAL)
        for name in kb.keys() - ka.keys():
            if _optional(kb[name]):
                add("parameter_added_optional", f"optional keyword parameter '{name}' added", RiskLevel.INFORMATIONAL)
            else:
                add("parameter_added_required", f"required keyword parameter '{name}' added", RiskLevel.CRITICAL)
        for name in ka.keys() & kb.keys():
            if _optional(ka[name]) and not _optional(kb[name]):
                add("parameter_became_required", f"keyword parameter '{name}' became required", RiskLevel.CRITICAL)

    @staticmethod
    def _compare_variadic(a: MethodDetail, b: MethodDetail, add) -> None:
        for kind, label in (("var_positional", "*args / ...rest"), ("var_keyword", "**kwargs")):
            had = any(p.kind == kind for p in a.parameters)
            has = any(p.kind == kind for p in b.parameters)
            if had and not has:
                add("parameter_removed", f"{label} removed", RiskLevel.CRITICAL)
            elif has and not had:
                add("parameter_added_optional", f"{label} added", RiskLevel.INFORMATIONAL)
