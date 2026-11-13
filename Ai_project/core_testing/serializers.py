"""Request validation and response shaping for the three test routes."""
from rest_framework import serializers

from core_testing import errors
from core_testing.statuses import Level


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


def status_response(job):
    files = []
    for entry in job.get("files") or []:
        item = {"path": entry["path"], "status": entry.get("status") or "pending"}
        if entry.get("reason"):
            item["reason"] = entry["reason"]
        files.append(item)
    progress = job.get("progress") or {
        "total": 0, "done": 0,
        "by_status": {"pending": 0, "ready": 0, "skipped": 0,
                      "generation_failed": 0, "test_failed": 0, "environment_error": 0},
    }
    return {
        "job_id": job["job_id"],
        "project_id": job["project_id"],
        "version_number": job["version_number"],
        "status": job["status"],
        "stage": job["stage"],
        "progress": progress,
        "files": files,
        "error": job.get("error"),
    }


def plan_response(job):
    plan = job["plan"]
    return {
        "units": [{"id": u["id"], "file": u["file"], "kind": u["kind"]} for u in plan["units"]],
        "skipped": plan["skipped"],
        "work_items_count": plan["work_items_count"],
    }
