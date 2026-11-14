"""The context of one unit: everything the language model is allowed to see about the project.

It holds the unit's own code, the class around it, the SIGNATURES of the local units it calls
directly, and the external names it uses. It never holds another unit's body and never a whole
file. All of it comes from what analysis already stored.
"""
import hashlib
import json

from core_testing.languages.python_adapter import split_unit_id


def local_name(unit_id):
    """`path::Student.enroll` → `Student.enroll`."""
    return unit_id.partition("::")[2]


def test_name_stem(unit_id):
    """`path::Student.enroll` → `Student_enroll` (the <unit> part of a test name)."""
    return local_name(unit_id).replace(".", "_")


test_name_stem.__test__ = False      # a helper, not a pytest test


def _signature(entry):
    return str(entry.get("signature") or entry.get("name") or "").lstrip("+-# ").strip()


def _importable(unit_id):
    path, class_name, name = split_unit_id(unit_id)
    return path, class_name or name


def build_unit_context(unit, analyses_by_path, adapter, level="unit"):
    """`unit` is a planned unit: {id, file, kind, callees, externals, ...}. → dict, or None when the
    unit's stored details cannot be found."""
    analysis = analyses_by_path.get(unit["file"])
    if analysis is None:
        return None
    class_entry, entry = adapter.find_entry(analysis, unit["id"])
    if entry is None:
        return None

    path, import_name = _importable(unit["id"])
    context = {
        "kind": level,
        "unit": {
            "id": unit["id"],
            "name": entry.get("name"),
            "kind": unit.get("kind"),
            "import_statement": adapter.import_statement(path, import_name),
            "signature": _signature(entry),
            "parameters": [
                {"name": p.get("name"), "type": p.get("type"), "default": p.get("default")}
                for p in entry.get("parameters") or []
            ],
            "return_type": entry.get("return_type"),
            "decorators": list(entry.get("decorators") or []),
            "docstring": entry.get("docstring"),
            "body": entry.get("body") or "",
        },
        "class": None,
        "callees": [],
        "externals": list(unit.get("externals") or []),
        "rules": {
            "framework": adapter.test_framework,
            "test_name": f"test_{test_name_stem(unit['id'])}__{level}_<n>",
        },
    }

    if class_entry is not None:
        constructor = next((m for m in class_entry.get("methods") or [] if m.get("name") == "__init__"), None)
        context["class"] = {
            "name": class_entry.get("name"),
            "bases": list(class_entry.get("base_classes") or []),
            "constructor": _signature(constructor) if constructor else None,
            "attributes": [{"name": a.get("name"), "type": a.get("type")}
                           for a in class_entry.get("attributes") or []],
        }

    for callee_id in unit.get("callees") or []:
        callee_path, callee_import = _importable(callee_id)
        item = {"id": callee_id, "signature": None,
                "import_statement": adapter.import_statement(callee_path, callee_import)}
        callee_analysis = analyses_by_path.get(callee_path)
        if callee_analysis is not None:
            _, callee_entry = adapter.find_entry(callee_analysis, callee_id)
            if callee_entry is not None:
                item["signature"] = _signature(callee_entry)   # the signature only, never the body
        context["callees"].append(item)

    return context


def context_hash(context, prompt_version):
    """Stable fingerprint of what is sent to the model. The key for reusing an earlier answer."""
    canonical = json.dumps({"prompt_version": prompt_version, "context": context},
                           sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
