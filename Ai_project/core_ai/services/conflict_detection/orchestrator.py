# core_ai/services/conflict_detection/orchestrator.py
import os
from typing import Dict, Any, Optional
from .schemas import ConflictAnalysisResult
from .ast_unifier import ASTUnifier
from .structural_diff import StructuralDiff
from .body_comparer import BodyComparer
from .change_classifier import ChangeClassifier
from .risk_classifier import RiskClassifier
from .behavior_analyzer import DEFAULT_THRESHOLD as BEHAVIOR_THRESHOLD, BehaviorAnalyzer
from .code_doc_consistency import CodeDocConsistencyChecker
from .report_generator import ReportGenerator


class ConflictOrchestrator:
    """المنسق الرئيسي - يدير كل عمليات كشف التناقض"""

    @staticmethod
    def run_code_vs_code(
        analysis_a: Dict[str, Any],
        analysis_b: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None
    ) -> ConflictAnalysisResult:

        diagram_a = ASTUnifier.from_tree_sitter(analysis_a)
        diagram_b = ASTUnifier.from_tree_sitter(analysis_b)

        structural = StructuralDiff.compare(diagram_a, diagram_b)
        # الخطوة 8: مقارنة الأجسام — معلومة بالتقرير (body_changes)، مش تنبيه
        renames = {(c.class_name, c.old_value): c.new_value
                   for c in structural if c.category == "method_renamed" and c.old_value and c.new_value}
        body_changes = BodyComparer.compare_diagrams(diagram_a, diagram_b, renames)
        # الخطوة 9: قرار لكل دالة (توقيع × جسم)، وفلترة التافه، ودرجة أهمية للخطوة 11
        ChangeClassifier.classify_all(structural, body_changes)
        # الخطوة 10: مستوى خطر لكل تنبيه (الأعضاء الخاصين = معلومة، متل AexPy)
        RiskClassifier.classify(structural, diagram_a)
        # الخطوة 11: الذكاء الاصطناعي بس على الدوال المرشّحة (بدل SemanticAnalyzer القديم يلي كان
        # يبعت أسماء الدوال بس، بطلب بكل مقارنة). ما في مرشّحين → ولا طلب.
        # BEHAVIOR_LLM_ENABLED=0 بيوقّفه، و BEHAVIOR_CONFIDENCE_THRESHOLD للعتبة.
        semantic, behavior_stats = [], None
        if os.environ.get("BEHAVIOR_LLM_ENABLED", "1").strip().lower() not in ("0", "false", "no", "off"):
            analyzer = BehaviorAnalyzer(threshold=float(os.environ.get("BEHAVIOR_CONFIDENCE_THRESHOLD",
                                                                       BEHAVIOR_THRESHOLD)))
            semantic = analyzer.analyze(diagram_a, diagram_b, body_changes, structural)
            behavior_stats = analyzer.stats.model_dump()

        version_a = str(analysis_a.get("_id", "version_a"))
        version_b = str(analysis_b.get("_id", "version_b"))

        result = ReportGenerator.generate(
            analysis_type="code_vs_code",
            version_a=version_a,
            version_b=version_b,
            diagram_a=diagram_a,
            diagram_b=diagram_b,
            structural_changes=structural,
            semantic_conflicts=semantic,
            metadata=metadata
        )
        result.body_changes = body_changes
        result.behavior_analysis = behavior_stats
        return result

    @staticmethod
    def run_code_vs_doc(
        analysis: Dict[str, Any],
        explanation: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None
    ) -> ConflictAnalysisResult:

        diagram      = ASTUnifier.from_tree_sitter(analysis)
        doc_conflicts = CodeDocConsistencyChecker.compare(diagram, explanation)

        version_a = str(analysis.get("_id", "current"))

        return ReportGenerator.generate(
            analysis_type="code_vs_doc",
            version_a=version_a,
            diagram_a=diagram,
            doc_conflicts=doc_conflicts,
            metadata=metadata
        )

    @staticmethod
    def run_full_analysis(
        analysis_a:  Dict[str, Any],
        analysis_b:  Dict[str, Any],
        explanation: Optional[Dict[str, Any]] = None,
        metadata:    Optional[Dict[str, Any]] = None
    ) -> ConflictAnalysisResult:
        """Full Analysis = Code vs Code + Code vs Doc (إذا وُجد التوثيق)"""

        code_result = ConflictOrchestrator.run_code_vs_code(
            analysis_a, analysis_b, metadata
        )

        if explanation:
            doc_result = ConflictOrchestrator.run_code_vs_doc(
                analysis_b, explanation, metadata
            )
            return ReportGenerator.merge_results(code_result, doc_result, metadata)

        return code_result
