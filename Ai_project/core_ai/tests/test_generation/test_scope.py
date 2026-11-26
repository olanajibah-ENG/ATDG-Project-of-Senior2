import pytest

from core_ai.services.test_generation import scope
from core_ai.services.test_generation.errors import ApiError
from core_ai.tests.test_generation.conftest import PROJECT_ID


def _resolve(reader, **data):
    data.setdefault("project_id", PROJECT_ID)
    return scope.resolve(data, reader)


def test_omitted_version_uses_the_latest(reader, make_project):
    make_project({"a.py": "game.py"}, version=1)
    make_project({"a.py": "game.py", "b.py": "no_units.py"}, version=2)
    result = _resolve(reader)
    assert result.version_number == 2
    assert [f["path"] for f in result.files] == ["a.py", "b.py"]


def test_explicit_version(reader, make_project):
    make_project({"a.py": "game.py"}, version=1)
    make_project({"a.py": "game.py", "b.py": "no_units.py"}, version=2)
    assert [f["path"] for f in _resolve(reader, version_number=1).files] == ["a.py"]


def test_unknown_version_is_400(reader, make_project):
    make_project({"a.py": "game.py"})
    with pytest.raises(ApiError) as info:
        _resolve(reader, version_number=999)
    assert (info.value.http_status, info.value.code) == (400, "validation_error")
    assert info.value.details["latest_version"] == 1


def test_project_without_version_is_400(reader):
    with pytest.raises(ApiError) as info:
        _resolve(reader)
    assert info.value.http_status == 400


def test_empty_paths_selects_everything(reader, make_project):
    make_project({"a.py": "game.py", "b.py": "no_units.py"})
    assert len(_resolve(reader, paths=[]).files) == 2
    assert len(_resolve(reader, paths=None).files) == 2


def test_paths_restrict_the_selection(reader, make_project):
    make_project({"a.py": "game.py", "b.py": "no_units.py"})
    result = _resolve(reader, paths=["b.py"])
    assert [f["path"] for f in result.files] == ["b.py"]
    assert result.paths == ["b.py"]


def test_unknown_path_is_400_and_listed(reader, make_project):
    make_project({"a.py": "game.py"})
    with pytest.raises(ApiError) as info:
        _resolve(reader, paths=["a.py", "nope.py"])
    assert info.value.http_status == 400
    assert info.value.details["paths"] == ["nope.py"]


def test_levels_default_to_all_three(reader, make_project):
    make_project({"a.py": "game.py"})
    assert _resolve(reader).levels == ["unit", "edge", "integration"]
    assert _resolve(reader, levels=["edge"]).levels == ["edge"]


def test_no_python_file_is_422(reader, make_project):
    make_project({"app.js": None, "util.js": None})
    with pytest.raises(ApiError) as info:
        _resolve(reader)
    assert (info.value.http_status, info.value.code) == (422, "no_python_files")


def test_selection_of_only_non_python_paths_is_422(reader, make_project):
    make_project({"a.py": "game.py", "app.js": None})
    with pytest.raises(ApiError) as info:
        _resolve(reader, paths=["app.js"])
    assert info.value.http_status == 422


def test_mixed_selection_keeps_non_python_files(reader, make_project):
    make_project({"a.py": "game.py", "app.js": None})
    result = _resolve(reader)
    assert {f["path"]: f["file_type"] for f in result.files} == {"a.py": "python", "app.js": "javascript"}
