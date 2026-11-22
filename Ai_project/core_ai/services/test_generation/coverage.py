"""Coverage figures (S3).

- record_contribution(): what one record's own run covered — labelled as such, never the job's figure.
- job_report(): the official report, built ONLY from the final run in which every test passed (FR-017).
"""

CONTRIBUTION_LABEL = "this record's own run"


def record_contribution(reduced):
    if not reduced:
        return None
    return {
        "label": CONTRIBUTION_LABEL,
        "files": [{"file": path, "covered_lines": data["executed_lines"], "covered_branches": data["branches_covered"]}
                  for path, data in sorted(reduced["files"].items())],
    }


def _pct(part, whole):
    return round(100.0 * part / whole, 2) if whole else 100.0


def skipped_ranges(plan, entry_of):
    """[(path, first line, last line, text)] for every unit the plan skipped.

    `entry_of(path, unit_id)` returns the unit's stored details (with line_start / line_end) or None.
    """
    out = []
    for skip in (plan or {}).get("skipped") or []:
        unit_id = skip.get("unit")
        if not unit_id:
            continue
        entry = entry_of(skip["path"], unit_id) or {}
        start = int(entry.get("line_start") or skip.get("line") or 0)
        end = int(entry.get("line_end") or start)
        if start:
            name = unit_id.partition("::")[2] or unit_id
            out.append((skip["path"], start, end, f"{name} — skipped: {skip.get('reason')}"))
    return out


def job_report(reduced, *, final_run_id, ready_count, plan_ranges, version_paths, excluded=()):
    """The coverage report of data-model.md, from the reduced coverage of the all-pass final run."""
    files, totals = [], {"statements": 0, "covered": 0, "branches": 0, "branches_covered": 0}
    for path, data in sorted((reduced or {}).get("files", {}).items()):
        annotations = {}
        for line in data["missing_lines"]:
            for r_path, start, end, text in plan_ranges:
                if r_path == path and start <= line <= end:
                    annotations[str(line)] = text
                    break
        files.append({
            "file": path,
            "statements": data["statements"], "covered": data["covered"],
            "line_pct": _pct(data["covered"], data["statements"]),
            "branches": data["branches"], "branches_covered": data["branches_covered"],
            "branch_pct": _pct(data["branches_covered"], data["branches"]),
            "missing_lines": data["missing_lines"],
            "missing_annotations": annotations,
        })
        for key in totals:
            totals[key] += data[key]
    totals.update(
        line_pct=_pct(totals["covered"], totals["statements"]),
        branch_pct=_pct(totals["branches_covered"], totals["branches"]),
        combined_pct=_pct(totals["covered"] + totals["branches_covered"], totals["statements"] + totals["branches"]),
    )
    measured = {f["file"] for f in files}
    not_measured = [{"file": p, "reason": "unsupported_language"}
                    for p in sorted(version_paths) if not p.endswith(".py") and p not in measured]
    return {
        "available": True,
        "final_run_id": final_run_id,
        "branch": True,
        "scope": f"ready records only ({ready_count})",
        "files": files,
        "totals": totals,
        "not_measured": not_measured,
        "excluded_records": [{"record_id": rid, "reason": reason} for rid, reason in excluded],
    }


def unavailable(reason, detail=None):
    out = {"available": False, "reason": reason}
    if detail:
        out["detail"] = detail
    return out


def totals_only(report):
    """What the job status shows: just the three percentages, or None."""
    if not report or not report.get("available"):
        return None
    t = report["totals"]
    return {"line_pct": t["line_pct"], "branch_pct": t["branch_pct"], "combined_pct": t["combined_pct"]}
