"""Request validation and response shaping for the three test routes."""
from rest_framework import serializers

from core_ai.services.test_generation import errors
from core_ai.services.test_generation.statuses import Level


class StartJobSerializer(serializers.Serializer):
    project_id = serializers.CharField(max_length=255, trim_whitespace=True)
    version_number = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    paths = serializers.ListField(
        child=serializers.CharField(allow_blank=False), required=False, allow_empty=True, allow_null=True
    )
    levels = serializers.ListField(
        child=serializers.ChoiceField(choices=Level.ALL), required=False, allow_empty=False, allow_null=True
    )

    def validate_levels(self, value):
        if value and len(set(value)) != len(value):
            raise serializers.ValidationError("A level may be listed only once.")
        return value


def validate_start_request(data):
    if not isinstance(data, dict):
        raise errors.validation_error("The request body must be a JSON object.")
    if "snapshot" in data:
        raise errors.validation_error(
            "File content is never sent. Use project_id, version_number and paths.",
            {"fields": ["snapshot"]},
        )
    serializer = StartJobSerializer(data=data)
    if not serializer.is_valid():
        raise errors.validation_error("Invalid request.", {"fields": serializer.errors})
    return serializer.validated_data


def start_response(job):
    return {
        "job_id": job["job_id"],
        "status": job["status"],
        "project_id": job["project_id"],
        "version_number": job["version_number"],
    }


_EMPTY_COUNTS = {"pending": 0, "generated": 0, "ready": 0, "skipped": 0,
                 "generation_failed": 0, "test_failed": 0, "environment_error": 0}


def _summary(statuses):
    """One word for a set of record statuses."""
    kinds = set(statuses)
    if not kinds or kinds == {"pending"}:
        return "pending"
    if kinds == {"generated"}:
        return "generated"
    if kinds == {"ready"}:
        return "ready"
    if kinds <= {"generation_failed", "test_failed", "environment_error"}:
        return "failed"
    return "partial"


def status_response(job, records=None):
    by_file = {}
    for record in records or []:
        by_file.setdefault(record["file"], {}).setdefault(record["level"], []).append(record["status"])

    files = []
    for entry in job.get("files") or []:
        item = {"path": entry["path"], "status": entry.get("status") or "pending"}
        if entry.get("reason"):
            item["reason"] = entry["reason"]
        levels = by_file.get(entry["path"])
        if levels and item["status"] != "skipped":
            item["levels"] = {level: _summary(statuses) for level, statuses in levels.items()}
            # the file's own status follows the level that has been worked on so far
            item["status"] = _summary(levels.get("unit", []))
        files.append(item)

    progress = job.get("progress") or {"total": 0, "done": 0, "by_status": dict(_EMPTY_COUNTS)}
    return {
        "job_id": job["job_id"],
        "project_id": job["project_id"],
        "version_number": job["version_number"],
        "status": job["status"],
        "stage": job["stage"],
        "progress": progress,
        "files": files,
        "coverage": _coverage_totals(job),
        "error": job.get("error"),
    }


def _coverage_totals(job):
    from core_ai.services.test_generation.coverage import totals_only

    return totals_only(job.get("coverage"))


def coverage_response(job):
    return job.get("coverage") or {"available": False, "reason": "no_ready_tests"}


def plan_response(job):
    plan = job["plan"]
    return {
        "units": [{"id": u["id"], "file": u["file"], "kind": u["kind"]} for u in plan["units"]],
        "skipped": plan["skipped"],
        "work_items_count": plan["work_items_count"],
    }


# ── records ─────────────────────────────────────────────────────────────────

NOT_RUN_NOTICE = "This test was generated and checked for form only. It has not been run."
_SHOW_CODE = ("generated", "ready", "test_failed", "environment_error")


def _notice(record, version_number):
    status = record["status"]
    if status == "ready":
        return (f"This test was run in an isolated environment on version {version_number} and passed. "
                "It shows the test runs on this version; it does not prove the code's logic is correct.")
    if status in ("test_failed", "environment_error") and record.get("executed") is not None:
        return (f"This test was run in an isolated environment on version {version_number} and did not "
                f"pass: {record.get('reason_code')}.")
    return NOT_RUN_NOTICE


def validate_record_filters(query):
    from core_ai.services.test_generation.statuses import RECORD_STATUSES, Level

    filters = {}
    status = query.get("status")
    if status:
        if status not in RECORD_STATUSES:
            raise errors.validation_error("Unknown status.", {"status": status, "allowed": list(RECORD_STATUSES)})
        filters["status"] = status
    level = query.get("level")
    if level:
        if level not in Level.ALL:
            raise errors.validation_error("Unknown level.", {"level": level, "allowed": list(Level.ALL)})
        filters["level"] = level
    if query.get("path"):
        filters["path"] = query.get("path")
    return filters


def _record_item(record):
    return {
        "id": record["record_id"],
        "file": record["file"],
        "unit_id": record["unit_id"],
        "level": record["level"],
        "status": record["status"],
        "reason_code": record.get("reason_code"),
        "test_path": record.get("test_path"),
        "executed": bool(record.get("executed")),
    }


def records_response(records):
    return {"items": [_record_item(r) for r in records], "total": len(records)}


def record_detail_response(record, version_number=None):
    item = _record_item(record)
    run = record.get("run_result") or None
    item.update({
        "reason_detail": record.get("reason_detail"),
        "test_code": record.get("test_code") if record["status"] in _SHOW_CODE else None,
        "notice": _notice(record, version_number),
        "run": ({"run_id": record.get("run_id"), "exit_code": run.get("exit_code"),
                 "duration_s": run.get("duration_s"), "tests": run.get("tests") or [],
                 "output": run.get("output")} if run else None),
        "evidence": record.get("evidence") if record["status"] == "ready" else None,
        "coverage_contribution": record.get("coverage_contribution") if record["status"] == "ready" else None,
        "model": record.get("model"),
        "prompt_version": record.get("prompt_version"),
    })
    return item
