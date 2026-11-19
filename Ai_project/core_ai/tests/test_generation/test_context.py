import ast
import json

from core_ai.services.test_generation import assembler, context
from core_ai.services.test_generation.languages.base import PythonAdapter, adapter_for
from core_ai.services.test_generation.prompts import unit as unit_prompt
from core_ai.services.test_generation.strategies.unit import UnitStrategy
from core_ai.tests.test_generation.conftest import analysis_for

ADAPTER = PythonAdapter()


def _unit(unit_id, callees=(), externals=(), kind="method"):
    return {"id": unit_id, "file": unit_id.split("::")[0], "kind": kind,
            "callees": list(callees), "externals": list(externals)}


def _game_context(name="Student.enroll", callees=("game.py::Course.add_student",)):
    return context.build_unit_context(_unit(f"game.py::{name}", callees), {"game.py": analysis_for("game.py")}, ADAPTER)


# ── context ──────────────────────────────────────────────────────────────────

def test_unit_part_of_the_context():
    unit = _game_context()["unit"]
    assert unit["id"] == "game.py::Student.enroll"
    assert unit["import_statement"] == "from game import Student"
    assert unit["signature"].startswith("enroll(")
    assert unit["return_type"] == "bool"
    assert {"name": "course", "type": "Course", "default_code": None} in unit["parameters"]
    assert "self.courses.append(course)" in unit["body"]


def test_class_part_of_the_context():
    cls = _game_context()["class"]
    assert cls["name"] == "Student" and cls["bases"] == ["Person"]
    assert cls["constructor"].startswith("__init__(") and "major" in cls["constructor"]
    assert not cls["constructor"].startswith("+")


def test_callee_is_listed_by_signature_only():
    ctx = _game_context()
    assert ctx["callees"] == [{"id": "game.py::Course.add_student",
                               "signature": ctx["callees"][0]["signature"],
                               "import_statement": "from game import Course"}]
    assert ctx["callees"][0]["signature"].startswith("add_student(")
    text = json.dumps(ctx)
    assert "self.students.append(student)" not in text          # the callee's body
    assert "self.professors" not in text                        # any other unit's body


def test_function_outside_a_class_has_no_class_part():
    ctx = context.build_unit_context(_unit("shop/models.py::format_price", kind="function"),
                                     {"shop/models.py": analysis_for("shop/models.py")}, ADAPTER)
    assert ctx["class"] is None
    assert ctx["unit"]["import_statement"] == "from shop.models import format_price"


def test_callee_from_another_file_gets_that_files_import():
    analyses = {"shop/service.py": analysis_for("shop/service.py"), "shop/models.py": analysis_for("shop/models.py")}
    ctx = context.build_unit_context(
        _unit("shop/service.py::Checkout.receipt", ["shop/models.py::Cart.total", "shop/models.py::format_price"]),
        analyses, ADAPTER)
    imports = {c["id"]: c["import_statement"] for c in ctx["callees"]}
    assert imports == {"shop/models.py::Cart.total": "from shop.models import Cart",
                       "shop/models.py::format_price": "from shop.models import format_price"}
    assert "sum(p.price" not in json.dumps(ctx)                 # Cart.total's body


def test_rules_and_externals():
    ctx = context.build_unit_context(_unit("game.py::Student.enroll", externals=["os.getcwd"]),
                                     {"game.py": analysis_for("game.py")}, ADAPTER)
    assert ctx["externals"] == ["os.getcwd"]
    assert ctx["rules"] == {"framework": "pytest", "test_name": "test_Student_enroll__unit_<n>"}


def test_unknown_unit_or_missing_analysis_gives_no_context():
    assert context.build_unit_context(_unit("game.py::Nope.x"), {"game.py": analysis_for("game.py")}, ADAPTER) is None
    assert context.build_unit_context(_unit("game.py::Student.enroll"), {}, ADAPTER) is None


def test_hash_is_stable_and_follows_the_body_and_the_prompt_version():
    first, second = _game_context(), _game_context()
    assert context.context_hash(first, "unit-v1") == context.context_hash(second, "unit-v1")
    assert context.context_hash(first, "unit-v1") != context.context_hash(first, "unit-v2")
    second["unit"]["body"] += "\npass"
    assert context.context_hash(first, "unit-v1") != context.context_hash(second, "unit-v1")


# ── adapter ──────────────────────────────────────────────────────────────────

def test_adapter_registry_and_import_rules():
    assert isinstance(adapter_for("python", "a.py"), PythonAdapter)
    assert adapter_for("javascript", "a.js") is None
    assert ADAPTER.import_statement("pkg/sub/mod.py", "Thing") == "from pkg.sub.mod import Thing"
    assert ADAPTER.import_statement("game", "Student") == "from game import Student"     # no extension
    assert ADAPTER.allowed_import_roots(["game.py", "shop/models.py", "shop/service.py"]) == {"game", "shop"}


# ── strategy and prompt ──────────────────────────────────────────────────────

def test_prompt_holds_the_context_and_the_rules_and_nothing_else_from_the_project():
    strategy = UnitStrategy()
    analysis = analysis_for("game.py")
    for cls in analysis["class_diagram_data"]["classes"]:       # a marker in ANOTHER unit's body
        for method in cls["methods"]:
            if (cls["name"], method["name"]) == ("Department", "hire_professor"):
                method["body"] = "SECRET_MARKER = 1"
    ctx = strategy.build_context(_unit("game.py::Student.enroll", ["game.py::Course.add_student"]),
                                 {"game.py": analysis}, ADAPTER)
    system, user = strategy.build_prompt(ctx, ADAPTER)

    assert "```python" in system and "one Python file" in system
    assert json.dumps(ctx, indent=2, ensure_ascii=False) in user
    assert "test_Student_enroll__unit_<n>" in user
    assert "tmp_path" in user and "network" in user
    assert "SECRET_MARKER" not in user and "SECRET_MARKER" not in system


def test_prompt_version_and_request_hash():
    strategy = UnitStrategy()
    assert strategy.prompt_version == unit_prompt.PROMPT_VERSION == "unit-v2"
    assert strategy.level == "unit"
    ctx = _game_context()
    assert strategy.request_hash(ctx) == context.context_hash(ctx, "unit-v2")


# ── assembler ────────────────────────────────────────────────────────────────

def test_test_path_rule():
    assert assembler.test_path("game.py::Student.enroll") == "tests/generated/test_game_Student_enroll__unit.py"
    assert assembler.test_path("pkg/util.py::slugify") == "tests/generated/test_pkg_util_slugify__unit.py"


def test_assembled_file_has_a_header_and_still_parses():
    text = assembler.assemble("import pytest\n\n\ndef test_a():\n    assert True\n",
                              unit_id="game.py::Student.enroll", body_hash="abc123", job_id="job_1")
    assert text.startswith("# Generated by")
    assert "game.py::Student.enroll" in text and "abc123" in text and "NOT RUN YET" in text
    ast.parse(text)
    assert text.endswith("assert True\n")


# ── default values reach the model as Python code (the "2" vs 2 bug, 19/11/2026) ──

from core_ai.tests.test_generation import helpers  # noqa: E402

COURSE_SRC = '''
class Course:
    def __init__(self, title: str, capacity: int = 2, tag="new", *names, limit=None, **extra):
        self.title = title
        self.capacity = capacity

    @staticmethod
    def make(title: str = "x") -> "Course":
        return Course(title)

    @classmethod
    def empty(cls, n: int = 0):
        return cls("e", n)

    async def load(self, src: str = "db") -> bool:
        return True

def pair(a, b=1, /, c=2):
    return a + b + c
'''


def _course_ctx(name, kind="method"):
    return context.build_unit_context(_unit(f"demo/course.py::{name}", kind=kind),
                                      {"demo/course.py": helpers.build_analysis(COURSE_SRC)}, ADAPTER)


def test_signature_carries_default_values_as_code():
    unit = _course_ctx("Course.__init__")["unit"]
    assert unit["signature"] == "__init__(self, title: str, capacity: int = 2, tag='new', *names, limit=None, **extra)"


def test_default_code_is_python_source_not_a_plain_string():
    params = {p["name"]: p for p in _course_ctx("Course.__init__")["unit"]["parameters"]}
    assert params["capacity"]["default_code"] == "2"            # the integer 2, written as code
    assert params["tag"]["default_code"] == "'new'"             # a string keeps its quotes
    assert params["title"]["default_code"] is None
    assert "default" not in params["capacity"]


def test_class_constructor_signature_has_the_defaults():
    ctx = _course_ctx("Course.make")
    assert "capacity: int = 2" in ctx["class"]["constructor"]


def test_static_class_and_async_methods():
    assert _course_ctx("Course.make")["unit"]["signature"] == "make(title: str = 'x') -> Course"
    assert _course_ctx("Course.empty")["unit"]["signature"] == "empty(cls, n: int = 0)"
    assert _course_ctx("Course.load")["unit"]["signature"] == "async load(self, src: str = 'db') -> bool"


def test_positional_only_marker_for_a_module_function():
    assert _course_ctx("pair", kind="function")["unit"]["signature"] == "pair(a, b=1, /, c=2)"


def test_prompt_says_defaults_are_code_and_version_moved():
    assert unit_prompt.PROMPT_VERSION == "unit-v2"
    assert "not the text" in unit_prompt.USER_TEMPLATE
