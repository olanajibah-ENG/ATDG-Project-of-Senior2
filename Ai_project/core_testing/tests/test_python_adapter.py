from core_testing.languages.python_adapter import is_python, list_units
from core_testing.tests.conftest import analysis_for


def _by_name(items, key="id"):
    return {item[key].split("::")[-1]: item for item in items}


def test_game_has_14_method_units_and_no_skips():
    units, skips = list_units("game.py", analysis_for("game.py"))
    assert len(units) == 14
    assert skips == []
    assert {u["kind"] for u in units} == {"method"}
    assert all(u["file"] == "game.py" and u["body_hash"] for u in units)


def test_constructors_are_units():
    units, _ = list_units("game.py", analysis_for("game.py"))
    inits = [u["id"] for u in units if u["id"].endswith(".__init__")]
    assert len(inits) == 6
    assert "game.py::Student.__init__" in inits


def test_unit_ids_use_path_class_method():
    units, _ = list_units("pkg/game.py", analysis_for("game.py"))
    assert "pkg/game.py::Student.enroll" in {u["id"] for u in units}


def test_units_follow_source_order():
    units, _ = list_units("game.py", analysis_for("game.py"))
    names = [u["id"].split("::")[1] for u in units]
    assert names[0] == "Person.__init__"
    assert names.index("Student.enroll") < names.index("Student.drop_course") < names.index("Course.add_student")


def test_edge_cases_units_and_skip_reasons():
    units, skips = list_units("edge_cases.py", analysis_for("edge_cases.py"))
    planned = _by_name(units)
    skipped = {s["unit"].split("::")[-1]: s["reason"] for s in skips}

    # top-level functions have kind "function"
    assert planned["double"]["kind"] == "function"
    # dunder methods are units
    assert planned["Shape.__str__"]["kind"] == "method"
    assert {"Shape.describe", "Base.validate", "Child.save"} <= set(planned)

    assert skipped["_helper"] == "private"
    assert skipped["Shape._internal"] == "private"
    assert skipped["Shape.area"] == "empty_or_abstract"       # abstract
    assert skipped["not_done_yet"] == "empty_or_abstract"     # pass
    assert skipped["only_documented"] == "empty_or_abstract"  # docstring only
    assert skipped["ellipsis_body"] == "empty_or_abstract"    # ...

    # every function and method appears exactly once
    assert set(planned).isdisjoint(skipped)
    assert len(planned) + len(skipped) == 11


def test_truncated_body_is_skipped():
    analysis = analysis_for("game.py")
    analysis["class_diagram_data"]["classes"][0]["methods"][0]["body_truncated"] = True
    units, skips = list_units("game.py", analysis)
    assert len(units) == 13
    assert skips == [{"path": "game.py", "unit": "game.py::Person.__init__", "reason": "body_truncated"}]


def test_file_without_functions_is_no_units():
    units, skips = list_units("no_units.py", analysis_for("no_units.py"))
    assert units == []
    assert skips == [{"path": "no_units.py", "reason": "no_units"}]


def test_class_diagram_data_stored_as_json_string_is_read():
    import json

    analysis = analysis_for("game.py")
    analysis["class_diagram_data"] = json.dumps(analysis["class_diagram_data"])
    units, _ = list_units("game.py", analysis)
    assert len(units) == 14


def test_is_python():
    assert is_python("python")
    assert is_python("Python", "x")
    assert not is_python("javascript", "app.js")
    assert not is_python("java", "Main.py")       # the stored language wins
    assert is_python("unknown", "tool.py")
    assert not is_python(None, "notes")
