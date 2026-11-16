"""Links calls to the local unit they really reach.

The stored graph leaves some calls as external or dangling (`course.add_student(...)` is stored as
`ext.course.add_student`, `super().__init__` as `ext.super`). This pass re-reads each unit's stored
body with Python's `ast` and resolves, in order:

  self.m() / cls.m()   → the class, then its bases
  super().m()          → the bases
  param.m()            → the parameter's type annotation
  var.m()              → a variable assigned from a local class in the same body
  Class.m()            → that class
  name()               → a local function, or a local class's constructor
  imported names       → the unit in the other project file

It writes nothing back to analysis. A unit whose body is truncated or does not parse keeps its
stored edges as they are.
"""
import ast
import posixpath
import re
import textwrap

from core_ai.services.test_generation.graphify.merge import finalize, qualify

_TYPE_RE = re.compile(r"^(?:Optional\[)?\s*([A-Za-z_][\w.]*)\s*\]?(?:\s*\|\s*None)?$")


def _module_file(module, level, current_path, all_paths):
    """The project file an import refers to, or None when it is not part of the project."""
    parts = [p for p in (module or "").split(".") if p]
    current_dir = posixpath.dirname(current_path)
    if level:
        base = current_dir
        for _ in range(level - 1):
            base = posixpath.dirname(base)
        candidates = []
        if parts:
            candidates.append(posixpath.join(base, *parts) + ".py")
        candidates.append(posixpath.join(base, *parts, "__init__.py"))
        return next((c for c in candidates if c in all_paths), None)
    if not parts:
        return None
    suffix = "/".join(parts) + ".py"
    sibling = posixpath.join(current_dir, suffix) if current_dir else suffix
    if sibling in all_paths:
        return sibling
    matches = sorted(p for p in all_paths if p == suffix or p.endswith("/" + suffix))
    return matches[0] if matches else None


def _clean_type(annotation):
    if not annotation:
        return None
    match = _TYPE_RE.match(str(annotation).strip().strip("'\""))
    return match.group(1).split(".")[-1] if match else None


class _Index:
    def __init__(self, file_graphs):
        self.classes = {}      # (path, class) -> {"bases": [...], "methods": set}
        self.functions = set()  # (path, function)
        self.names = {}        # path -> {local name: ("class" | "function", path, name)}
        paths = {fg["path"] for fg in file_graphs}

        for fg in file_graphs:
            path = fg["path"]
            for name, cls in fg["classes"].items():
                self.classes[(path, name)] = {"bases": cls["bases"], "methods": set(cls["methods"])}
            for name in fg["functions"]:
                self.functions.add((path, name))

        for fg in file_graphs:
            path = fg["path"]
            table = {}
            for imp in fg["imports"]:
                if not imp.get("name") or imp["name"] == "*":
                    continue
                target = _module_file(imp.get("module"), imp.get("level") or 0, path, paths)
                if target is None:
                    continue
                local = imp.get("asname") or imp["name"]
                if (target, imp["name"]) in self.classes:
                    table[local] = ("class", target, imp["name"])
                elif (target, imp["name"]) in self.functions:
                    table[local] = ("function", target, imp["name"])
            for name in fg["classes"]:
                table[name] = ("class", path, name)
            for name in fg["functions"]:
                table[name] = ("function", path, name)
            self.names[path] = table

    def class_ref(self, path, name):
        ref = self.names.get(path, {}).get(name)
        return (ref[1], ref[2]) if ref and ref[0] == "class" else None

    def find_method(self, owner, method, *, skip_self=False, _seen=None):
        """(path, class) that defines `method`, searching the class and then its bases."""
        seen = _seen if _seen is not None else set()
        if owner in seen or owner not in self.classes:
            return None
        seen.add(owner)
        cls = self.classes[owner]
        if not skip_self and method in cls["methods"]:
            return owner
        for base in cls["bases"]:
            base_ref = self.class_ref(owner[0], str(base).split(".")[-1])
            if base_ref:
                found = self.find_method(base_ref, method, _seen=seen)
                if found:
                    return found
        return None


def _method_id(owner, method):
    return qualify(owner[0], f"{owner[1]}.{method}")


def _resolve_unit(index, path, class_name, entry):
    """→ (targets, handled) or None when the body cannot be read."""
    if entry.get("body_truncated"):
        return None
    try:
        tree = ast.parse(textwrap.dedent(entry.get("body") or ""))
    except SyntaxError:
        return None

    var_types = {}
    for param in entry.get("parameters") or []:
        ref = index.class_ref(path, _clean_type(param.get("type")) or "")
        if ref:
            var_types[param.get("name")] = ref
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            value = node.value
            if isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
                ref = index.class_ref(path, value.func.id)
                if ref:
                    var_types[node.targets[0].id] = ref
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            ref = index.class_ref(path, _clean_type(ast.unparse(node.annotation)) or "")
            if ref:
                var_types[node.target.id] = ref

    targets, handled = [], set()

    def add(target, raw):
        handled.add(raw)
        if target and target not in targets:
            targets.append(target)

    own = (path, class_name) if class_name else None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            ref = index.names.get(path, {}).get(func.id)
            if not ref:
                continue
            if ref[0] == "function":
                add(qualify(ref[1], ref[2]), func.id)
            else:
                owner = index.find_method((ref[1], ref[2]), "__init__")
                add(_method_id(owner, "__init__") if owner else qualify(ref[1], ref[2]), func.id)
        elif isinstance(func, ast.Attribute):
            value, owner, raw, skip_self = func.value, None, None, False
            if isinstance(value, ast.Name):
                raw = f"{value.id}.{func.attr}"
                if value.id in ("self", "cls") and own:
                    owner = own
                elif value.id in var_types:
                    owner = var_types[value.id]
                else:
                    owner = index.class_ref(path, value.id)
            elif isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
                if value.func.id == "super" and own:
                    owner, raw, skip_self = own, "super", True
                else:
                    owner, raw = index.class_ref(path, value.func.id), f"{value.func.id}.{func.attr}"
            if owner is None:
                continue
            found = index.find_method(owner, func.attr, skip_self=skip_self)
            if found:
                add(_method_id(found, func.attr), raw)
    return targets, handled


def resolve_calls(project_graph, file_graphs):
    index = _Index(file_graphs)
    node_ids = {n["id"] for n in project_graph["nodes"]}
    class_ids = {n["id"] for n in project_graph["nodes"] if n.get("type") == "class"}
    edges = list(project_graph["edges"])

    for fg in file_graphs:
        path = fg["path"]
        units = [(None, name, entry) for name, entry in fg["functions"].items()]
        for class_name, cls in fg["classes"].items():
            units += [(class_name, name, entry) for name, entry in cls["methods"].items()]

        for class_name, name, entry in units:
            resolved = _resolve_unit(index, path, class_name, entry)
            if resolved is None:
                continue
            targets, handled = resolved
            uid = qualify(path, f"{class_name}.{name}" if class_name else name)
            constructors = {t.rsplit(".__init__", 1)[0] for t in targets if t.endswith(".__init__")}

            def superseded(edge):
                if edge.get("relation") != "calls" or edge.get("from") != uid:
                    return False
                to = edge.get("to") or ""
                if to.startswith("ext."):
                    return to[4:] in handled
                return to in class_ids and to in constructors

            edges = [e for e in edges if not superseded(e)]
            edges += [{"from": uid, "to": t, "relation": "calls", "confidence": "EXTRACTED",
                       "resolved_by": "core_ai.services.test_generation"} for t in targets]

    # A graph must be well formed: an edge whose end is not a node is dropped and counted.
    kept = [e for e in edges if e.get("from") in node_ids and e.get("to") in node_ids]
    meta = dict(project_graph.get("meta") or {})
    meta["dropped_dangling_edges"] = len(edges) - len(kept)
    return finalize({"nodes": project_graph["nodes"], "edges": kept, "meta": meta})
