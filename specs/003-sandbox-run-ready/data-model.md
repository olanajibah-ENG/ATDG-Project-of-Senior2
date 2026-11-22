# Data Model: S3 — Isolated Run, Acceptance Gate, Coverage and Bundle

## New: `test_runs` (one document per container run)

| Field | Type | Notes |
|---|---|---|
| `run_id` | str | `sbx_<job>_<record or "final">_<n>`; also the container name |
| `job_id` | str | |
| `record_id` | str \| null | null for a final run |
| `kind` | `record` \| `final` | |
| `version_number` | int | the job's version |
| `test_paths` | [str] | test files in the run |
| `started_at`, `finished_at` | datetime | |
| `exit_code` | int \| null | null when the container never started |
| `timed_out` | bool | |
| `tests` | [{`name`, `outcome`, `message`}] | from `junit.xml`; outcome ∈ passed, failed, error, skipped |
| `output` | str | printed output, cut to `TESTGEN_SANDBOX_OUTPUT_LIMIT` |
| `coverage` | object \| null | reduced coverage of this run (see below) |
| `verdict` | {`status`, `reason`, `detail`} | the decision of R5 |
| `options` | object | image and limits used (network, cpus, memory, pids, timeout, read_only, user) |

Kept for audit; a record points at its last run.

## Changed: `test_records`

New fields (all optional, absent until the record is run):

| Field | Type | Notes |
|---|---|---|
| `run_id` | str | the record's run |
| `executed` | bool | true once run (was always false in S2) |
| `run_result` | {`tests`, `exit_code`, `duration_s`, `output`} | copy of the run's essentials |
| `reason_code` | str | now also: `assertion`, `collection_error`, `no_tests`, `skipped_test`, `timeout`, `fails_with_others`, `missing_dependency`, `sandbox_unavailable`, `no_result_file` |
| `reason_detail` | str | failure message, missing module name, … |
| `evidence` | {`run_id`, `version_number`, `body_hash`, `test_sha256`, `tests`, `passed`, `duration_s`, `accepted_at`} | **only on `ready`; written only by the acceptance gate** |
| `coverage_contribution` | {`files`: [{`file`, `covered_lines`, `covered_branches`}], `label`: "this record's own run"} | only on `ready` |

### Record status transitions added in S3

```text
generated ──run──► ready                     (acceptance gate, with evidence)
          └──run──► test_failed              (assertion | collection_error | no_tests | skipped_test | timeout)
          └──run──► environment_error        (missing_dependency | sandbox_unavailable | no_result_file)
ready ──final run fails──► test_failed       (fails_with_others; evidence removed, run kept)
```

`generation_failed`, `pending` (edge, integration) and `skipped` are never run and never change here.

## Changed: `test_jobs`

| Field | Type | Notes |
|---|---|---|
| `stage` | new values `sandbox_run`, `final_run` | after `generated` |
| `sandbox` | {`src_volume`, `runs`, `next_record_id`} | bookkeeping of the run stage |
| `coverage` | object \| null | the official report (below), from the final all-pass run |
| `final_run_id` | str \| null | the run the coverage came from |
| `progress.by_status` | — | already holds `ready`, `test_failed`, `environment_error` |

### Job stage transitions

```text
… generating ─► generated ─► sandbox_run ─► final_run ─► (status completed | completed_with_issues)
                    │                                       completed            = every run record ready
                    └─ no generated record ─► completed_with_issues (nothing to run)
```

Stage `generated` now means "generation finished"; the job stays `running` until the final run ends.
A job whose passes stop is failed by the existing stale-job rule.

## Coverage report (on the job)

```text
{
  "final_run_id": "...", "branch": true,
  "scope": "ready records only (N)",
  "files": [ { "file", "statements", "covered", "line_pct", "branches", "branches_covered",
               "branch_pct", "missing_lines": [..], "missing_annotations": { "<line>": "<reason>" } } ],
  "totals": { "statements", "covered", "line_pct", "branches", "branches_covered", "branch_pct",
              "combined_pct" },
  "not_measured": [ { "file", "reason" } ],
  "excluded_records": [ { "record_id", "reason" } ]       # fails_with_others
}
```

No `ready` record → `{"available": false, "reason": "no_ready_tests"}`.

## Bundle (built on request, never stored)

```text
<job_id>_<project>_v<version>.zip
├── MANIFEST.json            job, project, version, created_at, files: [{path, sha256}]
├── junit_results.xml        junit of the final all-pass run (ready tests only)
├── coverage_report.json     the report above
├── plan.json                the job's plan
├── records_summary.json     every record: unit, level, status, reason, test_path, run_id
├── pytest.ini               [pytest] pythonpath = src ; addopts = -p no:cacheprovider
└── tests/generated/unit/…   the ready test files only
```

## In memory only

- **Workspace**: the version's files as `{path: bytes}` read from GridFS, plus per run the test files
  and a `conftest`-free runner config; turned into tar archives for the loader container.
- **Verdict**: `(status, reason, detail)` computed by R5 before the gate writes anything.
