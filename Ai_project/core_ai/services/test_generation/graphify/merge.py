"""Joins the per-file graphs into one project graph with ids that are unique across the project.

Local ids become `filepath::Name`  (`filepath::Class`, `filepath::Class.method`,
`filepath::function`, `filepath::__module__`). External ids keep the form `ext.name` and are shared
between files. The unified shape (nodes / edges / meta) is kept.
"""

LOCAL_TYPES = ("module", "class", "method", "function")


def qualify(file_path, local_id):
    return f"{file_path}::{local_id}"


def _is_external(node_id):
    return isinstance(node_id, str) and node_id.startswith("ext.")


def merge(file_graphs):
    nodes, edges = {}, []

    for fg in file_graphs:
        path = fg["path"]

        for node in fg["graph"].get("nodes", []):
            old_id = node.get("id")
            if old_id is None:
                continue
            if _is_external(old_id) or node.get("type") == "external":
                nodes.setdefault(old_id, dict(node))
                continue
            new = dict(node)
            new["id"] = qualify(path, old_id)
            new["file"] = path
            if new.get("parent"):
                new["parent"] = qualify(path, new["parent"])
            nodes[new["id"]] = new

        # Every unit and class analysis knows about gets a node, even if the stored graph missed it.
        for class_name, cls in fg["classes"].items():
            class_id = qualify(path, class_name)
            nodes.setdefault(class_id, {"id": class_id, "label": class_name, "type": "class",
                                        "local": True, "file": path})
            for method_name in cls["methods"]:
                mid = qualify(path, f"{class_name}.{method_name}")
                nodes.setdefault(mid, {"id": mid, "label": f"{method_name}()", "type": "method",
                                       "parent": class_id, "local": True, "file": path})
        for func_name in fg["functions"]:
            fid = qualify(path, func_name)
            nodes.setdefault(fid, {"id": fid, "label": f"{func_name}()", "type": "function",
                                   "local": True, "file": path})

        for edge in fg["graph"].get("edges", []):
            new = dict(edge)
            for end in ("from", "to"):
                value = new.get(end)
                if value is not None and not _is_external(value):
                    new[end] = qualify(path, value)
            edges.append(new)

    return finalize({"nodes": list(nodes.values()), "edges": edges,
                     "meta": {"files": [fg["path"] for fg in file_graphs]}})


def finalize(graph):
    """Drops duplicate edges and externals nobody points at, then refreshes the counters."""
    seen, edges = set(), []
    for e in graph["edges"]:
        key = (e.get("from"), e.get("to"), e.get("relation"))
        if key in seen:
            continue
        seen.add(key)
        edges.append(e)

    used = {e.get("from") for e in edges} | {e.get("to") for e in edges}
    nodes = [n for n in graph["nodes"] if n.get("type") != "external" or n["id"] in used]

    meta = dict(graph.get("meta") or {})
    meta.update({"total_nodes": len(nodes), "total_edges": len(edges), "source": "merged"})
    return {"nodes": nodes, "edges": edges, "meta": meta}
