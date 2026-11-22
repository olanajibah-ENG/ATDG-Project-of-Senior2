"""coverage.py: the job report and a record's contribution."""
from core_ai.services.test_generation import coverage, results
from core_ai.tests.test_generation.fake_sandbox import cov_json


def reduced(files):
    return results.reduce_coverage(cov_json(files, root="src"))


def test_report_shape_and_totals():
    r = coverage.job_report(reduced({"demo/course.py": (10, list(range(1, 9)), [9, 10], 4, 3),
                                     "demo/student.py": (5, [1, 2, 3, 4, 5], [], 0, 0)}),
                            final_run_id="f1", ready_count=3, plan_ranges=[],
                            version_paths=["demo/course.py", "demo/student.py", "config.json"])
    assert r["available"] and r["final_run_id"] == "f1" and r["scope"] == "ready records only (3)"
    course = r["files"][0]
    assert course == {"file": "demo/course.py", "statements": 10, "covered": 8, "line_pct": 80.0,
                      "branches": 4, "branches_covered": 3, "branch_pct": 75.0,
                      "missing_lines": [9, 10], "missing_annotations": {}}
    assert r["totals"] == {"statements": 15, "covered": 13, "branches": 4, "branches_covered": 3,
                           "line_pct": 86.67, "branch_pct": 75.0, "combined_pct": 84.21}
    assert r["not_measured"] == [{"file": "config.json", "reason": "unsupported_language"}]


def test_uncovered_line_of_a_skipped_unit_carries_the_plans_reason():
    plan = {"skipped": [{"path": "demo/course.py", "unit": "demo/course.py::Course._audit", "reason": "private", "line": 9}]}
    ranges = coverage.skipped_ranges(plan, lambda path, unit: {"line_start": 9, "line_end": 10})
    r = coverage.job_report(reduced({"demo/course.py": (10, list(range(1, 9)), [9, 10], 0, 0)}),
                            final_run_id="f", ready_count=1, plan_ranges=ranges, version_paths=["demo/course.py"])
    assert r["files"][0]["missing_annotations"] == {"9": "Course._audit — skipped: private",
                                                    "10": "Course._audit — skipped: private"}


def test_file_level_skips_have_no_line_range():
    assert coverage.skipped_ranges({"skipped": [{"path": "a.js", "reason": "unsupported_language"}]},
                                   lambda p, u: None) == []


def test_unavailable_and_totals_only():
    assert coverage.unavailable("no_ready_tests") == {"available": False, "reason": "no_ready_tests"}
    assert coverage.totals_only(coverage.unavailable("x")) is None
    r = coverage.job_report(reduced({"a.py": (2, [1], [2], 0, 0)}), final_run_id="f", ready_count=1,
                            plan_ranges=[], version_paths=["a.py"])
    assert coverage.totals_only(r) == {"line_pct": 50.0, "branch_pct": 100.0, "combined_pct": 50.0}


def test_contribution_is_labelled_as_the_records_own_run():
    c = coverage.record_contribution(reduced({"demo/course.py": (4, [1, 2], [3, 4], 2, 1)}))
    assert c == {"label": "this record's own run",
                 "files": [{"file": "demo/course.py", "covered_lines": [1, 2], "covered_branches": 1}]}
    assert coverage.record_contribution(None) is None
