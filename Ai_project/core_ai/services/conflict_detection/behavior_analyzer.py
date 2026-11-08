# core_ai/services/conflict_detection/behavior_analyzer.py
"""
BehaviorAnalyzer — الخطوة 11: الذكاء الاصطناعي بـ Code vs Code، بس على الدوال المرشّحة.

بدل SemanticAnalyzer القديم (كان يبعت المخطط كله بأسماء الدوال بس، بطلب بكل مقارنة):
- ما في مرشّحين من الخطوة 9 (behavioral_candidate / structural_and_behavioral) → ولا طلب.
- طلب لكل مقارنة، فيه الدوال المرشّحة مرتّبة حسب priority، لحد MAX_REQUEST_CHARS (والباقي بطلب تاني).
- لكل دالة: الكود قبل وبعد بأرقام أسطر، الفرق (8)، تغيير التوقيع (7)، والإشارات كتلميح.
- الفلترة (متل الخطوة 5):
    1. old_snippet لازم يكون من BEFORE و new_snippet من AFTER، وإلا بينرمى (اختراع). لازم واحد منهم على الأقل.
    2. عتبة ثقة (DEFAULT_THRESHOLD).
    3. تغيير سلوكي ما بيكسر، أو تحت العتبة → إحصائية (hidden) مش تنبيه.
    4. بيكسر → ConflictItem من نوع behavior_change، مستوى خطر حرج، مع النوع والدليل.
- فشل كل المحاولات → المقارنة بتنسجّل إنها ما انفحصت دلالياً، وبتضل نتائج الخطوات 7-10.
"""
import logging
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from core_ai.ai_engine.llm_client import LLMClient
from .doc_prompt_builder import _guess_language, method_code, method_lines
from .doc_semantic_analyzer import _confidence, _strip_line_numbers, parse_response, quote_found
from .prompts.conflict_prompts import BEHAVIOR_ITEM, BEHAVIOR_PROMPT, BEHAVIOR_SYSTEM
from .schemas import (
    MODULE_CLASS, BodyChange, ChangeDecision, ChangeType, ConflictItem, MethodDetail, RiskLevel,
    SeverityLevel, UnifiedClassDiagram,
)

logger = logging.getLogger(__name__)

DEFAULT_THRESHOLD = 0.7
MAX_REQUEST_CHARS = 12000
SEND = {ChangeDecision.BEHAVIORAL_CANDIDATE.value, ChangeDecision.STRUCTURAL_AND_BEHAVIORAL.value}
CHANGE_TYPES = {"change_return", "change_default", "option_handling", "error_handling", "other"}


class BehaviorItem(BaseModel):
    id:         str
    class_name: str
    member:     str
    decision:   str
    before:     str          # الأسطر بدون أرقام، للتأكد من النسخ
    after:      str


class BehaviorRequest(BaseModel):
    system: str
    user:   str
    items:  List[BehaviorItem] = Field(default_factory=list)


class BehaviorAnalysisStats(BaseModel):
    candidates:       int = 0
    requests:         int = 0
    failed_requests:  int = 0
    findings:         int = 0
    not_observable:   int = 0
    dropped_quote:    int = 0      # السطر المنسوخ مش موجود بالكود
    non_breaking:     int = 0      # تغيير سلوكي ما بيكسر → إحصائية
    below_threshold:  int = 0
    flagged:          int = 0
    unknown_item_ids: int = 0
    hidden:           List[Dict] = Field(default_factory=list)


def _find(diagram: UnifiedClassDiagram, cls: str, name: str) -> Optional[MethodDetail]:
    c = next((c for c in diagram.classes if c.name == cls), None)
    return next((m for m in c.methods if m.name == name), None) if c else None


def build_behavior_requests(diagram_a: UnifiedClassDiagram, diagram_b: UnifiedClassDiagram,
                            bodies: List[BodyChange], structural: List[ConflictItem]) -> List[BehaviorRequest]:
    language = diagram_a.language or diagram_b.language or _guess_language(diagram_a) or _guess_language(diagram_b)
    signature = {(c.class_name, c.member): c.description for c in structural
                 if c.category == "method_signature_changed"}
    blocks: List[Tuple[BehaviorItem, str]] = []
    for b in sorted((b for b in bodies if b.decision in SEND), key=lambda b: -b.priority):
        ma = _find(diagram_a, b.class_name, b.member)
        mb = _find(diagram_b, b.class_name, b.new_member or b.member)
        if ma is None or mb is None:
            continue
        in_class = b.class_name != MODULE_CLASS
        item = BehaviorItem(
            id=f"{b.class_name}.{b.member}", class_name=b.class_name, member=b.member, decision=b.decision,
            before="\n".join(method_lines(ma, language, None, in_class)[0].values()),
            after="\n".join(method_lines(mb, language, None, in_class)[0].values()))
        sig = signature.get((b.class_name, b.member))
        text = BEHAVIOR_ITEM.format(
            item_id=item.id, signature=f"SIGNATURE CHANGE: {sig}\n" if sig else "",
            hints=", ".join(b.signals) or "none",
            before=method_code(ma, language, None, in_class), after=method_code(mb, language, None, in_class),
            diff=b.diff or "(diff unavailable)")
        blocks.append((item, text))

    requests, chunk, size = [], [], 0
    for item, text in blocks:
        if chunk and size + len(text) > MAX_REQUEST_CHARS:
            requests.append(_request(language, chunk))
            chunk, size = [], 0
        chunk.append((item, text))
        size += len(text)
    if chunk:
        requests.append(_request(language, chunk))
    return requests


def _request(language: str, chunk: List[Tuple[BehaviorItem, str]]) -> BehaviorRequest:
    user = BEHAVIOR_PROMPT.format(language=language or "source", items="\n\n".join(t for _, t in chunk))
    return BehaviorRequest(system=BEHAVIOR_SYSTEM, user=user, items=[i for i, _ in chunk])


def _truthy(v) -> bool:
    return v is True or (isinstance(v, str) and v.strip().lower() in ("true", "yes"))


class BehaviorAnalyzer:
    def __init__(self, threshold: float = DEFAULT_THRESHOLD, max_attempts: int = 3):
        self.threshold = threshold
        self.max_attempts = max_attempts
        self.stats = BehaviorAnalysisStats()

    def analyze(self, diagram_a: UnifiedClassDiagram, diagram_b: UnifiedClassDiagram,
                bodies: List[BodyChange], structural: List[ConflictItem]) -> List[ConflictItem]:
        self.stats.candidates = sum(b.decision in SEND for b in bodies)
        out: List[ConflictItem] = []
        for req in build_behavior_requests(diagram_a, diagram_b, bodies, structural):
            self.stats.requests += 1
            data = self._call(req)
            if data is None:
                self.stats.failed_requests += 1
                continue
            items = {i.id: i for i in req.items}
            seen = set()
            for r in data["results"]:
                item = items.get(str(r.get("id", "")))
                if item is None or item.id in seen:
                    self.stats.unknown_item_ids += item is None
                    continue
                seen.add(item.id)
                conflict = self._finding(r, item)
                if conflict is not None:
                    out.append(conflict)
        self.stats.flagged = len(out)
        return out

    def _call(self, req: BehaviorRequest) -> Optional[Dict]:
        for attempt in range(1, self.max_attempts + 1):
            try:
                raw = LLMClient.call_model(system_prompt=req.system, user_prompt=req.user, temperature=0.0,
                                           use_cache=(attempt == 1))
                return parse_response(raw)
            except Exception as e:
                logger.warning(f"BehaviorAnalyzer: attempt {attempt}/{self.max_attempts} failed — {e}")
        logger.error("BehaviorAnalyzer: all attempts failed; keeping structural results only")
        return None

    def _finding(self, r: Dict, item: BehaviorItem) -> Optional[ConflictItem]:
        self.stats.findings += 1
        if not _truthy(r.get("observable_change")):
            self.stats.not_observable += 1
            return None
        old = _strip_line_numbers(r.get("old_snippet") or "").strip()
        new = _strip_line_numbers(r.get("new_snippet") or "").strip()
        if (not old and not new) or (old and not quote_found(old, item.before)) \
                or (new and not quote_found(new, item.after)):
            self.stats.dropped_quote += 1
            return None
        change_type = r.get("change_type") if r.get("change_type") in CHANGE_TYPES else "other"
        confidence = _confidence(r.get("confidence"))
        breaking = _truthy(r.get("breaking"))
        record = {"class": item.class_name, "member": item.member, "change_type": change_type,
                  "breaking": breaking, "confidence": confidence}
        if not breaking:
            self.stats.non_breaking += 1
            self.stats.hidden.append(record)
            return None
        if confidence < self.threshold:
            self.stats.below_threshold += 1
            self.stats.hidden.append(record)
            return None
        evidence = " | ".join(x for x in (f'before: "{old}"' if old else "", f'after: "{new}"' if new else "") if x)
        return ConflictItem(
            type=ChangeType.BEHAVIOR_CHANGE,
            severity=SeverityLevel.HIGH,
            risk_level=RiskLevel.CRITICAL,
            decision=ChangeDecision(item.decision),
            category=f"behavior_{change_type}",
            class_name=item.class_name,
            member=item.member,
            description=str(r.get("explanation") or "Behavior change that breaks existing callers"),
            old_logic=str(r.get("before") or "") or None,
            new_logic=str(r.get("after") or "") or None,
            impact="Breaking change - existing callers get a different result",
            evidence=evidence,
            ai_confidence=confidence,
        )
