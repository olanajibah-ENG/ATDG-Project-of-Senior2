# core_ai/services/conflict_detection/risk_classifier.py
"""
بيحط مستوى خطر لكل تنبيه بـ Code vs Code (الخطوة 10)، متل AexPy:

    حرج (CRITICAL)        = بيكسر الاستدعاءات الموجودة
    تحذير (WARNING)       = ممكن يكسر، أو ما منعرف أكيد
    معلومة (INFORMATIONAL) = ما بيكسر حدا من برّا

1. الأعضاء الخاصين = معلومة، والتنبيه ما عاد "كسر":
   الاسم بيبلّش بـ `_` (مش `__x__`) أو `#`، أو الظهور private / protected.
   (قارئ Python بيعطي `__eq__` ظهور private لأنه بيبلّش بـ `_`، فالـ `__x__` بتضل عامة.)
   هيك AexPy بيعامل الأعضاء الخاصين: يلي من برّا ما بيستعملهم.
2. باقي التنبيهات: من نوعها. breaking_change / renamed = حرج (إلا إذا الخطوة 7 حطت مستوى أدق
   للتوقيع)، behavior_change / logic_change = تحذير، refactoring / new_feature = معلومة.
3. JS / TS بدون export بنفس الملف: التنبيه بيضل كسر، بس مستواه "تحذير" مع ملاحظة إنه ممكن يكون
   داخلي. السبب: الـ export غالباً بملف تاني (index.ts: `export * from './x'`) ما منشوفه، ولما
   جرّبنا نعتبرهن داخليين، خسرنا 107 من 425 تعديل بيكسر منكشف بقسم الاختبار تبع NPM.
"""
from typing import List, Optional

from .schemas import (
    MODULE_CLASS, ChangeType, ConflictItem, RiskLevel, SeverityLevel, UnifiedClassDiagram,
)

_PRIVATE_VISIBILITY = {"private", "protected", "-", "#"}
_BY_TYPE = {
    ChangeType.BREAKING_CHANGE: RiskLevel.CRITICAL, ChangeType.RENAMED: RiskLevel.CRITICAL,
    ChangeType.BEHAVIOR_CHANGE: RiskLevel.WARNING, ChangeType.LOGIC_CHANGE: RiskLevel.WARNING,
}
_ATTRIBUTE_CATEGORIES = {"attribute_removed", "attribute_added", "attribute_type_changed"}
INTERNAL_HINT = "قد يكون داخلياً: ما عليه export بهالملف (ممكن ينعمله export من ملف تاني)"


def _is_dunder(name: str) -> bool:
    return name.startswith("__") and name.endswith("__")


def is_private_name(name: Optional[str]) -> bool:
    name = (name or "").split("<", 1)[0].strip()
    if _is_dunder(name):
        return False                                   # __init__ و __eq__ عامّين
    return name.startswith(("_", "#"))


class RiskClassifier:

    @staticmethod
    def _member_visibility(diagram: UnifiedClassDiagram, item: ConflictItem) -> Optional[str]:
        cls = next((c for c in diagram.classes if c.name == item.class_name), None)
        if cls is None or not item.member:
            return None
        pool = cls.attributes if item.category in _ATTRIBUTE_CATEGORIES else cls.methods
        member = next((m for m in pool if m.name == item.member), None)
        return member.visibility if member is not None else None

    @staticmethod
    def classify(items: List[ConflictItem], diagram_a: UnifiedClassDiagram) -> List[ConflictItem]:
        exported = set(diagram_a.exported_names) if diagram_a.exported_names is not None else None
        for c in items:
            visibility = RiskClassifier._member_visibility(diagram_a, c)
            private = (is_private_name(c.member) or (not c.member and is_private_name(c.class_name))
                       or (c.member and visibility in _PRIVATE_VISIBILITY and not _is_dunder(c.member))
                       or (c.class_name != MODULE_CLASS and is_private_name(c.class_name)))

            if private:
                if c.type in (ChangeType.BREAKING_CHANGE, ChangeType.RENAMED):
                    c.type = ChangeType.REFACTORING
                    c.severity = SeverityLevel.LOW
                    c.impact = "عضو خاص: ما حدا من برّا بيستعمله"
                c.risk_level = RiskLevel.INFORMATIONAL
                continue

            if c.risk_level is None:
                c.risk_level = _BY_TYPE.get(c.type, RiskLevel.INFORMATIONAL)

            # JS / TS: الكلاس أو الدالة المستقلة ما عليها export بهالملف → تحذير، بس بيضل كسر
            target = c.member if c.class_name == MODULE_CLASS else c.class_name
            if (exported is not None and "*" not in exported and c.risk_level == RiskLevel.CRITICAL
                    and target and target.split("<", 1)[0] not in exported):
                c.risk_level = RiskLevel.WARNING
                c.impact = f"{c.impact} — {INTERNAL_HINT}" if c.impact else INTERNAL_HINT
        return items
