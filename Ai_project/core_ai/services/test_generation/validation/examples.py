"""Keep literal input/output examples from a function's docstring in its unit tests."""
import ast
import doctest
import re


def _literal(source):
    value = ast.literal_eval(source)
    if type(value) not in (int, float, str, bool, list, tuple, dict, type(None)):
        raise ValueError("unsupported example value")
    return repr(value)


def documented_test(context):
    unit = context["unit"]
    doc = unit.get("docstring") or ""
    if context.get("class") or ">>>" not in doc:
        return ""
    target = re.fullmatch(r"from ([\w.]+) import (\w+)", unit["import_statement"])
    if not target or target[2] != unit["name"]:
        return ""
    try:
        ast.parse(unit["import_statement"])
    except SyntaxError:
        return ""
    try:
        examples = doctest.DocTestParser().get_examples(doc)
    except ValueError:
        return ""

    checks = []
    for example in examples:
        try:
            call = ast.parse(example.source.strip(), mode="eval").body
            if (example.options or not isinstance(call, ast.Call) or call.keywords
                    or not isinstance(call.func, ast.Name) or call.func.id != unit["name"]):
                continue
            args = ", ".join(_literal(arg) for arg in call.args)
            expected = _literal(example.want.strip())
        except (SyntaxError, ValueError, TypeError, RecursionError):
            continue
        checks.append(f"    assert {unit['name']}({args}) == {expected}")
    if not checks:
        return ""
    return "\n".join(["def test_documented_examples():", "    " + unit["import_statement"], *checks])
