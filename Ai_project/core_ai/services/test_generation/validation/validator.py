"""Checks a model's answer WITHOUT running it. In order (the first failure decides the reason):

  1. extract   the code out of the answer            → no_code
  2. parse     it as Python                          → syntax_error
  3. imports   standard library, pytest, the project → forbidden_import
  4. safety    see safety_lint                       → unsafe_code
  5. weak test a test function exists, each one asserts something and calls the unit → weak_test
  6. naming    test functions are renamed to test_<unit>__<level>_<n>   (cannot fail)
"""
import ast
import re
import sys
from dataclasses import dataclass
from typing import Optional

from core_ai.services.test_generation.context import test_name_stem
from core_ai.services.test_generation.languages.python_adapter import split_unit_id
from core_ai.services.test_generation.statuses import FailReason
from core_ai.services.test_generation.validation.safety_lint import find_unsafe

_FENCE = re.compile(r"```[ \t]*(?:python|py)?[ \t]*\r?\n(.*?)```", re.DOTALL | re.IGNORECASE)
_OPEN_FENCE = re.compile(r"```[ \t]*(?:python|py)?[ \t]*\r?\n(.*)\Z", re.DOTALL | re.IGNORECASE)
CUT_OFF = "the answer was cut off before the code ended (the model ran out of answer length)"
ALWAYS_ALLOWED_ROOTS = frozenset({"pytest"})


@dataclass
class Result:
    ok: bool
    code: Optional[str] = None
    reason_code: Optional[str] = None
    reason_detail: Optional[str] = None

    def as_dict(self):
        return {"ok": self.ok, "reason_code": self.reason_code, "reason_detail": self.reason_detail}


def _fail(reason, detail):
    return Result(ok=False, reason_code=reason, reason_detail=detail)


def looks_cut_off(answer):
    """A code fence was opened and never closed: the model stopped in the middle of the file."""
    return (answer or "").count("```") % 2 == 1


def extract_code(answer):
    """The first fenced Python block; or the whole answer when it is itself Python with a function.
    A fence that was opened but never closed still yields its text, so that a cut-off answer is
    reported as what it is and not as "no code"."""
    text = answer or ""
    match = _FENCE.search(text)
    if match and match.group(1).strip():
        return match.group(1).strip("\n") + "\n"
    if looks_cut_off(text):
        open_match = _OPEN_FENCE.search(text)
        if open_match and open_match.group(1).strip():
            return open_match.group(1).strip("\n") + "\n"
    candidate = text.strip()
    if not candidate:
        return None
    try:
        tree = ast.parse(candidate)
    except SyntaxError:
        return None
    if any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) for node in ast.walk(tree)):
        return candidate + "\n"
    return None


def _forbidden_import(tree, allowed_roots):
    allowed = set(allowed_roots) | ALWAYS_ALLOWED_ROOTS
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots = [alias.name.split(".")[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                return "a relative import"
            roots = [(node.module or "").split(".")[0]]
        else:
            continue
        for root in roots:
            if root not in sys.stdlib_module_names and root not in allowed:
                return root
    return None


def _test_functions(tree):
    """Test functions in source order: module level, and methods of Test* classes."""
    found = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
            found.append(node)
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            found.extend(child for child in node.body
                         if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                         and child.name.startswith("test"))
    return sorted(found, key=lambda n: n.lineno)


def _has_check(func):
    for node in ast.walk(func):
        if isinstance(node, ast.Assert):
            return True
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "raises":
            return True
    return False


def _calls(scope, *, name=None, attr=None):
    for node in ast.walk(scope):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if name and isinstance(func, ast.Name) and func.id == name:
            return True
        if isinstance(func, ast.Attribute) and func.attr in (attr, name):
            return True
    return False


def _calls_unit(func, tree, class_name, unit_name):
    if class_name is None:                                   # a plain function
        return _calls(func, name=unit_name)
    if unit_name == "__init__":                              # the constructor: the class is called
        return _calls(func, name=class_name) or _calls(tree, name=class_name)
    if unit_name.startswith("__") and unit_name.endswith("__"):
        # other special methods are reached through an operator or a builtin (str(x), x == y),
        # so the only thing that can be checked is that an object of the class is made
        return _calls(func, name=class_name) or _calls(tree, name=class_name)
    return _calls(func, attr=unit_name)


def _rename(code, functions, stem, level):
    lines = code.split("\n")
    for index, func in enumerate(functions, start=1):
        new_name = f"test_{stem}__{level}_{index}"
        row = func.lineno - 1
        lines[row] = re.sub(r"(\bdef\s+)" + re.escape(func.name) + r"\b", r"\g<1>" + new_name, lines[row], count=1)
    return "\n".join(lines)


def validate(answer, *, unit_id, allowed_roots, level="unit"):
    code = extract_code(answer)
    if code is None:
        return _fail(FailReason.NO_CODE, "the answer holds no Python code")

    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        detail = f"line {exc.lineno}: {exc.msg}"
        if looks_cut_off(answer):
            detail = f"{CUT_OFF}; {detail}"
        return _fail(FailReason.SYNTAX_ERROR, detail)

    forbidden = _forbidden_import(tree, allowed_roots)
    if forbidden:
        return _fail(FailReason.FORBIDDEN_IMPORT, f"imports {forbidden}")

    unsafe = find_unsafe(tree)
    if unsafe:
        return _fail(FailReason.UNSAFE_CODE, unsafe)

    _, class_name, unit_name = split_unit_id(unit_id)
    functions = _test_functions(tree)
    if not functions:
        return _fail(FailReason.WEAK_TEST, "no test function")
    for func in functions:
        if not _has_check(func):
            return _fail(FailReason.WEAK_TEST, f"{func.name} has no assert")
        if not _calls_unit(func, tree, class_name, unit_name):
            return _fail(FailReason.WEAK_TEST, f"{func.name} never calls {unit_name}")

    renamed = _rename(code, functions, test_name_stem(unit_id), level)
    try:
        ast.parse(renamed)
    except SyntaxError as exc:  # renaming must never break the file
        return _fail(FailReason.SYNTAX_ERROR, f"after renaming, line {exc.lineno}: {exc.msg}")
    return Result(ok=True, code=renamed)
