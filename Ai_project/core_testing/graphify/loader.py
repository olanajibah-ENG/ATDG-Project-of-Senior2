"""Loads, for one file, the three things analysis already stored that the project graph needs:
the stored graph, the table of classes and units, and the top-level imports.

Nothing is written back; the stored graph is copied before use.
"""
import copy

from core_testing.languages.python_adapter import class_data


def _imports(analysis):
    """Top-level imports from the stored AST → [{module, name, asname, level}]."""
    tree = ((analysis or {}).get("ast_structure") or {}).get("ast_tree") or {}
    out = []
    for node in tree.get("body") or []:
        kind = node.get("node_type")
        if kind == "Import":
            for alias in node.get("names") or []:
                out.append({"module": alias.get("name"), "name": None,
                            "asname": alias.get("asname"), "level": 0})
        elif kind == "ImportFrom":
            for alias in node.get("names") or []:
                out.append({"module": node.get("module"), "name": alias.get("name"),
                            "asname": alias.get("asname"), "level": node.get("level") or 0})
    return out


def load_file(file_path, analysis):
    data = class_data(analysis)
    classes = {}
    for cls in data.get("classes") or []:
        name = cls.get("name")
        if not name:
            continue
        classes[name] = {
            "bases": list(cls.get("base_classes") or []),
            "methods": {m.get("name"): m for m in cls.get("methods") or [] if m.get("name")},
        }
    functions = {f.get("name"): f for f in data.get("module_functions") or [] if f.get("name")}

    graph = copy.deepcopy((analysis or {}).get("dependency_graph") or {})
    if not isinstance(graph, dict):
        graph = {}
    graph.setdefault("nodes", [])
    graph.setdefault("edges", [])

    return {
        "path": file_path,
        "graph": graph,
        "classes": classes,
        "functions": functions,
        "imports": _imports(analysis),
    }
