import copy

from core_ai.services.test_generation.graphify import loader, merge
from core_ai.tests.test_generation.conftest import analysis_for


def _merged(files):
    file_graphs = [loader.load_file(path, analysis_for(name)) for path, name in files.items()]
    return merge.merge(file_graphs), file_graphs


def _ids(graph, node_type=None):
    return {n["id"] for n in graph["nodes"] if node_type is None or n.get("type") == node_type}


def test_local_ids_are_file_qualified():
    graph, _ = _merged({"pkg/game.py": "game.py"})
    assert "pkg/game.py::Student" in _ids(graph, "class")
    assert "pkg/game.py::Student.enroll" in _ids(graph, "method")
    assert "pkg/game.py::__module__" in _ids(graph, "module")


def test_top_level_function_id():
    graph, _ = _merged({"shop/models.py": "shop/models.py"})
    assert "shop/models.py::format_price" in _ids(graph, "function")


def test_external_ids_are_shared_not_qualified():
    graph, _ = _merged({"a/game.py": "game.py", "b/game.py": "game.py"})
    externals = [n for n in graph["nodes"] if n.get("type") == "external"]
    assert all(n["id"].startswith("ext.") for n in externals)
    assert len([n for n in externals if n["id"] == "ext.typing"]) == 1


def test_same_class_name_in_two_files_gives_two_nodes():
    graph, _ = _merged({"a/game.py": "game.py", "b/game.py": "game.py"})
    students = sorted(i for i in _ids(graph, "class") if i.endswith("::Student"))
    assert students == ["a/game.py::Student", "b/game.py::Student"]
    assert len(_ids(graph, "module")) == 2


def test_unified_shape_is_kept():
    graph, _ = _merged({"game.py": "game.py"})
    assert set(graph) == {"nodes", "edges", "meta"}
    for edge in graph["edges"]:
        assert {"from", "to", "relation", "confidence"} <= set(edge)
        assert edge["relation"] in ("imports", "inherits", "calls")
    assert graph["meta"]["total_nodes"] == len(graph["nodes"])
    assert graph["meta"]["total_edges"] == len(graph["edges"])
    assert graph["meta"]["source"] == "merged"
    assert graph["meta"]["files"] == ["game.py"]


def test_inheritance_edges_are_qualified():
    graph, _ = _merged({"game.py": "game.py"})
    inherits = {(e["from"], e["to"]) for e in graph["edges"] if e["relation"] == "inherits"}
    assert ("game.py::Student", "game.py::Person") in inherits
    assert ("game.py::Professor", "game.py::Person") in inherits


def test_method_nodes_point_at_their_qualified_parent():
    graph, _ = _merged({"game.py": "game.py"})
    node = next(n for n in graph["nodes"] if n["id"] == "game.py::Student.enroll")
    assert node["parent"] == "game.py::Student"
    assert node["file"] == "game.py"


def test_stored_graph_is_not_mutated():
    analysis = analysis_for("game.py")
    before = copy.deepcopy(analysis["dependency_graph"])
    merge.merge([loader.load_file("pkg/game.py", analysis)])
    assert analysis["dependency_graph"] == before


def test_loader_reads_imports_and_class_table():
    fg = loader.load_file("shop/service.py", analysis_for("shop/service.py"))
    imported = {(i["module"], i["name"], i["level"]) for i in fg["imports"]}
    assert ("models", "Cart", 1) in imported
    assert ("models", "format_price", 1) in imported
    assert set(fg["classes"]) == {"Checkout"}
    assert set(fg["functions"]) == {"new_cart"}
