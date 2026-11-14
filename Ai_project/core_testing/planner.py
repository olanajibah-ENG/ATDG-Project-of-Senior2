"""Builds the plan of a job: planned units, everything skipped with its reason, and the work-item count.

In S1 a work item is simply (unit, level): work_items_count = units × requested levels. Edge and
integration planning refine this in later slices.
"""
from core_testing.graphify import queries
from core_testing.languages import python_adapter


def build_plan(ready_files, skipped_files, levels, project_graph=None):
    """
    ready_files   : [(path, analysis)] — analysed Python files
    skipped_files : [{path, reason}]   — files the gate or the scope already gave up on
    → ({units, skipped, work_items_count}, no_unit_paths)
    """
    units, skipped, no_unit_paths = [], [], []
    for entry in sorted(skipped_files, key=lambda s: s["path"]):
        skipped.append({"path": entry["path"], "reason": entry["reason"]})

    for path, analysis in sorted(ready_files, key=lambda item: item[0]):
        file_units, file_skips = python_adapter.list_units(path, analysis)
        if not file_units and any("unit" not in s for s in file_skips):
            no_unit_paths.append(path)
        for unit in file_units:
            unit = dict(unit)
            unit.pop("line", None)
            unit["callees"] = queries.callees(project_graph, unit["id"]) if project_graph else []
            unit["externals"] = queries.externals(project_graph, unit["id"]) if project_graph else []
            units.append(unit)
        skipped.extend(file_skips)

    plan = {"units": units, "skipped": skipped, "work_items_count": len(units) * len(levels)}
    return plan, no_unit_paths
