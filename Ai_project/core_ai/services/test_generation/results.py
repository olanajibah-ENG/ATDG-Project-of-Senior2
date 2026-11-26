"""Reading what a run left behind, and deciding what it means (research R5, R7).

The decision never comes from printed output: it comes from the exit code, the structured result
file pytest writes (`junit.xml`) and the names of the tests the record is supposed to contain.
Nothing here writes anything; the acceptance gate acts on the Verdict.
"""
import json
import re
import sys
from dataclasses import dataclass, field
from xml.etree import ElementTree

from core_ai.services.test_generation.statuses import RecordStatus, RunReason

MAX_RESULT_BYTES = 1_000_000
TIMEOUT_EXIT_CODES = (124, 137)              # `timeout` itself (124) or KILL (128 + 9); OOM is also 137
_MISSING_MODULE = re.compile(r"No module named ['\"]([A-Za-z0-9_.]+)['\"]")
_PARAM_SUFFIX = re.compile(r"\[.*\]$")
_ERROR_LINE = re.compile(r"^E\s+([A-Za-z_][\w.]*(?:Error|Exception|Exit|Interrupt|Blocked\w*))\b", re.M)
_PER_TEST_TIMEOUT = "Failed: Timeout"
_STDLIB = set(getattr(sys, "stdlib_module_names", ())) | set(sys.builtin_module_names)


@dataclass
class Verdict:
    status: str                    # ready | test_failed | environment_error
    reason: object = None          # RunReason value, None when ready
    detail: object = None          # first failure message, missing module, …
    tests: list = field(default_factory=list)

    @property
    def acceptable(self):
        return self.status == RecordStatus.READY


# ── junit.xml ───────────────────────────────────────────────────────────────

def parse_junit(text):
    """→ [{name, classname, outcome, message, text}] or None when there is no readable file."""
    if not text or len(text.encode("utf-8", "ignore")) > MAX_RESULT_BYTES:
        return None
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError:
        return None
    if root.tag not in ("testsuites", "testsuite"):
        return None
    cases = []
    for case in root.iter("testcase"):
        outcome, message, body, error_type = "passed", None, None, None
        for tag in ("failure", "error", "skipped"):
            child = case.find(tag)
            if child is not None:
                outcome = {"failure": "failed", "error": "error", "skipped": "skipped"}[tag]
                message = child.get("message")
                body = (child.text or "").strip() or None
                if tag != "skipped":
                    error_type = _error_type(child.get("type"), message, body)
                break
        cases.append({"name": case.get("name") or "", "classname": case.get("classname") or "",
                      "outcome": outcome, "message": message, "text": body, "error_type": error_type})
    return cases


def _error_type(type_attr, message, body):
    """`type=` when pytest writes it, else the last `E   Name:` line, else Timeout for pytest-timeout."""
    if (message or "").startswith(_PER_TEST_TIMEOUT) or (body or "").find("Timeout >") >= 0:
        return "Timeout"
    if type_attr:
        return type_attr.rsplit(".", 1)[-1]
    found = _ERROR_LINE.findall(body or "") or _ERROR_LINE.findall(message or "")
    if found:
        return found[-1].rsplit(".", 1)[-1]
    if (message or "").lstrip().startswith("assert"):
        return "AssertionError"
    return None


def _short(text, limit=500):
    text = (text or "").strip()
    if not text:
        return None                       # a passed test has no message (was "": found in the real run)
    return text if len(text) <= limit else text[:limit] + " …"


def _missing_module(cases, output):
    for case in cases or []:
        for chunk in (case.get("message"), case.get("text")):
            match = _MISSING_MODULE.search(chunk or "")
            if match:
                return match.group(1)
    match = _MISSING_MODULE.search(output or "")
    return match.group(1) if match else None


def _base_name(name):
    return _PARAM_SUFFIX.sub("", name or "")


# ── the decision ────────────────────────────────────────────────────────────

def verdict(output, expected_names, project_names):
    """`output`: sandbox RunOutput. `expected_names`: test functions in the stored test file.
    `project_names`: top-level import names of the version's Python files."""
    failed, env = RecordStatus.TEST_FAILED, RecordStatus.ENVIRONMENT_ERROR

    if not output.started:
        return Verdict(env, RunReason.SANDBOX_UNAVAILABLE, _short(output.start_error))
    if getattr(output, "oom_killed", False):
        return Verdict(env, RunReason.OUT_OF_MEMORY, "the run was killed for using too much memory")
    if output.timed_out or output.exit_code in TIMEOUT_EXIT_CODES:
        return Verdict(env, RunReason.RUN_TIMEOUT, "the whole run was stopped at its time limit")

    cases = parse_junit(output.junit_xml)
    if cases is None:
        return Verdict(env, RunReason.NO_RESULT_FILE, "the run left no readable result file")
    tests = [{"name": c["name"], "outcome": c["outcome"], "message": _short(c["message"] or c["text"]),
              "error_type": c.get("error_type")} for c in cases]

    missing = _missing_module(cases, output.output)
    if missing and output.exit_code != 0:
        root = missing.split(".")[0]
        if root not in project_names and root not in _STDLIB:
            return Verdict(env, RunReason.MISSING_DEPENDENCY, missing, tests)
    if output.exit_code == 2 or any(c["outcome"] == "error" and not c["classname"] for c in cases):
        first = next((c for c in cases if c["outcome"] == "error"), None)
        return Verdict(failed, RunReason.COLLECTION_ERROR,
                       _short((first or {}).get("text") or (first or {}).get("message") or output.output), tests)
    if output.exit_code == 5 or not cases:
        return Verdict(failed, RunReason.NO_TESTS, "no test was collected", tests)

    hung = next((c for c in cases if c.get("error_type") == "Timeout"), None)
    if hung is not None:
        return Verdict(failed, RunReason.TIMEOUT, f"{hung['name']}: " + (_short(hung["message"]) or "timed out"),
                       tests)
    bad = next((c for c in cases if c["outcome"] in ("failed", "error")), None)
    if bad is not None:
        return Verdict(failed, RunReason.ASSERTION, _short(bad["message"] or bad["text"]), tests)
    if any(c["outcome"] == "skipped" for c in cases):
        return Verdict(failed, RunReason.SKIPPED_TEST, "a test was skipped, so it proves nothing", tests)

    ran = {_base_name(c["name"]) for c in cases}
    if output.exit_code == 0 and expected_names and ran == set(expected_names):
        return Verdict(RecordStatus.READY, None, None, tests)
    return Verdict(env, RunReason.NO_RESULT_FILE,
                   "the result file does not match the test file (exit code or test names)", tests)


# ── coverage JSON (coverage.py format 3) ────────────────────────────────────

def reduce_coverage(text, src_root="/workspace/src"):
    """→ {"files": {relative path: {...}}, "totals": {...}} or None."""
    if not text or len(text.encode("utf-8", "ignore")) > 20 * MAX_RESULT_BYTES:
        return None
    try:
        raw = json.loads(text)
    except ValueError:
        return None
    files = {}
    prefix = src_root.rstrip("/") + "/"
    relative_prefix = prefix.split("/workspace/", 1)[-1]          # "src/"
    for path, data in (raw.get("files") or {}).items():
        # coverage.py writes paths relative to the working directory (/workspace): "src/demo/course.py"
        # (found in the first real run); absolute ones are handled too.
        if path.startswith(prefix):
            rel = path[len(prefix):]
        elif path.startswith(relative_prefix):
            rel = path[len(relative_prefix):]
        else:
            rel = path.lstrip("/")
        summary = data.get("summary") or {}
        files[rel] = {
            "statements": int(summary.get("num_statements") or 0),
            "covered": int(summary.get("covered_lines") or 0),
            "branches": int(summary.get("num_branches") or 0),
            "branches_covered": int(summary.get("covered_branches") or 0),
            "executed_lines": sorted(data.get("executed_lines") or []),
            "missing_lines": sorted(data.get("missing_lines") or []),
        }
    return {"files": files}
