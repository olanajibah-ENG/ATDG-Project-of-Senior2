# API Contract: S3 — Isolated Run, Acceptance Gate, Coverage and Bundle

All routes are under `/api/analysis/tests/`, need `Authorization: Bearer <UPM access token>`, and
read a job only for its creator (403 otherwise). Errors keep the S1 shape
`{"error": {"code", "message", "details"}}`.

## Changes to existing routes

### `POST jobs/` — unchanged

The run stage starts by itself after generation.

### `GET jobs/{job_id}/` — more values

```json
{
  "job_id": "job_…", "status": "running", "stage": "sandbox_run",
  "progress": {"total": 15, "done": 5,
               "by_status": {"pending": 10, "generated": 1, "ready": 3, "test_failed": 1,
                             "environment_error": 0, "skipped": 0, "generation_failed": 0}},
  "files": [ … unchanged … ],
  "coverage": null,
  "error": null
}
```

- `stage`: also `sandbox_run`, `final_run`.
- When finished: `status` `completed` (every run record `ready`) or `completed_with_issues`, and
  `coverage` holds `{"line_pct", "branch_pct", "combined_pct"}` (totals only; full report on the
  coverage route) or `null` when there is no `ready` test.

### `GET jobs/{job_id}/records/` — more values

`status` filter also accepts `ready`, `test_failed`, `environment_error` (already allowed values).
Each item gains `executed` (bool) and the S3 `reason_code` values.

### `GET jobs/{job_id}/records/{record_id}/` — run details

```json
{
  "id": "t_…", "file": "demo/course.py", "unit_id": "demo/course.py::Course.__init__",
  "level": "unit", "status": "ready", "reason_code": null, "reason_detail": null,
  "test_path": "tests/generated/unit/test_demo_course_Course___init____unit.py",
  "test_code": "…",
  "executed": true,
  "notice": "This test was run in an isolated environment on version 10 and passed.",
  "run": {"run_id": "sbx_job_…_t_…_1", "exit_code": 0, "duration_s": 0.31,
          "tests": [{"name": "test_Course___init____unit_1", "outcome": "passed", "message": null}],
          "output": "…"},
  "evidence": {"run_id": "sbx_…", "version_number": 10, "body_hash": "d828b891…",
               "test_sha256": "…", "tests": 3, "passed": 3, "duration_s": 0.31,
               "accepted_at": "2026-11-20T…Z"},
  "coverage_contribution": {"label": "this record's own run",
                            "files": [{"file": "demo/course.py", "covered_lines": [2,3,4,5],
                                       "covered_branches": 0}]},
  "model": "cohere/north-mini-code:free", "prompt_version": "unit-v2"
}
```

- `test_code` is now shown for `ready`, `test_failed` and `environment_error` too (it was only for
  `generated`).
- `notice` per status: `generated` → "generated and checked for form only; not run";
  `ready` → "run … and passed"; `test_failed` / `environment_error` → "run … and did not pass: <reason>".
- A failed record has `evidence: null` and `run.tests[*].message` set for failures.

## New: coverage of a job

`GET jobs/{job_id}/coverage/`

- `200` — the report of [data-model.md](../data-model.md#coverage-report-on-the-job), or
  `{"available": false, "reason": "no_ready_tests"}`.
- `409 coverage_not_ready` — the job is not finished.

## New: bundle of a job

`GET jobs/{job_id}/bundle/`

- `200` — `Content-Type: application/zip`,
  `Content-Disposition: attachment; filename="<job_id>_<project>_v<version>.zip"`; content as in
  [data-model.md](../data-model.md#bundle-built-on-request-never-stored).
- `409 bundle_not_ready` — the job is not finished.

## Reason codes added in S3

| Status | `reason_code` | Meaning |
|---|---|---|
| `test_failed` | `assertion` | a test failed or errored while running |
| `test_failed` | `collection_error` | the test file could not be collected (wrong project import, …) |
| `test_failed` | `no_tests` | nothing was collected |
| `test_failed` | `skipped_test` | a test was skipped |
| `test_failed` | `timeout` | the 60 s limit was reached |
| `test_failed` | `fails_with_others` | passed alone, failed in the final run |
| `environment_error` | `missing_dependency` | project code needs a library that is not installed (`reason_detail` = module) |
| `environment_error` | `sandbox_unavailable` | the run environment could not be started |
| `environment_error` | `no_result_file` | no readable / consistent result file |
