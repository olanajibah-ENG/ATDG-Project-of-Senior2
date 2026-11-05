# core_ai/services/conflict_detection/body_comparer.py
"""
بيقارن جسم كل دالة بين نسختين (الخطوة 8): شو تغيّر **جوا** الدالة.

- status : unchanged (نفس body_hash، يعني التعليقات والمسافات بس تغيّروا) / changed / unknown
           (جسم ناقص: abstract، interface، أو تحليل قديم قبل الخطوة 1)
- diff   : الفرق سطر سطر بعد شيل التعليقات والمسافات — هاد يلي بينبعت للـ LLM بالخطوة 11
- signals: إشارات سلوكية من الأسطر يلي تغيّرت، كل وحدة مربوطة بنوع من أنواع NPM:
    return_changed         (change return)
    throw_added / throw_removed (error handling)
    literal_changed        (change default)   نفس السطر، بس قيمة ثابتة تغيّرت
    option_access_changed  (option handling)  options.x / opts?.x / config.get('x')
    condition_changed      if / while / case / ?: تغيّر
    call_added / call_removed                 استدعاء دالة انضاف أو انشال

ما بيطلّع تنبيهات: تقريباً كل تعديل بيغيّر جسم دالة ما. القرار بالخطوات 9-11.
الإشارات مبنية على شكل الأسطر (patterns)، مش فهم كامل للكود، فممكن تغلط.
"""
import difflib
import re
from typing import Dict, List, Optional, Tuple

from .schemas import BodyChange, MethodDetail, UnifiedClassDiagram

MAX_DIFF_CHARS = 6000

_LINE_COMMENT_START = re.compile(r'^\s*(//|#|/\*|\*/|\*(?!\*)|"""|\'\'\')')
_TRAILING_COMMENT = re.compile(r'\s+(//|#)\s.*$')
_RETURN = re.compile(r'(^|[\s;{(])(return|yield)\b')
_THROW = re.compile(r'\b(throw|raise)\b')
_CONDITION = re.compile(r'^\s*(}\s*)?(if|elif|else\s+if|while|case|switch)\b|\s\?\s[^:]*\s:\s')
_OPTION = re.compile(r'\b(options|opts|option|config|conf|cfg|settings|params|props)\s*(\?\.|\.|\[)'
                     r'|\.get\(\s*[\'"]')
_CALL = re.compile(r'([A-Za-z_$][\w$]*)\s*\(')
_LITERAL = re.compile(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|`(?:\\.|[^`\\])*`'
                      r'|\b\d+(?:\.\d+)?\b|\b(?:true|false|True|False|null|None|undefined)\b')
_NOT_CALLS = {"if", "for", "while", "switch", "catch", "function", "return", "typeof", "elif", "with",
              "super", "new", "await", "yield", "print", "assert", "lambda", "not", "and", "or", "in", "def"}


def _normalize_lines(body: Optional[str]) -> List[str]:
    """أسطر بدون تعليقات ومسافات زيادة، وبدون أسطر فاضية."""
    out = []
    in_block = False
    for raw in (body or "").splitlines():
        line = raw.strip()
        if in_block:
            if "*/" in line:
                in_block = False
                line = line.split("*/", 1)[1].strip()
            else:
                continue
        if line.startswith("/*") and "*/" not in line:
            in_block = True
            continue
        if not line or _LINE_COMMENT_START.match(line):
            continue
        # تعليق بآخر السطر — بس إذا ما في علامات تنصيص قبله (لحتى ما نقطع "http://...")
        m = _TRAILING_COMMENT.search(line)
        if m and line[:m.start()].count('"') % 2 == 0 and line[:m.start()].count("'") % 2 == 0:
            line = line[:m.start()].rstrip()
        out.append(" ".join(line.split()))
    return out


def _calls(lines: List[str]) -> set:
    return {m.group(1) for l in lines for m in _CALL.finditer(l) if m.group(1) not in _NOT_CALLS}


def _skeleton(line: str) -> Tuple[str, List[str]]:
    """السطر مع كل قيمة ثابتة مستبدلة بـ L، وقائمة القيم نفسها."""
    return _LITERAL.sub("L", line), [m.group(0) for m in _LITERAL.finditer(line)]


def _literal_changed(removed: List[str], added: List[str]) -> bool:
    """سطر انشال وسطر انضاف بنفس الشكل بالزبط، والفرق بالقيم الثابتة بس."""
    added_skeletons: Dict[str, List[List[str]]] = {}
    for l in added:
        sk, lits = _skeleton(l)
        added_skeletons.setdefault(sk, []).append(lits)
    for l in removed:
        sk, lits = _skeleton(l)
        if lits and any(other != lits for other in added_skeletons.get(sk, [])):
            return True
    return False


def _signals(old: List[str], new: List[str], removed: List[str], added: List[str]) -> List[str]:
    sig = []
    changed = removed + added
    if any(_RETURN.search(l) for l in changed):
        sig.append("return_changed")
    t_old, t_new = sum(bool(_THROW.search(l)) for l in removed), sum(bool(_THROW.search(l)) for l in added)
    if t_new > t_old:
        sig.append("throw_added")
    elif t_old > t_new:
        sig.append("throw_removed")
    if _literal_changed(removed, added):
        sig.append("literal_changed")
    if any(_OPTION.search(l) for l in changed):
        sig.append("option_access_changed")
    if any(_CONDITION.search(l) for l in changed):
        sig.append("condition_changed")
    calls_old, calls_new = _calls(old), _calls(new)
    if calls_new - calls_old:
        sig.append("call_added")
    if calls_old - calls_new:
        sig.append("call_removed")
    return sig


class BodyComparer:

    @staticmethod
    def compare(a: MethodDetail, b: MethodDetail, class_name: str = "") -> BodyChange:
        base = {"class_name": class_name, "member": a.name, "new_member": b.name if b.name != a.name else None}
        if a.body is None or b.body is None or not a.body_hash or not b.body_hash:
            return BodyChange(status="unknown", **base)
        if a.body_hash == b.body_hash:
            return BodyChange(status="unchanged", **base)

        old, new = _normalize_lines(a.body), _normalize_lines(b.body)
        removed, added = [], []
        for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, old, new, autojunk=False).get_opcodes():
            if op in ("replace", "delete"):
                removed += old[i1:i2]
            if op in ("replace", "insert"):
                added += new[j1:j2]
        diff = "\n".join(difflib.unified_diff(old, new, lineterm="", n=1))
        diff = "\n".join(l for l in diff.splitlines() if not l.startswith(("---", "+++")))
        return BodyChange(status="changed", lines_added=len(added), lines_removed=len(removed),
                          diff=diff[:MAX_DIFF_CHARS], truncated=a.body_truncated or b.body_truncated
                          or len(diff) > MAX_DIFF_CHARS,
                          signals=_signals(old, new, removed, added), **base)

    @staticmethod
    def compare_diagrams(a: UnifiedClassDiagram, b: UnifiedClassDiagram,
                         renames: Optional[Dict[Tuple[str, str], str]] = None) -> List[BodyChange]:
        """
        كل دالة موجودة بالنسختين بنفس الكلاس، وكمان يلي تغيّر اسمها (renames: (class, old) → new،
        من تنبيهات method_renamed بالخطوة 7). الكلاسات والدوال الجديدة أو المحذوفة ما إلها مقارنة.
        """
        renames = renames or {}
        classes_b = {c.name: c for c in b.classes}
        out: List[BodyChange] = []
        for ca in a.classes:
            cb = classes_b.get(ca.name)
            if cb is None:
                continue
            methods_b = {m.name: m for m in cb.methods}
            for ma in ca.methods:
                mb = methods_b.get(ma.name) or methods_b.get(renames.get((ca.name, ma.name), ""))
                if mb is not None:
                    out.append(BodyComparer.compare(ma, mb, ca.name))
        return out
