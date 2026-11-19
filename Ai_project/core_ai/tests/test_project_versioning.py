"""How a new project version is built (core_ai/services/project_versioning.py).

The demo project has three files; version 2 changes course.py only. Before the fix, version 2
listed course.py twice (the old file carried over next to the modified one)."""
import pytest

from core_ai.services import project_versioning as pv


def f(file_id, path, version=1, file_type="python"):
    return {"file_id": file_id, "filepath": path, "filename": path.rsplit("/", 1)[-1],
            "file_type": file_type, "version_number": version}


V1 = [f("s1", "demo/student.py"), f("c1", "demo/course.py"), f("m1", "demo/main.py")]


def statuses(result):
    return {e["filepath"]: e["status"] for e in result["file_changes"]}


# ── mode ─────────────────────────────────────────────────────────────────────

def test_mode_comes_from_the_upload_shape_unless_given():
    assert pv.infer_mode(None, has_zip=True) == "full"
    assert pv.infer_mode(None, has_zip=False) == "partial"
    assert pv.infer_mode("partial", has_zip=True) == "partial"
    assert pv.infer_mode("full", has_zip=False) == "full"
    assert pv.infer_mode("nonsense", has_zip=True) == "full"


def test_unknown_mode_is_refused():
    with pytest.raises(ValueError):
        pv.build_version(V1, [], "sometimes")


# ── the bug that was found ───────────────────────────────────────────────────

def test_modified_file_replaces_the_old_one_at_its_path():
    uploaded = [f("s1", "demo/student.py"), f("c2", "demo/course.py", 2), f("m1", "demo/main.py")]
    result = pv.build_version(V1, uploaded, "full")
    assert sorted(result["file_ids"]) == ["c2", "m1", "s1"]                  # 3, not 4
    assert statuses(result) == {"demo/student.py": "unchanged", "demo/course.py": "modified",
                                "demo/main.py": "unchanged"}
    assert result["counts"] == {"total_files": 3, "new_files": 0, "modified_files": 1,
                                "unchanged_files": 2, "deleted_files": 0}


def test_each_path_appears_once_whatever_the_mode():
    for mode in ("full", "partial"):
        result = pv.build_version(V1, [f("c2", "demo/course.py", 2)], mode)
        paths = [e["filepath"] for e in result["file_changes"] if e["status"] != "deleted"]
        assert len(paths) == len(set(paths))


def test_first_version():
    result = pv.build_version([], V1, "full")
    assert set(statuses(result).values()) == {"new"} and len(result["file_ids"]) == 3


# ── full upload (ZIP) ────────────────────────────────────────────────────────

def test_full_upload_deletes_what_was_not_uploaded():
    result = pv.build_version(V1, [f("s1", "demo/student.py"), f("c1", "demo/course.py")], "full")
    assert sorted(result["file_ids"]) == ["c1", "s1"]
    assert statuses(result)["demo/main.py"] == "deleted"
    assert result["counts"]["deleted_files"] == 1 and result["counts"]["total_files"] == 2
    assert result["file_changes"][-1]["filepath"] == "demo/main.py"          # deleted ones last


def test_full_upload_adds_new_files():
    result = pv.build_version(V1, V1 + [f("u1", "demo/utils.py", 2)], "full")
    assert statuses(result)["demo/utils.py"] == "new" and result["counts"]["new_files"] == 1


# ── partial upload (loose files, GitHub) ─────────────────────────────────────

def test_partial_upload_keeps_what_was_not_uploaded():
    result = pv.build_version(V1, [f("c2", "demo/course.py", 2)], "partial")
    assert sorted(result["file_ids"]) == ["c2", "m1", "s1"]
    assert statuses(result) == {"demo/student.py": "unchanged", "demo/course.py": "modified",
                                "demo/main.py": "unchanged"}


def test_partial_upload_deletes_only_the_listed_paths():
    result = pv.build_version(V1, [], "partial", deleted_paths=["demo/main.py", "not/there.py"])
    assert sorted(result["file_ids"]) == ["c1", "s1"]
    assert statuses(result)["demo/main.py"] == "deleted"
    assert "not/there.py" not in statuses(result)                           # nothing to delete


def test_rename_is_a_delete_plus_a_new_file():
    result = pv.build_version(V1, [f("e2", "demo/enrolment.py", 2)], "partial",
                              deleted_paths=["demo/student.py"])
    assert statuses(result)["demo/student.py"] == "deleted"
    assert statuses(result)["demo/enrolment.py"] == "new"


def test_uploading_a_path_that_is_also_listed_as_deleted_keeps_the_upload():
    result = pv.build_version(V1, [f("m2", "demo/main.py", 2)], "partial", deleted_paths=["demo/main.py"])
    assert statuses(result)["demo/main.py"] == "modified" and "m2" in result["file_ids"]


# ── content reused at the same path ──────────────────────────────────────────

def test_reverting_a_file_to_older_content_is_modified_not_unchanged():
    v2 = [f("s1", "demo/student.py"), f("c2", "demo/course.py", 2), f("m1", "demo/main.py")]
    reverted = [f("s1", "demo/student.py"), f("c1", "demo/course.py", 1), f("m1", "demo/main.py")]
    result = pv.build_version(v2, reverted, "full")
    assert statuses(result)["demo/course.py"] == "modified"
    assert sorted(result["file_ids"]) == ["c1", "m1", "s1"]


def test_two_paths_with_the_same_content_stay_two_files():
    prev = [f("i1", "pkg_a/__init__.py"), f("i2", "pkg_b/__init__.py")]
    result = pv.build_version(prev, prev, "full")
    assert sorted(e["filepath"] for e in result["file_changes"]) == ["pkg_a/__init__.py", "pkg_b/__init__.py"]


# ── old versions saved with a duplicate path ─────────────────────────────────

BROKEN_V2 = [f("s1", "demo/student.py"), f("c2", "demo/course.py", 2), f("m1", "demo/main.py"),
             f("c1", "demo/course.py", 1)]


def test_dedupe_keeps_the_newest_file_of_each_path():
    kept = pv.dedupe_by_path(BROKEN_V2)
    assert [(e["filepath"], e["file_id"]) for e in kept] == [
        ("demo/student.py", "s1"), ("demo/course.py", "c2"), ("demo/main.py", "m1")]


def test_a_version_built_on_a_broken_one_is_clean():
    result = pv.build_version(BROKEN_V2, [f("m3", "demo/main.py", 3)], "partial")
    assert sorted(result["file_ids"]) == ["c2", "m3", "s1"]


def test_visible_files_hides_deleted_and_duplicates():
    doc = {"file_changes": [dict(e, status="unchanged") for e in BROKEN_V2]
           + [dict(f("x1", "demo/old.py"), status="deleted")]}
    assert [e["file_id"] for e in pv.visible_files(doc)] == ["s1", "c2", "m1"]
    assert pv.visible_files({"file_ids": ["a"]}) is None              # older document: caller resolves


# ── check_deletions ──────────────────────────────────────────────────────────

PREV = [f("1", "demo/a.py"), f("2", "demo/b.py"), f("3", "demo/c.py"), f("4", "demo/d.py")]


def test_check_deletions_is_quiet_below_half():
    assert pv.check_deletions(PREV, ["demo/a.py", "demo/b.py", "demo/c.py"]) is None       # 1 of 4


def test_check_deletions_flags_half_or_more():
    risk = pv.check_deletions(PREV, ["demo/a.py", "demo/b.py"])                             # 2 of 4
    assert risk["would_delete"] == ["demo/c.py", "demo/d.py"]
    assert risk["deleted_count"] == 2 and risk["previous_count"] == 4
    assert risk["top_folder"] is None


def test_check_deletions_needs_at_least_two_files():
    assert pv.check_deletions([f("1", "a.py"), f("2", "b.py")], ["a.py"]) is None          # 1 of 2


def test_check_deletions_first_version():
    assert pv.check_deletions([], ["a.py"]) is None


def test_check_deletions_sees_a_missing_or_extra_top_folder():
    lost = pv.check_deletions(PREV, ["a.py", "b.py", "c.py", "d.py"])
    assert lost["top_folder"] == {"top_folder": "demo/", "zip_has_it": False}
    extra = pv.check_deletions([f("1", "a.py"), f("2", "b.py")], ["src/a.py", "src/b.py"])
    assert extra["top_folder"] == {"top_folder": "src/", "zip_has_it": True}


# ── match_bare_names ─────────────────────────────────────────────────────────

def test_bare_name_matching_one_path():
    mapping, ambiguous = pv.match_bare_names([f("1", "demo/course.py"), f("2", "demo/main.py")],
                                             {"demo3/course.py": "course.py"})
    assert mapping == {"demo3/course.py": "demo/course.py"} and ambiguous == {}


def test_bare_name_matching_two_paths_is_ambiguous():
    mapping, ambiguous = pv.match_bare_names([f("1", "a/user.py"), f("2", "b/user.py")], {"p/user.py": "user.py"})
    assert mapping == {} and ambiguous == {"user.py": ["a/user.py", "b/user.py"]}


def test_bare_name_that_is_new_or_already_a_path_is_left_alone():
    prev = [f("1", "demo3/course.py"), f("2", "demo/main.py")]
    mapping, ambiguous = pv.match_bare_names(prev, {"demo3/course.py": "course.py", "demo3/new.py": "new.py"})
    assert mapping == {} and ambiguous == {}
