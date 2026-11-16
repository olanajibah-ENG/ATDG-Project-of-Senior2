"""Reads a generated test's syntax tree and refuses code that reaches outside the test:
network, processes, evaluating text as code, sleeping, deleting, or writing files outside pytest's
temporary directory. Nothing is imported or executed here.
"""
import ast

FORBIDDEN_IMPORT_ROOTS = frozenset({
    "socket", "urllib", "http", "requests", "ftplib", "smtplib", "telnetlib",
    "subprocess", "multiprocessing",
})
FORBIDDEN_NAME_CALLS = frozenset({"eval", "exec", "compile", "__import__"})
FORBIDDEN_ATTR_CALLS = frozenset({
    "os.system", "os.popen", "os.remove", "os.unlink", "os.rmdir", "os.removedirs",
    "shutil.rmtree", "time.sleep",
})
FORBIDDEN_FROM_IMPORTS = frozenset({("time", "sleep"), ("os", "system"), ("os", "popen"),
                                    ("os", "remove"), ("shutil", "rmtree")})
_TMP_MARKERS = ("tmp_path", "tmpdir", "tmp_path_factory")


def _dotted(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def _open_mode(call):
    if len(call.args) >= 2 and isinstance(call.args[1], ast.Constant):
        return call.args[1].value
    for keyword in call.keywords:
        if keyword.arg == "mode" and isinstance(keyword.value, ast.Constant):
            return keyword.value.value
    return "r"


def find_unsafe(tree):
    """→ one readable line describing the first unsafe thing found, or None."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in FORBIDDEN_IMPORT_ROOTS:
                    return f"imports {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root in FORBIDDEN_IMPORT_ROOTS:
                return f"imports from {node.module}"
            for alias in node.names:
                if (root, alias.name) in FORBIDDEN_FROM_IMPORTS:
                    return f"imports {alias.name} from {root}"
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                if func.id in FORBIDDEN_NAME_CALLS:
                    return f"calls {func.id}()"
                if func.id == "open":
                    mode = str(_open_mode(node))
                    if any(flag in mode for flag in "wax+"):
                        target = ast.unparse(node.args[0]) if node.args else ""
                        if not any(marker in target for marker in _TMP_MARKERS):
                            return f"opens a file for writing outside tmp_path: open({target}, {mode!r})"
            else:
                dotted = _dotted(func)
                if dotted in FORBIDDEN_ATTR_CALLS:
                    return f"calls {dotted}()"
    return None
