"""Python-specific part of planning: which functions and methods are units, and which are skipped.

Reads only what analysis stored in `class_diagram_data`. Rules, in order
(specs/001-test-job-plan/research.md, R5):
  name starts with `_` and is not a __dunder__      → skipped  private
  abstract, or body is only pass / ... / a docstring → skipped  empty_or_abstract
  body_truncated                                     → skipped  body_truncated
  otherwise                                          → a unit (kind: method | function)
A file with no function and no method at all is skipped as no_units.
"""
import ast
import json

from core_testing.statuses import SkipReason


def is_python(file_type, path=None):
    if (file_type or "").lower() == "python":
        return True
    return bool(path) and str(path).lower().endswith(".py") and (file_type or "unknown").lower() in ("unknown", "text", "")


def class_data(analysis):
    """`class_diagram_data` as a dict (analysis may have stored it as a JSON string)."""
    data = (analysis or {}).get("class_diagram_data") or {}
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except ValueError:
            data = {}
    return data if isinstance(data, dict) else {}


def unit_id(file_path, name, class_name=None):
    return f"{file_path}::{class_name}.{name}" if class_name else f"{file_path}::{name}"


def _is_private(name):
    return name.startswith("_") and not (name.startswith("__") and name.endswith("__"))


def _is_empty_body(body):
    text = (body or "").strip()
    if not text:
        return True
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return False
    for node in tree.body:
        if isinstance(node, ast.Pass):
            continue
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and (
            isinstance(node.value.value, str) or node.value.value is Ellipsis
        ):
            continue
        return False
    return True


def _is_abstract(entry):
    if entry.get("is_abstract"):
        return True
    return any("abstractmethod" in str(d) for d in entry.get("decorators") or [])


def _classify(entry):
    name = entry.get("name") or ""
    if _is_private(name):
        return SkipReason.PRIVATE
    if _is_abstract(entry) or _is_empty_body(entry.get("body")):
        return SkipReason.EMPTY_OR_ABSTRACT
    if entry.get("body_truncated"):
        return SkipReason.BODY_TRUNCATED
    return None


def list_units(file_path, analysis):
    """→ (units, skips). A unit is {id, file, kind, body_hash, line}."""
    data = class_data(analysis)
    entries = []
    for cls in data.get("classes") or []:
        for method in cls.get("methods") or []:
            entries.append((cls.get("name"), method))
    for func in data.get("module_functions") or []:
        entries.append((None, func))

    if not entries:
        return [], [{"path": file_path, "reason": SkipReason.NO_UNITS}]

    units, skips = [], []
    for class_name, entry in entries:
        uid = unit_id(file_path, entry.get("name"), class_name)
        reason = _classify(entry)
        if reason:
            skips.append({"path": file_path, "unit": uid, "reason": reason, "line": entry.get("line_start") or 0})
        else:
            units.append({
                "id": uid,
                "file": file_path,
                "kind": "method" if class_name else "function",
                "body_hash": entry.get("body_hash"),
                "line": entry.get("line_start") or 0,
            })
    units.sort(key=lambda u: u["line"])
    skips.sort(key=lambda s: s["line"])
    for s in skips:
        s.pop("line", None)
    return units, skips


# ── S2: what generation needs from a Python file ────────────────────────────

import builtins as _builtins  # noqa: E402

BUILTIN_NAMES = frozenset(dir(_builtins))


def split_unit_id(unit_id_value):
    """`path::Class.method` → (path, class | None, name)."""
    path, _, local = unit_id_value.partition("::")
    class_name, _, name = local.rpartition(".")
    return path, (class_name or None), name


def find_entry(analysis, unit_id_value):
    """→ (class_entry | None, unit_entry | None) from the stored class data."""
    _, class_name, name = split_unit_id(unit_id_value)
    data = class_data(analysis)
    if class_name:
        for cls in data.get("classes") or []:
            if cls.get("name") == class_name:
                for method in cls.get("methods") or []:
                    if method.get("name") == name:
                        return cls, method
                return cls, None
        return None, None
    for func in data.get("module_functions") or []:
        if func.get("name") == name:
            return None, func
    return None, None


def module_name(path):
    """`pkg/game.py` → `pkg.game`. A path with no extension is used as it is (`game` → `game`)."""
    text = str(path).replace("\\", "/")
    if text.lower().endswith(".py"):
        text = text[:-3]
    if text.endswith("/__init__"):
        text = text[: -len("/__init__")]
    return ".".join(part for part in text.split("/") if part)


def import_statement(path, name):
    return f"from {module_name(path)} import {name}"


def project_import_roots(project_paths):
    """Top-level names a test may import from the project itself."""
    return {module_name(p).split(".")[0] for p in project_paths if module_name(p)}
