"""Questions asked of the project graph. S1 needs one: which local units does a unit call directly."""

UNIT_TYPES = ("method", "function")


def callees(project_graph, unit_id):
    unit_ids = {n["id"] for n in project_graph["nodes"] if n.get("type") in UNIT_TYPES}
    out = []
    for edge in project_graph["edges"]:
        if edge.get("relation") != "calls" or edge.get("from") != unit_id:
            continue
        target = edge.get("to")
        if target in unit_ids and target != unit_id and target not in out:
            out.append(target)
    return out
