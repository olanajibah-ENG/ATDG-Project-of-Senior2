"""Step 1 of a job: which version, which files, which levels."""
from dataclasses import dataclass, field
from typing import List

from core_ai.services.test_generation import errors
from core_ai.services.test_generation.languages.python_adapter import is_python
from core_ai.services.test_generation.statuses import Level


@dataclass
class Scope:
    project_id: str
    version_number: int
    paths: List[str]
    levels: List[str]
    files: List[dict] = field(default_factory=list)  # {file_id, path, file_type}


def resolve(data, reader):
    """`data` is already shape-checked by the serializer. Raises ApiError for 400 / 422."""
    project_id = data["project_id"]

    latest = reader.latest_version(project_id)
    if latest is None:
        raise errors.validation_error(
            "This project has no uploaded version.", {"project_id": project_id}
        )

    version_number = data.get("version_number")
    if version_number is None:
        version_number = latest
    elif not reader.version_exists(project_id, version_number):
        raise errors.validation_error(
            f"Version {version_number} does not exist for this project.",
            {"version_number": version_number, "latest_version": latest},
        )

    levels = list(data.get("levels") or Level.ALL)

    all_files = reader.files_of_version(project_id, version_number)
    paths = list(data.get("paths") or [])
    if paths:
        by_path = {f["path"]: f for f in all_files}
        unknown = [p for p in paths if p not in by_path]
        if unknown:
            raise errors.validation_error(
                "Some paths are not part of this version.", {"paths": unknown}
            )
        selected = [by_path[p] for p in dict.fromkeys(paths)]
    else:
        selected = list(all_files)

    selected = [f for f in selected if f.get("file_type") != "support"]
    if not any(is_python(f.get("file_type"), f.get("path")) for f in selected):
        raise errors.no_python_files()

    files = [{"file_id": f["file_id"], "path": f["path"], "file_type": f.get("file_type") or "unknown"}
             for f in selected]
    return Scope(project_id=project_id, version_number=version_number, paths=paths, levels=levels, files=files)
