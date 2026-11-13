from core_testing.graphify import loader, merge, queries, resolver
from core_testing.tests.conftest import analysis_for


def _graph(files):
    file_graphs = [loader.load_file(path, analysis_for(name)) for path, name in files.items()]
    return resolver.resolve_calls(merge.merge(file_graphs), file_graphs)


def _calls(graph):
    return {(e["from"], e["to"]) for e in graph["edges"] if e["relation"] == "calls"}


GAME = {"game.py": "game.py"}
SHOP = {"shop/models.py": "shop/models.py", "shop/service.py": "shop/service.py"}


def test_call_through_a_typed_parameter_reaches_the_local_method():
    calls = _calls(_graph(GAME))
    assert ("game.py::Student.enroll", "game.py::Course.add_student") in calls
    assert ("game.py::Student.drop_course", "game.py::Course.remove_student") in calls


def test_super_call_reaches_the_parent_constructor():
    calls = _calls(_graph(GAME))
    assert ("game.py::Professor.__init__", "game.py::Person.__init__") in calls
    assert ("game.py::Student.__init__", "game.py::Person.__init__") in calls


def test_instantiation_reaches_the_constructor():
    calls = _calls(_graph(GAME))
    assert ("game.py::University.create_department", "game.py::Department.__init__") in calls


def test_no_local_call_is_left_as_external():
    graph = _graph(GAME)
    targets = {to for _, to in _calls(graph)}
    assert "ext.course.add_student" not in targets
    assert "ext.course.remove_student" not in targets
    assert "ext.super" not in targets
    node_ids = {n["id"] for n in graph["nodes"]}
    assert "ext.course.add_student" not in node_ids and "ext.super" not in node_ids


def test_every_edge_end_is_a_node():
    for files in (GAME, SHOP, {"edge_cases.py": "edge_cases.py"}):
        graph = _graph(files)
        node_ids = {n["id"] for n in graph["nodes"]}
        for edge in graph["edges"]:
            assert edge["from"] in node_ids and edge["to"] in node_ids, edge


def test_self_call_to_an_inherited_method_reaches_the_parent():
    calls = _calls(_graph({"edge_cases.py": "edge_cases.py"}))
    assert ("edge_cases.py::Child.save", "edge_cases.py::Base.validate") in calls


def test_self_call_inside_the_same_class():
    calls = _calls(_graph({"edge_cases.py": "edge_cases.py"}))
    assert ("edge_cases.py::Shape.describe", "edge_cases.py::Shape.area") in calls
    assert ("edge_cases.py::Shape.__str__", "edge_cases.py::Shape.describe") in calls


def test_call_to_a_local_function():
    calls = _calls(_graph({"edge_cases.py": "edge_cases.py"}))
    assert ("edge_cases.py::double", "edge_cases.py::_helper") in calls


def test_cross_file_calls_through_imports():
    calls = _calls(_graph(SHOP))
    assert ("shop/service.py::Checkout.add_product", "shop/models.py::Cart.add") in calls
    assert ("shop/service.py::Checkout.receipt", "shop/models.py::Cart.total") in calls
    assert ("shop/service.py::Checkout.receipt", "shop/models.py::format_price") in calls
    assert ("shop/service.py::new_cart", "shop/models.py::Cart.__init__") in calls


def test_callees_lists_direct_local_units_only():
    graph = _graph(GAME)
    assert queries.callees(graph, "game.py::Student.enroll") == ["game.py::Course.add_student"]
    assert queries.callees(graph, "game.py::Course.add_student") == []
    assert queries.callees(graph, "game.py::does.not.exist") == []


def test_callees_across_files():
    graph = _graph(SHOP)
    assert set(queries.callees(graph, "shop/service.py::Checkout.receipt")) == {
        "shop/models.py::Cart.total", "shop/models.py::format_price"}


def test_shape_and_counters_after_resolution():
    graph = _graph(GAME)
    assert set(graph) == {"nodes", "edges", "meta"}
    assert graph["meta"]["total_edges"] == len(graph["edges"])
    assert graph["meta"]["total_nodes"] == len(graph["nodes"])
    for edge in graph["edges"]:
        assert {"from", "to", "relation", "confidence"} <= set(edge)
    keys = [(e["from"], e["to"], e["relation"]) for e in graph["edges"]]
    assert len(keys) == len(set(keys))        # no duplicate edges


def test_unparseable_or_truncated_body_keeps_stored_edges():
    analysis = analysis_for("game.py")
    for cls in analysis["class_diagram_data"]["classes"]:
        for method in cls["methods"]:
            if cls["name"] == "Student" and method["name"] == "enroll":
                method["body_truncated"] = True
    fg = loader.load_file("game.py", analysis)
    graph = resolver.resolve_calls(merge.merge([fg]), [fg])
    calls = _calls(graph)
    assert ("game.py::Student.enroll", "game.py::Course.add_student") not in calls
    assert ("game.py::Student.enroll", "ext.course.add_student") in calls   # stored edge untouched
    assert ("game.py::Student.drop_course", "game.py::Course.remove_student") in calls
