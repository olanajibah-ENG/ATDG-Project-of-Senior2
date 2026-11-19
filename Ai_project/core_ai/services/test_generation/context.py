"""The context of one unit: everything the language model is allowed to see about the project.

It holds the unit's own code, the class around it, the SIGNATURES of the local units it calls
directly, and the external names it uses. It never holds another unit's body and never a whole
file. All of it comes from what analysis already stored.
"""
import hashlib
import json

from core_ai.services.test_generation.languages.python_adapter import split_unit_id


def local_name(unit_id):
    """`path::Student.enroll` → `Student.enroll`."""
    return unit_id.partition("::")[2]


def test_name_stem(unit_id):
    """`path::Student.enroll` → `Student_enroll` (the <unit> part of a test name)."""
    return local_name(unit_id).replace(".", "_")


test_name_stem.__test__ = False      # a helper, not a pytest test


def _stored_signature(entry):
    return str(entry.get("signature") or entry.get("name") or "").lstrip("+-# ").strip()


def _signature(entry, in_class=False):
    """The unit's signature as Python source, with its default values: `__init__(self, title: str,
    capacity: int = 2)`. The stored signature leaves the defaults out, and a default sent alone as a
    JSON string ("2") read like the text "2" to the model. Without stored parameters, the stored
    signature is used as it is."""
    params = entry.get("parameters")
    name = entry.get("name")
    if params is None or not name:
        return _stored_signature(entry)

    decorators = [str(d) for d in entry.get("decorators") or []]
    parts = []
    if in_class and "staticmethod" not in decorators:
        parts.append("cls" if "classmethod" in decorators else "self")

    kinds = [p.get("kind") for p in params]
    last_positional_only = max((i for i, k in enumerate(kinds) if k == "positional_only"), default=None)
    star_written = "var_positional" in kinds
    for i, p in enumerate(params):
        kind = p.get("kind")
        if kind == "keyword_only" and not star_written:
            parts.append("*")
            star_written = True
        text = {"var_positional": "*", "var_keyword": "**"}.get(kind, "") + str(p.get("name"))
        if p.get("type"):
            text += f": {p['type']}"
        if p.get("default") is not None:
            text += f" = {p['default']}" if p.get("type") else f"={p['default']}"
        parts.append(text)
        if last_positional_only is not None and i == last_positional_only:
            parts.append("/")

    signature = f"{name}({', '.join(parts)})"
    if entry.get("return_type") and entry.get("return_type") != "Any":
        signature += f" -> {entry['return_type']}"
    return ("async " if entry.get("is_async") else "") + signature


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
            "signature": _signature(entry, in_class=class_entry is not None),
            # default_code is Python source: "2" is the integer 2, "'2'" would be the text '2'
            "parameters": [
                {"name": p.get("name"), "type": p.get("type"), "default_code": p.get("default")}
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
            "constructor": _signature(constructor, in_class=True) if constructor else None,
            "attributes": [{"name": a.get("name"), "type": a.get("type")}
                           for a in class_entry.get("attributes") or []],
        }

    for callee_id in unit.get("callees") or []:
        callee_path, callee_import = _importable(callee_id)
        item = {"id": callee_id, "signature": None,
                "import_statement": adapter.import_statement(callee_path, callee_import)}
        callee_analysis = analyses_by_path.get(callee_path)
        if callee_analysis is not None:
            callee_class, callee_entry = adapter.find_entry(callee_analysis, callee_id)
            if callee_entry is not None:
                # the signature only, never the body
                item["signature"] = _signature(callee_entry, in_class=callee_class is not None)
        context["callees"].append(item)

    return context


def context_hash(context, prompt_version):
    """Stable fingerprint of what is sent to the model. The key for reusing an earlier answer."""
    canonical = json.dumps({"prompt_version": prompt_version, "context": context},
                           sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
