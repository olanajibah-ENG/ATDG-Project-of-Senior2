import ast
from pathlib import Path
from zipfile import ZipFile

import pytest

from core_ai.services.test_generation.validation.validator import validate


def test_documented_boundary_runs_against_both_demo_versions():
    fixtures = Path(__file__).resolve().parents[4] / "docs/demo_versions/s4_cases"
    generated = "from s4_case import count_items\ndef test_normal():\n    assert count_items([1]) == 1"
    files = []
    for filename in ("05_source_bug.zip", "06_source_fixed.zip"):
        with ZipFile(fixtures / filename) as archive:
            source = archive.read("s4_case.py").decode()
        func = ast.parse(source).body[0]
        context = {"unit": {"docstring": ast.get_docstring(func), "name": func.name,
                            "import_statement": "from s4_case import count_items"}}
        kwargs = dict(unit_id="s4_case.py::count_items", allowed_roots={"s4_case"}, context=context)
        checked = validate(generated, **kwargs)
        assert checked.ok
        assert validate(checked.code, **kwargs).code == checked.code
        files.append(checked.code)
        import types
        import sys
        with pytest.MonkeyPatch.context() as patch:
            module = types.ModuleType("s4_case")
            exec(source, module.__dict__)
            patch.setitem(sys.modules, "s4_case", module)
            suite = {}
            exec(checked.code, suite)
            suite["test_count_items__unit_1"]()
            if filename.startswith("05"):
                with pytest.raises(AssertionError):
                    suite["test_count_items__unit_2"]()
            else:
                suite["test_count_items__unit_2"]()
    assert files[0] == files[1]
