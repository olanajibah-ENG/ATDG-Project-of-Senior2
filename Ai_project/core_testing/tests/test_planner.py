from core_testing import planner
from core_testing.graphify import loader, merge, resolver
from core_testing.tests.conftest import analysis_for

ALL = ["unit", "edge", "integration"]


def _ready(files):
    return [(path, analysis_for(name)) for path, name in files.items()]


def _graph(ready):
    fgs = [loader.load_file(p, a) for p, a in ready]
    return resolver.resolve_calls(merge.merge(fgs), fgs)


def test_game_plan_counts():
    plan, no_units = planner.build_plan(_ready({"game.py": "game.py"}), [], ALL)
    assert len(plan["units"]) == 14
    assert plan["skipped"] == []
    assert plan["work_items_count"] == 42
    assert no_units == []


def test_work_items_follow_requested_levels():
    plan, _ = planner.build_plan(_ready({"game.py": "game.py"}), [], ["unit"])
    assert plan["work_items_count"] == 14
    plan, _ = planner.build_plan(_ready({"game.py": "game.py"}), [], ["unit", "edge"])
    assert plan["work_items_count"] == 28


def test_every_function_appears_exactly_once():
    plan, _ = planner.build_plan(_ready({"edge_cases.py": "edge_cases.py"}), [], ALL)
    planned = [u["id"] for u in plan["units"]]
    skipped = [s["unit"] for s in plan["skipped"]]
    assert len(planned) == len(set(planned))
    assert len(skipped) == len(set(skipped))
    assert set(planned).isdisjoint(skipped)
    assert len(planned) + len(skipped) == 11


def test_skip_shapes_for_files_and_units():
    plan, no_units = planner.build_plan(
        _ready({"edge_cases.py": "edge_cases.py", "no_units.py": "no_units.py"}),
        [{"path": "app.js", "reason": "unsupported_language"}],
        ALL,
    )
    assert {"path": "app.js", "reason": "unsupported_language"} in plan["skipped"]
    assert {"path": "no_units.py", "reason": "no_units"} in plan["skipped"]
    assert {"path": "edge_cases.py", "unit": "edge_cases.py::_helper", "reason": "private"} in plan["skipped"]
    assert no_units == ["no_units.py"]


def test_a_skip_never_removes_other_files_units():
    plan, _ = planner.build_plan(
        _ready({"game.py": "game.py", "no_units.py": "no_units.py"}),
        [{"path": "broken.py", "reason": "analysis_failed"}],
        ALL,
    )
    assert len(plan["units"]) == 14


def test_units_are_in_a_stable_order():
    ready = _ready({"b/game.py": "game.py", "a/game.py": "game.py"})
    first, _ = planner.build_plan(ready, [], ALL)
    second, _ = planner.build_plan(list(reversed(ready)), [], ALL)
    assert [u["id"] for u in first["units"]] == [u["id"] for u in second["units"]]
    assert first["units"][0]["id"] == "a/game.py::Person.__init__"
    assert first["units"][14]["id"] == "b/game.py::Person.__init__"


def test_units_carry_their_callees_when_a_graph_is_given():
    ready = _ready({"game.py": "game.py"})
    plan, _ = planner.build_plan(ready, [], ALL, _graph(ready))
    by_id = {u["id"]: u for u in plan["units"]}
    assert by_id["game.py::Student.enroll"]["callees"] == ["game.py::Course.add_student"]
    assert by_id["game.py::Course.add_student"]["callees"] == []
    assert "line" not in by_id["game.py::Student.enroll"]


def test_units_carry_their_externals_without_builtins():
    ready = _ready({"game.py": "game.py"})
    plan, _ = planner.build_plan(ready, [], ALL, _graph(ready))
    by_id = {u["id"]: u for u in plan["units"]}
    # enroll calls len() and print(): builtins are not externals
    assert by_id["game.py::Student.enroll"]["externals"] == []
    assert all("print" not in u["externals"] and "len" not in u["externals"] for u in plan["units"])


def test_real_externals_are_listed():
    from core_testing.graphify import queries

    graph = {"nodes": [], "edges": [
        {"from": "a.py::f", "to": "ext.os.getcwd", "relation": "calls", "confidence": "INFERRED"},
        {"from": "a.py::f", "to": "ext.print", "relation": "calls", "confidence": "INFERRED"},
        {"from": "a.py::f", "to": "ext.os.getcwd", "relation": "calls", "confidence": "INFERRED"},
        {"from": "a.py::f", "to": "ext.typing", "relation": "imports", "confidence": "EXTRACTED"},
        {"from": "a.py::g", "to": "ext.requests.get", "relation": "calls", "confidence": "INFERRED"},
    ]}
    assert queries.externals(graph, "a.py::f") == ["os.getcwd"]
    assert queries.externals(graph, "a.py::g") == ["requests.get"]
