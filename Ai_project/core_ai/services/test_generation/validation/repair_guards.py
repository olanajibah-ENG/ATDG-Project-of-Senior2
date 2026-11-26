import ast
from dataclasses import dataclass, field
from itertools import zip_longest

from .validator import _test_functions, _calls_unit


@dataclass
class GuardResult:
    ok: bool
    rule: str = ""
    detail: str = ""
    changed_assertions: list = field(default_factory=list)


def _checks(func):
    checks = []
    for node in sorted(ast.walk(func), key=lambda n: getattr(n, "lineno", 0)):
        if isinstance(node, ast.Assert):
            value = node.test
            if isinstance(value, ast.Compare):
                value = value.comparators[-1]
            if isinstance(value, ast.Call) and ast.unparse(value.func) == "pytest.approx":
                checks.append(", ".join(ast.unparse(arg) for arg in value.args))
            else:
                checks.append(ast.unparse(value))
        elif isinstance(node, ast.Call) and ast.unparse(node.func).endswith(".raises"):
            checks.append(", ".join(ast.unparse(arg) for arg in node.args))
    return checks


def _changes(before, after):
    remaining = {f.name: f for f in before}
    pairs = [(remaining.pop(f.name, None), f) for f in after]
    unused = iter(remaining.values())
    changes = []
    for old, new in pairs:
        old = old or next(unused, None)
        if old is None:
            changes.append(dict(kind="added", test=new.name))
            continue
        for index, (a, b) in enumerate(zip_longest(_checks(old), _checks(new))):
            if a != b:
                change = dict(test=new.name, index=index, kind="changed")
                if a is not None:
                    change["before"] = a
                else:
                    change["kind"] = "added"
                if b is not None:
                    change["after"] = b
                else:
                    change["kind"] = "removed"
                changes.append(change)
    return changes


_OPERATORS = {"__eq__": ast.Eq, "__ne__": ast.NotEq, "__lt__": ast.Lt, "__le__": ast.LtE,
              "__gt__": ast.Gt, "__ge__": ast.GtE, "__add__": ast.Add, "__sub__": ast.Sub,
              "__mul__": ast.Mult, "__truediv__": ast.Div, "__floordiv__": ast.FloorDiv,
              "__mod__": ast.Mod, "__pow__": ast.Pow, "__contains__": (ast.In, ast.NotIn),
              "__getitem__": ast.Subscript, "__setitem__": ast.Subscript, "__enter__": ast.With,
              "__exit__": ast.With, "__iter__": ast.For, "__str__": ast.FormattedValue, "__bool__": ast.If}
_BUILTINS = {"__len__": {"len"}, "__str__": {"str"}, "__repr__": {"repr"}, "__iter__": {"iter", "list"},
             "__hash__": {"hash"}, "__bool__": {"bool"}}


def _called(func, tree, unit, cls):
    if unit in _OPERATORS or unit in _BUILTINS:
        return any(isinstance(n, _OPERATORS.get(unit, ())) or isinstance(n, ast.Call) and
                   ast.unparse(n.func) in _BUILTINS.get(unit, ()) for n in ast.walk(func))
    return _calls_unit(func, tree, cls, unit)


def check(original_code, repaired_code, unit_name, class_name):
    tree = ast.parse(repaired_code)
    try:
        original = ast.parse(original_code or "")
    except SyntaxError:
        original = None
    functions = _test_functions(tree)
    for func in functions:
        if not _called(func, tree, unit_name, class_name):
            return GuardResult(False, "unit_not_called", func.name)
    for n in ast.walk(tree):
        if isinstance(n, ast.ExceptHandler) and (n.type is None or
                any(isinstance(t, ast.Name) and t.id in {"Exception", "BaseException"} for t in ast.walk(n.type))):
            if not any(isinstance(t, (ast.Raise, ast.Assert)) or isinstance(t, ast.Call) and
                       ast.unparse(t.func) == "pytest.fail" for t in ast.walk(n)):
                return GuardResult(False, "swallowed_failure")
        if isinstance(n, ast.Attribute) and n.attr in {"skip", "skipif", "xfail"}:
            return GuardResult(False, "skip_marker")
        if isinstance(n, ast.Call) and ast.unparse(n.func).split(".")[-1] in {"patch", "object", "setattr"}:
            if any(isinstance(a, ast.Constant) and str(a.value).split(".")[-1] == unit_name for a in n.args):
                return GuardResult(False, "mocks_unit")
    before = _test_functions(original) if original else []
    def generic_raises(t):
        return sum(1 for n in ast.walk(t) if isinstance(n, ast.Call) and ast.unparse(n.func).endswith(".raises")
                   and n.args and ast.unparse(n.args[0]) in {"Exception", "BaseException"})
    if original and generic_raises(tree) > generic_raises(original):
        return GuardResult(False, "generic_raises")
    if len(functions) < len(before):
        return GuardResult(False, "fewer_tests")
    if sum(len(_checks(f)) for f in functions) < sum(len(_checks(f)) for f in before):
        return GuardResult(False, "fewer_asserts")
    return GuardResult(True, changed_assertions=_changes(before, functions) if original else [])
