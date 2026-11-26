"""results.py: reading junit.xml / coverage JSON and every row of the verdict table (research R5, R7)."""
import json

import pytest

from core_ai.services.test_generation import results
from core_ai.services.test_generation.sandbox.executor import RunOutput
from core_ai.tests.test_generation.fake_sandbox import (cov_json, junit, junit_collection_error, junit_fail,
                                                       junit_pass)

NAMES = ["test_Course___init____unit_1", "test_Course___init____unit_2"]
PROJECT = {"demo"}


def out(exit_code=0, junit_text=None, **kw):
    return RunOutput(run_id="r1", started=True, exit_code=exit_code, junit_xml=junit_text, **kw)


# ── junit.xml ────────────────────────────────────────────────────────────────

def test_parse_junit_reads_every_outcome_and_message():
    text = junit([("a", "passed", None), ("b", "failed", "assert 2 == '2'"), ("c", "error", "boom"),
                  ("d", "skipped", "why")])
    cases = results.parse_junit(text)
    assert [(c["name"], c["outcome"]) for c in cases] == [
        ("a", "passed"), ("b", "failed"), ("c", "error"), ("d", "skipped")]
    assert cases[1]["message"] == "assert 2 == '2'"


@pytest.mark.parametrize("text", [None, "", "not xml at all", "<html/>", "<testsuites>" + "x" * 1_100_000 + "</testsuites>"])
def test_unreadable_junit_is_none(text):
    assert results.parse_junit(text) is None


# ── the verdict table, row by row ────────────────────────────────────────────

def test_not_started_is_sandbox_unavailable():
    v = results.verdict(RunOutput(run_id="r", started=False, start_error="docker down"), NAMES, PROJECT)
    assert (v.status, v.reason, v.detail) == ("environment_error", "sandbox_unavailable", "docker down")


@pytest.mark.parametrize("kw", [{"exit_code": 137}, {"exit_code": 124}, {"exit_code": None, "timed_out": True}])
def test_killed_at_the_time_limit_is_run_timeout(kw):
    # S4: the real S3 whole-run kill is `timeout --signal=KILL` → exit 137, no OOM flag
    v = results.verdict(out(junit_text=junit_pass(NAMES), **kw), NAMES, PROJECT)
    assert (v.status, v.reason) == ("environment_error", "run_timeout")


def test_real_kill_without_junit_and_without_oom_is_run_timeout():
    v = results.verdict(out(exit_code=137, junit_text=None, oom_killed=False), NAMES, PROJECT)
    assert (v.status, v.reason) == ("environment_error", "run_timeout")


def test_oom_killed_is_out_of_memory():
    v = results.verdict(out(exit_code=137, junit_text=None, oom_killed=True), NAMES, PROJECT)
    assert (v.status, v.reason) == ("environment_error", "out_of_memory")


def test_one_hanging_test_is_a_repairable_timeout_with_its_name():
    text = junit([(NAMES[0], "passed", None), (NAMES[1], "failed", "Failed: Timeout >30.0s")])
    v = results.verdict(out(exit_code=1, junit_text=text), NAMES, PROJECT)
    assert (v.status, v.reason) == ("test_failed", "timeout")
    assert NAMES[1] in v.detail
    assert v.tests[1]["error_type"] == "Timeout"


def test_error_type_from_the_type_attribute_or_the_e_line():
    typed = ('<testsuites><testsuite><testcase classname="c" name="a"><failure type="builtins.ValueError" '
             'message="bad">x</failure></testcase><testcase classname="c" name="b"><failure message="m">'
             'def t():\n&gt;   f()\nE   KeyError: 3</failure></testcase><testcase classname="c" name="c">'
             '<failure message="assert 1 == 2">assert 1 == 2</failure></testcase></testsuite></testsuites>')
    cases = results.parse_junit(typed)
    assert [c["error_type"] for c in cases] == ["ValueError", "KeyError", "AssertionError"]


def test_network_blocked_stays_an_assertion_with_a_clear_message():
    text = junit_fail(NAMES, NAMES[0], "pytest_socket.SocketBlockedError: A test tried to use socket.socket.")
    v = results.verdict(out(exit_code=1, junit_text=text), NAMES, PROJECT)
    assert (v.status, v.reason) == ("test_failed", "assertion")
    assert "SocketBlockedError" in v.detail


def test_missing_third_party_module_wins_over_collection_error_on_exit_2():
    text = junit_collection_error("ModuleNotFoundError: No module named 'requests.adapters'")
    v = results.verdict(out(exit_code=2, junit_text=text), NAMES, PROJECT)
    assert (v.status, v.reason, v.detail) == ("environment_error", "missing_dependency", "requests.adapters")


def test_no_result_file():
    v = results.verdict(out(exit_code=0, junit_text=None), NAMES, PROJECT)
    assert (v.status, v.reason) == ("environment_error", "no_result_file")


def test_third_party_module_missing_is_missing_dependency():
    text = junit_collection_error("ModuleNotFoundError: No module named 'requests'")
    v = results.verdict(out(exit_code=2, junit_text=text), NAMES, PROJECT)
    assert (v.status, v.reason, v.detail) == ("environment_error", "missing_dependency", "requests")


def test_missing_project_module_is_the_tests_fault():
    text = junit_collection_error("ModuleNotFoundError: No module named 'demo.nope'")
    v = results.verdict(out(exit_code=2, junit_text=text), NAMES, PROJECT)
    assert (v.status, v.reason) == ("test_failed", "collection_error")


def test_missing_standard_library_name_is_not_a_dependency():
    text = junit_collection_error("ModuleNotFoundError: No module named 'collections.nope'")
    v = results.verdict(out(exit_code=2, junit_text=text), NAMES, PROJECT)
    assert v.reason == "collection_error"


def test_other_collection_error():
    text = junit_collection_error("ImportError: cannot import name 'Nope' from 'demo.course'")
    v = results.verdict(out(exit_code=2, junit_text=text), NAMES, PROJECT)
    assert (v.status, v.reason) == ("test_failed", "collection_error")
    assert "cannot import name" in v.detail


@pytest.mark.parametrize("exit_code, text", [(5, junit([])), (0, junit([]))])
def test_nothing_collected_is_no_tests(exit_code, text):
    v = results.verdict(out(exit_code=exit_code, junit_text=text), NAMES, PROJECT)
    assert (v.status, v.reason) == ("test_failed", "no_tests")


def test_a_failing_assert_is_assertion_with_the_first_message():
    text = junit_fail(NAMES, NAMES[1], "AssertionError: assert 2 == '2'")
    v = results.verdict(out(exit_code=1, junit_text=text), NAMES, PROJECT)
    assert (v.status, v.reason) == ("test_failed", "assertion")
    assert v.detail == "AssertionError: assert 2 == '2'"
    assert [t["outcome"] for t in v.tests] == ["passed", "failed"]


def test_a_skipped_test_is_not_ready():
    text = junit([(NAMES[0], "passed", None), (NAMES[1], "skipped", "no reason")])
    v = results.verdict(out(exit_code=0, junit_text=text), NAMES, PROJECT)
    assert (v.status, v.reason) == ("test_failed", "skipped_test")


def test_all_expected_tests_passed_is_ready():
    v = results.verdict(out(exit_code=0, junit_text=junit_pass(NAMES)), NAMES, PROJECT)
    assert v.acceptable and v.status == "ready" and v.reason is None
    assert [t["outcome"] for t in v.tests] == ["passed", "passed"]


def test_parametrized_cases_count_as_their_function():
    text = junit_pass([NAMES[0] + "[a]", NAMES[0] + "[b]", NAMES[1]])
    assert results.verdict(out(exit_code=0, junit_text=text), NAMES, PROJECT).acceptable


@pytest.mark.parametrize("names_in_file", [[NAMES[0]], NAMES + ["test_extra"]])
def test_names_that_do_not_match_the_test_file_are_not_trusted(names_in_file):
    v = results.verdict(out(exit_code=0, junit_text=junit_pass(names_in_file)), NAMES, PROJECT)
    assert (v.status, v.reason) == ("environment_error", "no_result_file")


def test_exit_code_1_with_an_all_passed_file_is_not_trusted():
    v = results.verdict(out(exit_code=1, junit_text=junit_pass(NAMES)), NAMES, PROJECT)
    assert not v.acceptable


# ── coverage JSON ────────────────────────────────────────────────────────────

def test_reduce_coverage_makes_paths_relative_and_keeps_the_figures():
    text = cov_json({"demo/course.py": (8, [1, 2, 3, 5, 6, 7], [9, 10], 4, 3)})
    reduced = results.reduce_coverage(text)
    assert reduced["files"]["demo/course.py"] == {
        "statements": 8, "covered": 6, "branches": 4, "branches_covered": 3,
        "executed_lines": [1, 2, 3, 5, 6, 7], "missing_lines": [9, 10]}


@pytest.mark.parametrize("text", [None, "", "{not json"])
def test_unreadable_coverage_is_none(text):
    assert results.reduce_coverage(text) is None


def test_reduce_coverage_ignores_unknown_fields():
    data = json.loads(cov_json({"a.py": (1, [1], [], 0, 0)}))
    data["totals"] = {"anything": 1}
    assert set(results.reduce_coverage(json.dumps(data))["files"]) == {"a.py"}


# ── review point 5: a damaged result file is never trusted ──────────────────

@pytest.mark.parametrize("damaged", [
    "<testsuites><testsuite><testcase name='x'>",          # cut off mid-file
    "garbage that is not xml",
    "<html><body>not junit</body></html>",
    "<testsuites>" + "<testcase name='t'/>" * 60000 + "</testsuites>",   # over the size cap
])
@pytest.mark.parametrize("exit_code", [0, 1])
def test_a_damaged_result_file_is_no_result_file_never_ready(damaged, exit_code):
    v = results.verdict(out(exit_code=exit_code, junit_text=damaged), NAMES, PROJECT)
    assert (v.status, v.reason) == ("environment_error", "no_result_file")
    assert not v.acceptable


# ── found in the first real run (2026-11-20) ────────────────────────────────

def test_coverage_paths_relative_to_the_working_directory_are_made_project_relative():
    text = cov_json({"demo/course.py": (8, [1, 2], [3], 0, 0)}, root="src")
    assert set(results.reduce_coverage(text)["files"]) == {"demo/course.py"}


def test_a_passed_test_has_no_message():
    v = results.verdict(out(exit_code=0, junit_text=junit_pass(NAMES)), NAMES, PROJECT)
    assert {t["message"] for t in v.tests} == {None}
