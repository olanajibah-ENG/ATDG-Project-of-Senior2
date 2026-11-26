"""A sandbox that starts no container: it answers each run from a script.

`script` maps a test path (or "final") to a RunOutput-like dict:
    {"exit_code", "junit", "cov", "output", "start_error", "timed_out"}
A value may also be a list: one entry per call, for paths run more than once (the final run).
Runs not in the script pass: exit 0 and a junit with the test names found in the test file.
"""
import ast
import json
from xml.sax.saxutils import escape

from core_ai.services.test_generation.sandbox.executor import RunOutput, SandboxExecutor


def junit(cases):
    """cases: [(name, outcome, message)] with outcome passed|failed|error|skipped; classname '' for collection."""
    parts = []
    for name, outcome, message, *rest in cases:
        classname = rest[0] if rest else "tests.generated.unit.t"
        inner = ""
        if outcome == "failed":
            inner = f'<failure message="{escape(message or "")}">{escape(message or "")}</failure>'
        elif outcome == "error":
            inner = f'<error message="{escape(message or "")}">{escape(message or "")}</error>'
        elif outcome == "skipped":
            inner = f'<skipped message="{escape(message or "")}"/>'
        parts.append(f'<testcase classname="{classname}" name="{escape(name)}" time="0.001">{inner}</testcase>')
    return ('<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite name="pytest" tests="%d">%s'
            '</testsuite></testsuites>' % (len(cases), "".join(parts)))


def junit_pass(names):
    return junit([(n, "passed", None) for n in names])


def junit_fail(names, failing, message):
    return junit([(n, "failed" if n == failing else "passed", message if n == failing else None) for n in names])


def junit_collection_error(message, module="tests.generated.unit.test_x"):
    return junit([(module, "error", message, "")])


def cov_json(files, root="/workspace/src"):
    """files: {path: (statements, executed_lines, missing_lines, branches, branches_covered)}."""
    out = {"meta": {"format": 3, "branch_coverage": True}, "files": {}}
    for path, (statements, executed, missing, branches, covered_branches) in files.items():
        out["files"][f"{root}/{path}"] = {
            "executed_lines": list(executed), "missing_lines": list(missing),
            "summary": {"num_statements": statements, "covered_lines": len(executed),
                        "num_branches": branches, "covered_branches": covered_branches},
        }
    return json.dumps(out)


def _names_in(test_files):
    names = []
    for path, content in test_files.items():
        if not path.endswith(".py"):
            continue
        tree = ast.parse(content.decode("utf-8") if isinstance(content, bytes) else content)
        names += [n.name for n in tree.body if isinstance(n, ast.FunctionDef) and n.name.startswith("test")]
    return names


class FakeSandboxExecutor(SandboxExecutor):
    def __init__(self, script=None, start_error=None):
        self.script = dict(script or {})
        self.start_error = start_error            # every run fails to start
        self.specs = []                            # every RunSpec received
        self.prepared = []                         # (job_id, files) of prepare_source calls
        self.discarded = []
        self.installs = []

    def install(self, request):
        from core_ai.services.test_generation.sandbox.executor import InstallOutput
        self.installs.append(request)
        entry = self.script.get("install")
        if isinstance(entry, list):
            entry = entry.pop(0)
        return entry or InstallOutput(True, volume="env_" + request.env_key)

    def probe_imports(self, request):
        return self.script.get("probe", {name: {"ok": True} for name in request.modules})

    def prepare_source(self, job_id, files):
        self.prepared.append((job_id, dict(files)))
        return f"sbx_{job_id}_src"

    def discard_source(self, volume):
        self.discarded.append(volume)

    def run(self, spec):
        self.specs.append(spec)
        if self.start_error:
            return RunOutput(run_id=spec.run_id, started=False, start_error=self.start_error)
        key = "final" if "_final_" in spec.run_id else (spec.test_paths[0] if spec.test_paths else "")
        if spec.mode == "collect_only":
            key = ("collect_only", key)
        entry = self.script.get(key)
        if isinstance(entry, list):
            entry = entry.pop(0) if entry else None
        if isinstance(entry, RunOutput):
            return entry
        if entry is None:
            entry = {"exit_code": 0, "junit": junit_pass(_names_in(spec.test_files))}
        if entry.get("start_error"):
            return RunOutput(run_id=spec.run_id, started=False, start_error=entry["start_error"])
        return RunOutput(run_id=spec.run_id, started=True, exit_code=entry.get("exit_code", 0),
                         timed_out=entry.get("timed_out", False), junit_xml=entry.get("junit"),
                         cov_json=entry.get("cov"), output=entry.get("output", ""), duration_s=0.2,
                         options={"network": "none"})
