"""
project_versioning.py — how a new project version is built from the previous one.

A version is a table   path → file.   Every path appears at most once.

Rules
-----
1. A file is identified in a version by its PATH. Its record (file_id) is reused only when the
   same path has the same content; otherwise the upload creates a new record.
2. The new version starts from the previous version's table:
     - every uploaded file replaces the entry with the same path, or is added
     - full upload    : a path of the previous version that was not uploaded is DELETED
     - partial upload : a path that was not uploaded is carried over unchanged,
                        except the paths listed in `deleted_paths`
3. The status of each path is decided by comparing with the previous version at that path:
     new        the path did not exist before
     modified   the path existed with another file_id
     unchanged  same path, same file_id
     deleted    the path existed and is not in the new version

Which mode
----------
     ZIP upload (from the UI, or from conflict detection)   → full
     loose files, GitHub sync                               → partial
An explicit `upload_mode` sent by the caller wins.

Nothing here touches the database: it is plain data in, plain data out.
"""

FULL = "full"
PARTIAL = "partial"
MODES = (FULL, PARTIAL)

NEW = "new"
MODIFIED = "modified"
UNCHANGED = "unchanged"
DELETED = "deleted"


def infer_mode(explicit=None, has_zip=False):
    if explicit in MODES:
        return explicit
    return FULL if has_zip else PARTIAL


def _path(entry):
    return (entry.get("filepath") or entry.get("filename") or "").replace("\\", "/")


def dedupe_by_path(entries):
    """One entry per path, keeping the newest file (highest version_number).

    Versions saved before this fix can list the same path twice (the old file was carried over next
    to its modified copy). Reading through this function shows them correctly.
    """
    best, order = {}, []
    for entry in entries or []:
        path = _path(entry)
        if not path:
            continue
        if path not in best:
            order.append(path)
            best[path] = entry
        elif int(entry.get("version_number") or 0) > int(best[path].get("version_number") or 0):
            best[path] = entry
    return [best[p] for p in order]


def _entry(source, status):
    return {
        "file_id": str(source["file_id"]),
        "filename": source.get("filename") or _path(source).rsplit("/", 1)[-1],
        "filepath": _path(source),
        "file_type": source.get("file_type") or "unknown",
        "version_number": source.get("version_number"),
        "status": status,
    }


def build_version(prev_entries, uploaded, mode, deleted_paths=()):
    """
    prev_entries  : files of the previous version  [{file_id, filepath, filename, file_type, version_number}]
    uploaded      : files saved by this upload      (same shape)
    mode          : "full" or "partial"
    deleted_paths : paths removed explicitly (partial mode; GitHub "removed" / "renamed")

    → {"file_ids": [...], "file_changes": [...], "counts": {...}}
      file_ids     : the files of the new version (no deleted ones)
      file_changes : the same files with their status, followed by the deleted paths
    """
    if mode not in MODES:
        raise ValueError(f"unknown upload mode: {mode!r}")

    prev = {_path(e): e for e in dedupe_by_path(prev_entries)}
    removed = {str(p).replace("\\", "/") for p in (deleted_paths or ()) if p}

    current = {}
    for item in uploaded or []:                      # the last one wins if a path repeats
        current[_path(item)] = item

    changes = []
    for path, item in current.items():
        before = prev.get(path)
        if before is None:
            status = NEW
        elif str(before["file_id"]) == str(item["file_id"]):
            status = UNCHANGED
        else:
            status = MODIFIED
        changes.append(_entry(item, status))

    deleted = []
    for path, before in prev.items():
        if path in current:
            continue
        if mode == FULL or path in removed:
            deleted.append(_entry(before, DELETED))
        else:
            changes.append(_entry(before, UNCHANGED))

    changes.sort(key=lambda e: e["filepath"])
    deleted.sort(key=lambda e: e["filepath"])

    counts = {
        "total_files": len(changes),
        "new_files": sum(1 for e in changes if e["status"] == NEW),
        "modified_files": sum(1 for e in changes if e["status"] == MODIFIED),
        "unchanged_files": sum(1 for e in changes if e["status"] == UNCHANGED),
        "deleted_files": len(deleted),
    }
    return {"file_ids": [e["file_id"] for e in changes], "file_changes": changes + deleted, "counts": counts}


def visible_files(version_doc):
    """The files of a stored version, one per path, deleted ones left out.

    Uses `file_changes` when the version has it (it carries the path the file had in THIS version),
    and falls back to `file_ids` for older documents (the caller resolves those)."""
    changes = version_doc.get("file_changes") or []
    if not changes:
        return None
    return dedupe_by_path([c for c in changes if c.get("status") != DELETED])


# ── guard against a full upload that would delete most of the project ────────

MASS_DELETION_MIN_FILES = 2      # deleting fewer files than this never needs a confirmation


def _top_folder_hint(prev_paths, new_paths):
    """'demo/' when the new paths are the old ones with a top folder added or taken away, else None."""
    prev_paths, new_paths = set(prev_paths), set(new_paths)
    if not prev_paths or not new_paths:
        return None
    tops = {p.split("/", 1)[0] + "/" for p in prev_paths if "/" in p}
    for top in tops:                                   # the zip lost the top folder: demo/x.py → x.py
        if {top + n for n in new_paths} & prev_paths:
            return {"top_folder": top, "zip_has_it": False}
    tops = {n.split("/", 1)[0] + "/" for n in new_paths if "/" in n}
    for top in tops:                                   # the zip added a top folder: x.py → demo/x.py
        stripped = {n[len(top):] for n in new_paths if n.startswith(top)}
        if stripped & prev_paths:
            return {"top_folder": top, "zip_has_it": True}
    return None


def check_deletions(prev_entries, uploaded_paths):
    """For a FULL upload: None when it is safe, else what it would delete.

    It is not safe when it would delete at least MASS_DELETION_MIN_FILES files and at least half
    of the previous version. The caller refuses such an upload unless it is confirmed.
    """
    prev_paths = [_path(e) for e in dedupe_by_path(prev_entries)]
    if not prev_paths:
        return None                                    # first version: nothing to delete
    new_paths = {str(p).replace("\\", "/") for p in uploaded_paths or () if p}
    would_delete = sorted(p for p in prev_paths if p not in new_paths)
    if len(would_delete) < MASS_DELETION_MIN_FILES or len(would_delete) * 2 < len(prev_paths):
        return None
    return {
        "would_delete": would_delete,
        "deleted_count": len(would_delete),
        "previous_count": len(prev_paths),
        "top_folder": _top_folder_hint(prev_paths, new_paths),
    }


# ── loose files sent by name only (the UI keeps no folders) ─────────────────

def match_bare_names(prev_entries, bare):
    """Put files that arrived with their name only back at the path they had.

    bare : {guessed_path: file_name} for files that came without a folder.
    → (mapping, ambiguous)
      mapping   : {guessed_path: real_path} for each name that matches exactly one previous path
      ambiguous : {file_name: [paths]} for names that match more than one previous path
    A guessed path that already exists, or a name no previous path has, stays as it is (new file).
    """
    prev_paths = [_path(e) for e in dedupe_by_path(prev_entries)]
    prev_set = set(prev_paths)
    mapping, ambiguous = {}, {}
    for guessed, name in (bare or {}).items():
        if guessed in prev_set:
            continue
        candidates = sorted(p for p in prev_paths if p.rsplit("/", 1)[-1] == name)
        if len(candidates) == 1:
            mapping[guessed] = candidates[0]
        elif len(candidates) > 1:
            ambiguous[name] = candidates
    return mapping, ambiguous
