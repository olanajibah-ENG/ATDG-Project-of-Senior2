import ast

import pytest

from core_testing.validation import validator
from core_testing.validation.safety_lint import find_unsafe

ENROLL = "game.py::Student.enroll"
ROOTS = {"game"}

GOOD = '''import pytest
from game import Student, Course


def test_enroll_adds_course():
    student = Student("a", 1, "cs")
    course = Course("m", "M1")
    assert student.enroll(course) is True


def test_enroll_twice():
    student = Student("a", 1, "cs")
    course = Course("m", "M1")
    student.enroll(course)
    assert student.enroll(course) is False
'''


def fenced(code):
    return "Sure, here it is:\n\n```python\n" + code + "```\nHope it helps."


def check(answer, unit_id=ENROLL, roots=ROOTS):
    return validator.validate(answer, unit_id=unit_id, allowed_roots=roots)


# ── 1. extract ───────────────────────────────────────────────────────────────

def test_code_is_taken_from_the_fenced_block():
    result = check(fenced(GOOD))
    assert result.ok and "Sure, here" not in result.code and "Hope it helps" not in result.code


def test_bare_code_without_a_fence_is_accepted():
    assert check(GOOD).ok


@pytest.mark.parametrize("answer", ["", "   ", "I cannot write this test.", "```python\n\n```"])
def test_answer_without_code_is_no_code(answer):
    result = check(answer)
    assert (result.ok, result.reason_code) == (False, "no_code")


# ── 2. parse ─────────────────────────────────────────────────────────────────

def test_broken_code_is_syntax_error():
    result = check(fenced("def test_x(:\n    assert True\n"))
    assert result.reason_code == "syntax_error" and "line 1" in result.reason_detail


# ── 3. imports ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("line, module", [("import numpy", "numpy"), ("from flask import Flask", "flask"),
                                          ("import other_project.mod", "other_project")])
def test_import_outside_stdlib_pytest_and_project_is_forbidden(line, module):
    result = check(fenced(line + "\n" + GOOD))
    assert result.reason_code == "forbidden_import" and module in result.reason_detail


def test_relative_import_is_forbidden():
    assert check(fenced("from . import game\n" + GOOD)).reason_code == "forbidden_import"


def test_stdlib_pytest_mock_and_project_imports_pass():
    code = "import os\nimport json\nfrom unittest import mock\nfrom unittest.mock import MagicMock\n" + GOOD
    assert check(fenced(code)).ok


def test_project_roots_come_from_the_caller():
    assert check(fenced(GOOD), roots=set()).reason_code == "forbidden_import"


# ── 4. safety ────────────────────────────────────────────────────────────────

def test_unsafe_code_is_refused_with_its_reason():
    result = check(fenced("import subprocess\n" + GOOD))
    assert result.reason_code == "unsafe_code" and "subprocess" in result.reason_detail


# ── 5. weak test ─────────────────────────────────────────────────────────────

def test_no_test_function_is_weak():
    result = check(fenced("from game import Student\n\ndef helper():\n    return Student\n"))
    assert (result.reason_code, result.reason_detail) == ("weak_test", "no test function")


def test_test_without_assert_is_weak():
    code = "from game import Student, Course\n\ndef test_a():\n    Student('a', 1, 'c').enroll(Course('m', 'M'))\n"
    result = check(fenced(code))
    assert result.reason_code == "weak_test" and "no assert" in result.reason_detail


def test_test_that_never_calls_the_unit_is_weak():
    code = "from game import Student\n\ndef test_a():\n    s = Student('a', 1, 'c')\n    assert s.name == 'a'\n"
    result = check(fenced(code))
    assert result.reason_code == "weak_test" and "never calls enroll" in result.reason_detail


def test_pytest_raises_counts_as_a_check():
    code = ("import pytest\nfrom game import Student\n\ndef test_a():\n"
            "    with pytest.raises(AttributeError):\n        Student('a', 1, 'c').enroll(None)\n")
    assert check(fenced(code)).ok


def test_constructor_is_called_through_the_class():
    code = "from game import Student\n\ndef test_a():\n    s = Student('a', 1, 'cs')\n    assert s.major == 'cs'\n"
    assert check(fenced(code), unit_id="game.py::Student.__init__").ok
    assert check(fenced(code), unit_id="game.py::Course.__init__").reason_code == "weak_test"


def test_plain_function_is_called_by_name():
    code = "from shop.models import format_price\n\ndef test_a():\n    assert format_price(1) == '1.00'\n"
    assert check(fenced(code), unit_id="shop/models.py::format_price", roots={"shop"}).ok


# ── 6. naming ────────────────────────────────────────────────────────────────

def test_test_functions_are_renamed_in_order():
    result = check(fenced(GOOD))
    names = [n.name for n in ast.parse(result.code).body if isinstance(n, ast.FunctionDef)]
    assert names == ["test_Student_enroll__unit_1", "test_Student_enroll__unit_2"]


def test_renaming_keeps_bodies_and_helpers_untouched():
    code = ("from game import Student, Course\n\n\ndef make():\n    return Student('a', 1, 'c')\n\n\n"
            "def test_enroll_ok():  # keeps this comment\n    assert make().enroll(Course('m', 'M')) is True\n")
    result = check(fenced(code))
    assert "def make():" in result.code and "# keeps this comment" in result.code
    assert "def test_Student_enroll__unit_1():" in result.code


def test_constructor_tests_get_a_valid_name():
    code = "from game import Student\n\ndef test_a():\n    assert Student('a', 1, 'cs').major == 'cs'\n"
    result = check(fenced(code), unit_id="game.py::Student.__init__")
    assert "def test_Student___init____unit_1():" in result.code


# ── order ────────────────────────────────────────────────────────────────────

def test_the_first_failing_check_decides_the_reason():
    # forbidden import AND unsafe AND weak: the import check comes first
    code = "import numpy\nimport subprocess\n\ndef test_a():\n    pass\n"
    assert check(fenced(code)).reason_code == "forbidden_import"


def test_nothing_is_executed_while_checking():
    code = ("from game import Student\nraise SystemExit('executed!')\n\n"
            "def test_a():\n    assert Student('a', 1, 'c').enroll(None)\n")
    assert check(fenced(code)).ok        # the file would exit if it were ever imported


# ── safety lint, rule by rule ────────────────────────────────────────────────

@pytest.mark.parametrize("code", [
    "import socket", "import subprocess", "from urllib import request", "import http.client",
    "import requests", "x = eval('1')", "exec('a = 1')", "import os\nos.system('ls')",
    "import time\ntime.sleep(1)", "from time import sleep", "import shutil\nshutil.rmtree('x')",
    "open('out.txt', 'w')", "open('out.txt', mode='a')",
])
def test_unsafe_constructs_are_reported(code):
    assert find_unsafe(ast.parse(code)) is not None


@pytest.mark.parametrize("code", [
    "open('data.txt')", "open('data.txt', 'r')", "open(tmp_path / 'out.txt', 'w')",
    "monkeypatch.setattr(obj, 'x', 1)", "import os\nos.path.join('a', 'b')", "import time\ntime.time()",
])
def test_safe_constructs_are_not_reported(code):
    assert find_unsafe(ast.parse(code)) is None


# ── an answer the model did not finish ───────────────────────────────────────

CUT = ("```python\nfrom game import Student, Course\n\n"
       "def test_a():\n    assert Student('a', 1, 'c').enroll(Course('m', 'M')) is True\n\n"
       "def test_b():\n    student = Student('a', 1,")          # no closing fence, stops mid-call


def test_cut_off_answer_is_recognised():
    assert validator.looks_cut_off(CUT) is True
    assert validator.looks_cut_off(fenced(GOOD)) is False
    assert validator.looks_cut_off(GOOD) is False
    assert validator.looks_cut_off(None) is False


def test_cut_off_answer_is_a_syntax_error_that_says_so():
    result = check(CUT)
    assert result.reason_code == "syntax_error"          # not "no_code": there was code, it just stopped
    assert "cut off" in result.reason_detail and "line" in result.reason_detail


def test_cut_off_exactly_between_two_tests_is_still_usable():
    answer = ("```python\nfrom game import Student, Course\n\n"
              "def test_a():\n    assert Student('a', 1, 'c').enroll(Course('m', 'M')) is True\n")
    result = check(answer)
    assert result.ok and "def test_Student_enroll__unit_1():" in result.code
