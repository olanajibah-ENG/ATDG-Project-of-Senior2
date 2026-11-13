"""
GenericProcessor
================
Regex fallback — يُستخدم فقط للغات غير مدعومة من tree-sitter-languages.
لو اللغة مدعومة → يستخدم TreeSitterProcessor.
لو اللغة مجهولة تماماً → هذا الملف.
"""

import re
import logging
from typing import Dict, Any, List

from .base_processor import ILanguageProcessorStrategy

logger = logging.getLogger(__name__)

_DEFAULT_PATTERNS: Dict[str, str] = {
    "functions":   r"(?:func|function|def|fn|sub|procedure)\s+(\w+)\s*\(",
    "classes":     r"(?:class|struct|interface|type|record|trait)\s+(\w+)",
    "imports":     r"(?:import|include|require|use|using)\s+['\"]?([\w./\\-]+)['\"]?",
    "comments":    r"(?://|#|--|%).*",
    "block_open":  r"\b(if|for|while|switch|else|case|catch)\b",
}


class GenericProcessor(ILanguageProcessorStrategy):

    def __init__(self, file_type: str = "unknown"):
        self.file_type = file_type
        logger.info(f"[GenericProcessor] Regex fallback for file_type='{file_type}'")

    def parse_source_code(self, code_content: str) -> Dict[str, Any]:
        if not code_content or not code_content.strip():
            return {"ast_tree": None, "code_content": "", "language": self.file_type, "error": "Empty file"}
        return {"ast_tree": None, "code_content": code_content, "language": self.file_type}

    def extract_features(self, ast_data: Dict[str, Any]) -> Dict[str, Any]:
        code  = ast_data.get("code_content", "")
        p     = _DEFAULT_PATTERNS
        funcs   = self._find(p["functions"], code)
        classes = self._find(p["classes"],   code)
        lines   = code.splitlines()
        total   = len(lines)
        comments= len(re.findall(p["comments"], code))
        blank   = sum(1 for l in lines if not l.strip())
        complexity = len(re.findall(p["block_open"], code))
        return {
            "language":            self.file_type,
            "lines_of_code":       max(0, total - comments - blank),
            "total_lines":         total,
            "comment_lines":       comments,
            "blank_lines":         blank,
            "comment_ratio":       round(comments / total, 2) if total else 0.0,
            "num_functions":       len(funcs),
            "num_classes":         len(classes),
            "complexity_score":    complexity,
            "num_inheritances":    0,
            "num_async_functions": 0,
            "functions":           funcs,
            "classes":             classes,
        }

    def extract_dependencies(self, ast_data: Dict[str, Any]) -> List[str]:
        code = ast_data.get("code_content", "")
        return list(dict.fromkeys(self._find(_DEFAULT_PATTERNS["imports"], code)))

    def perform_semantic_analysis(self, ast_data: Dict[str, Any], features: Dict[str, Any]) -> Dict[str, Any]:
        issues, warnings = [], []
        loc        = features.get("lines_of_code",    0)
        complexity = features.get("complexity_score", 0)
        ratio      = features.get("comment_ratio",    0.0)
        if loc > 500:
            warnings.append(f"File is large ({loc} lines).")
        if complexity > 30:
            issues.append(f"High complexity ({complexity}).")
        elif complexity > 15:
            warnings.append(f"Moderate complexity ({complexity}).")
        if ratio < 0.05 and loc > 50:
            warnings.append("Low comment coverage (< 5%).")
        penalty = (len(issues) * 8) + (len(warnings) * 3) + (complexity * 0.2)
        return {
            "quality_score": round(max(0.0, 100.0 - penalty), 2),
            "issues":        issues,
            "warnings":      warnings,
            "complexity":    complexity,
            "analysis_note": f"Regex-based fallback for unsupported language '{self.file_type}'.",
        }

    def generate_class_diagram_data(self, ast_data: Dict[str, Any], features: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "classes":       [{"name": n, "type": "class", "methods": [], "attributes": [], "relationships": []}
                              for n in features.get("classes", [])],
            "relationships": [],
        }

    def generate_dependency_graph_data(self, ast_data: Dict[str, Any], features: Dict[str, Any]) -> Dict[str, Any]:
        """
        🔥 Graphify Unified Schema Implementation for Generic (Regex fallback)
        توليد بيانات dependency_graph بالشكل الموحد
        ✅ nodes: module + imports (محدود)
        ✅ edges: imports فقط (calls محدود جداً)
        ✅ confidence: INFERRED (regex-based)
        """
        deps = self.extract_dependencies(ast_data)
        code = ast_data.get("code_content", "")
        funcs = features.get("functions", [])
        classes = features.get("classes", [])
        
        nodes = []
        edges = []
        node_ids = set()
        
        # إضافة module node
        node_ids.add("__module__")
        nodes.append({
            "id": "__module__",
            "label": f"[{self.file_type}] Module",
            "type": "module",
            "local": True
        })
        
        # إضافة classes
        for cls in classes:
            if cls not in node_ids:
                node_ids.add(cls)
                nodes.append({
                    "id": cls,
                    "label": cls,
                    "type": "class",
                    "local": True
                })
        
        # إضافة functions
        for func in funcs:
            if func not in node_ids:
                node_ids.add(func)
                nodes.append({
                    "id": func,
                    "label": f"{func}()",
                    "type": "function",
                    "local": True
                })
        
        # إضافة imports
        for dep in deps:
            dep_id = f"ext.{dep}"
            if dep_id not in node_ids:
                node_ids.add(dep_id)
                nodes.append({
                    "id": dep_id,
                    "label": dep,
                    "type": "external",
                    "local": False
                })
            
            # edge للـ import
            edges.append({
                "from": "__module__",
                "to": dep_id,
                "relation": "imports",
                "confidence": "INFERRED"  # regex-based, not 100% accurate
            })
        
        # محاولة استخراج calls بسيطة (محدودة جداً)
        # نبحث عن أسماء الدوال في الكود
        for func in funcs:
            # بحث بسيط عن استدعاءات
            pattern = rf'\b{func}\s*\('
            if re.search(pattern, code):
                # محاولة تحديد من أي دالة تم الاستدعاء (صعب مع regex)
                # نكتفي بـ edge عام من module
                edges.append({
                    "from": "__module__",
                    "to": func,
                    "relation": "calls",
                    "confidence": "INFERRED"
                })
        
        return {
            "nodes": nodes,
            "edges": edges,
            "meta": {
                "total_nodes": len(nodes),
                "total_edges": len(edges),
                "source": "regex"
            }
        }

    @staticmethod
    def _find(pattern: str, code: str) -> List[str]:
        names = []
        try:
            for m in re.finditer(pattern, code, re.MULTILINE):
                name = next((g for g in m.groups() if g), None)
                if name:
                    names.append(name)
        except re.error:
            pass
        return names
