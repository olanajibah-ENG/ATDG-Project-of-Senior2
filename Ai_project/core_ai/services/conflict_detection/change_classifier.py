# core_ai/services/conflict_detection/change_classifier.py
"""
بيصنّف التغيير لكل دالة (الخطوة 9): بيجمع نتيجة التوقيع (الخطوة 7) والجسم (الخطوة 8) بقرار واحد.

                    الجسم ما تغيّر          الجسم تغيّر
  التوقيع ما تغيّر   no_change              behavioral_candidate
  التوقيع تغيّر      structural_only        structural_and_behavioral

- يلي بينبعت للـ LLM بالخطوة 11: behavioral_candidate و structural_and_behavioral بس.
- التغيير "التافه" بيصير no_change مع سبب: تسجيل/طباعة بس، نص رسالة خطأ بس، أو اسم متغيّر محلي بس.
- priority: درجة أهمية من إشارات الخطوة 8، لحتى الخطوة 11 تبعت الأهم أول.

ما بيطلّع تنبيهات، وبيعبّي حقول decision / trivial_reason / priority.
"""
import math
import re
from typing import Dict, List, Optional, Set, Tuple

from .body_comparer import _skeleton
from .schemas import BodyChange, ChangeDecision, ConflictItem

# وزن كل إشارة = نسبتها بالتعديلات السلوكية يلي بتكسر ÷ نسبتها بالتعديلات السليمة،
# محسوبة على قسم التطوير (npm_dev) بس، من قياس الخطوة 8 (2026-11-05). ما بتنحسب على الاختبار.
#   بيكسر سلوكي (186): return .35  throw+ .07  throw- .07  literal .11  option .26  cond .51  call+ .35  call- .36
#   سليم (49)        : return .29  throw+ .06  throw- .00  literal .10  option .16  cond .45  call+ .41  call- .20
SIGNAL_WEIGHTS: Dict[str, float] = {
    "return_changed": 1.21, "throw_added": 1.17, "throw_removed": 2.0,      # 0.07 / 0 → سقف 2.0
    "literal_changed": 1.10, "option_access_changed": 1.63, "condition_changed": 1.13,
    "call_added": 0.85, "call_removed": 1.80,
}

_LOGGING = re.compile(r'^(await\s+)?((this\.)?(console|logger|log|logging|debug)\.\w+|print|debug|console\.\w+)\s*\(')
_ERROR_LINE = re.compile(r'\b(throw|raise)\b|\bError\s*\(|Exception\s*\(')
_TOKEN = re.compile(r'[A-Za-z_$][\w$]*|\S')
_KEYWORDS = {"const", "let", "var", "return", "if", "else", "for", "while", "new", "await", "async", "function",
             "def", "self", "this", "true", "false", "null", "None", "True", "False", "undefined", "in", "of",
             "not", "and", "or", "is", "typeof", "throw", "raise"}


def _diff_lines(diff: str) -> Tuple[List[str], List[str]]:
    removed, added = [], []
    for l in diff.splitlines():
        if l.startswith("@@"):
            continue
        if l.startswith("-"):
            removed.append(l[1:].strip())
        elif l.startswith("+"):
            added.append(l[1:].strip())
    return removed, added


def _message_only(old: str, new: str) -> bool:
    """نفس سطر الخطأ، والفرق بالنص بس."""
    return bool(_ERROR_LINE.search(old)) and _skeleton(old)[0] == _skeleton(new)[0] and old != new


def _rename_map(old: str, new: str, mapping: Dict[str, str], old_locals: Set[str], new_locals: Set[str]) -> bool:
    """
    نفس السطر بالزبط، إلا أسماء متغيّرات محلية متبدّلة بشكل ثابت. "محلي" = معامل أو معرّف جوا الجسم
    (old_locals / new_locals من الخطوة 8). اسم دالة أو ثابت من برّا (openBuffer → noop) = تغيير سلوك.
    """
    ta, tb = _TOKEN.findall(old), _TOKEN.findall(new)
    if len(ta) != len(tb):
        return False
    for i, (x, y) in enumerate(zip(ta, tb)):
        if x == y:
            continue
        if not (x[0].isalpha() or x[0] in "_$") or not (y[0].isalpha() or y[0] in "_$"):
            return False
        if x in _KEYWORDS or y in _KEYWORDS:
            return False
        if (i > 0 and ta[i - 1] == ".") or (i + 1 < len(ta) and ta[i + 1] == "("):
            return False                              # خاصية أو استدعاء = مش متغيّر محلي
        if x not in old_locals or y not in new_locals:
            return False                              # اسم من برّا الدالة
        if mapping.setdefault(x, y) != y:
            return False
    return True


def trivial_reason(body: BodyChange) -> Optional[str]:
    """إذا **كل** سطر تغيّر تافه → السبب. إذا في ولو سطر واحد مهم → None."""
    if body.truncated or not body.diff:
        return None
    removed, added = _diff_lines(body.diff)
    if not removed and not added:
        return None
    rem = [l for l in removed if not _LOGGING.match(l)]
    add = [l for l in added if not _LOGGING.match(l)]
    if not rem and not add:
        return "logging_only"
    if len(rem) != len(add):
        return None
    if all(_message_only(a, b) for a, b in zip(rem, add)):
        return "message_only"
    mapping: Dict[str, str] = {}
    old_locals, new_locals = set(body.old_locals), set(body.new_locals)
    if all(_rename_map(a, b, mapping, old_locals, new_locals) for a, b in zip(rem, add)) and mapping:
        return "local_rename_only"
    return None


def priority(body: BodyChange) -> float:
    weight = sum(SIGNAL_WEIGHTS.get(s, 1.0) for s in body.signals)
    size = math.log2(1 + body.lines_added + body.lines_removed)
    return round(weight + 0.25 * size, 3)


class ChangeClassifier:

    @staticmethod
    def classify(body: BodyChange, signature_changed: bool) -> BodyChange:
        reason = trivial_reason(body) if body.status == "changed" else None
        body_changed = body.status == "changed" and reason is None
        if body.status == "unknown":
            # ما منعرف الجسم: إذا التوقيع تغيّر الخطوة 7 بتحكم، وإلا ما في شي نبعته
            decision = ChangeDecision.STRUCTURAL_ONLY if signature_changed else ChangeDecision.NO_CHANGE
        elif signature_changed:
            decision = ChangeDecision.STRUCTURAL_AND_BEHAVIORAL if body_changed else ChangeDecision.STRUCTURAL_ONLY
        else:
            decision = ChangeDecision.BEHAVIORAL_CANDIDATE if body_changed else ChangeDecision.NO_CHANGE
        body.decision = decision.value
        body.trivial_reason = reason
        body.priority = priority(body) if body_changed else 0.0
        return body

    @staticmethod
    def classify_all(structural: List[ConflictItem], bodies: List[BodyChange]) -> List[BodyChange]:
        """
        بيعبّي decision لكل نتيجة جسم، ولتنبيهات التوقيع / إعادة التسمية / الحذف من الخطوة 7.
        الدوال يلي انحذفت أو انضافت أو تغيّر اسمها = structural_only (الخطوة 7 بتحكم عليها)،
        بس جسم الدالة يلي تغيّر اسمها بينفحص كمان، فممكن تصير structural_and_behavioral.
        """
        sig_changed: Set[Tuple[str, str]] = {(c.class_name, c.member) for c in structural
                                             if c.category in ("method_signature_changed", "method_renamed")}
        by_method = {}
        for b in bodies:
            ChangeClassifier.classify(b, (b.class_name, b.member) in sig_changed)
            by_method[(b.class_name, b.member)] = b
        for c in structural:
            if c.category in ("method_signature_changed", "method_renamed"):
                b = by_method.get((c.class_name, c.member))
                c.decision = (ChangeDecision(b.decision) if b and b.decision != ChangeDecision.NO_CHANGE.value
                              else ChangeDecision.STRUCTURAL_ONLY)
            elif c.category in ("method_removed", "method_added", "class_removed", "class_added"):
                c.decision = ChangeDecision.STRUCTURAL_ONLY
        return bodies
