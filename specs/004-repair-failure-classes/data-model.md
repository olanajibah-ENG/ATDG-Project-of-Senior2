# Data Model: S4

Fields are **added** to existing documents; nothing is renamed or removed.

## `test_jobs` (changed)

| Field               | Type         | Notes                                                                                                                                                                                                                      |
| ------------------- | ------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `stage`             | str          | + `preflight`, `repairing`, `flaky_check`                                                                                                                                                                                  |
| `progress.repaired` | int          | records that became `ready` through a repair                                                                                                                                                                               |
| `llm_requests`      | int          | unchanged field; now counts generation **and** repair requests (limit 30)                                                                                                                                                  |
| `preflight`         | dict \| null | `{env_key, status: skipped\|reused\|installed\|failed, volume, detail, duration_s, warnings: [str], install_tries: 0\|1\|2, probe: {modules: [str], missing: [str], import_failed: [{module, error}], not_probed: [str]}}` |
| `flaky`             | dict \| null | `{status: done\|inconclusive, runs: [run_id, …], removed: [record_id], reason}`                                                                                                                                            |
| `notices`           | list[str]    | job-level notices, e.g. `flaky_check_inconclusive`, `preflight_warnings`                                                                                                                                                   |
| `snapshot_id`       | str \| null  | the job's coverage snapshot                                                                                                                                                                                                |

Job stage order: `queued → waiting_analysis → planning → planned → preflight → generating →
sandbox_run ⇄ repairing → final_run → flaky_check → (final_run) → finished`.

## `test_records` (changed)

| Field                           | Type         | Notes                                                                                                                          |
| ------------------------------- | ------------ | ------------------------------------------------------------------------------------------------------------------------------ |
| `attempts`                      | list         | one item per write, see below                                                                                                  |
| `attempts_used`                 | int          | repair writes so far (0..2)                                                                                                    |
| `reason_code`                   | str          | + `suspected_code_bug`, `flaky`, `repair_budget_exhausted`, `run_timeout`, `out_of_memory`, `install_failed`, `import_failed`  |
| `explanation`                   | dict \| null | for `suspected_code_bug`: `{location, expected, explanation}`                                                                  |
| `fwo_repaired`                  | bool         | `fails_with_others` already repaired once                                                                                      |
| `last_rejection`                | dict \| null | `{rule, detail, code}` of the last rejected repair candidate; sent in the next repair request, cleared after a written attempt |
| `run_result.tests[].error_type` | str \| null  | e.g. `AssertionError`, `ImportError`, `Timeout`                                                                                |
| `evidence.repaired`             | bool         | set by the acceptance gate                                                                                                     |
| `evidence.attempt`              | int          | 1 = first generation, 2–3 = repairs                                                                                            |

`attempts[]` item:

```json
{
  "n": 2,
  "purpose": "repair",
  "attempt_id": "a_…",
  "run_id": "r_… (filled by update_attempt when the run ends)",
  "outcome": "written|ready|test_failed|environment_error|invalid|guard_violation|suspect_code|duplicate",
  "cause": "assertion",
  "test_sha256": "…",
  "changed_assertions": [
    {
      "kind": "changed",
      "test": "test_total__unit_1",
      "index": 0,
      "before": "5",
      "after": "7"
    },
    { "kind": "added", "test": "test_total__unit_2", "after": "[]" }
  ],
  "rejection": "guard:mocks_unit — patches pkg.calc.total",
  "created_at": "…"
}
```

`outcome` is `written` when the attempt is stored; `update_attempt()` sets the final value and
`run_id` when its run ends (or `invalid` / `guard_violation` / `duplicate` / `suspect_code` at once).

### Status transitions

See research R2. Enforced by `RecordRepo.transition()`; any other change raises `IllegalTransition`.

## `test_attempts` (changed)

| Field                    | Notes                                                            |
| ------------------------ | ---------------------------------------------------------------- |
| `purpose`                | `generate` \| `repair`                                           |
| `prompt_version`         | + `repair-v1`                                                    |
| `repair_of`              | `{cause, previous_attempt_id, previous_test_sha256}` for repairs |
| `verdict`                | `fix_test` \| `suspect_code` \| null                             |
| `validation.reason_code` | + `guard:<rule>`                                                 |

## `test_coverage_snapshots` (new, append-only)

```json
{
  "snapshot_id": "s_…",
  "project_id": "…",
  "version_number": 3,
  "job_id": "j_…",
  "source": "manual",
  "partial": false,
  "line_pct": 82.5,
  "branch_pct": 70.0,
  "files": [
    {
      "file": "pkg/a.py",
      "line_pct": 90.0,
      "branch_pct": 75.0,
      "statements": 40,
      "covered": 36,
      "branches": 8,
      "branches_covered": 6
    }
  ],
  "final_run_id": "r_…",
  "created_at": "…"
}
```

Indexes: unique `job_id`; `(project_id, version_number, source, created_at)`. Note for F3: F3's table
asks for uniqueness on `(project, version(+commit), source)`; S4 writes one snapshot per job, so two
manual jobs on the same version give two snapshots. F3 must pick the latest per version (or add that
unique key and an upsert rule) — decided in F3, not here. The repo exposes
`add()` and readers only.

## `test_envs` (new)

```json
{
  "env_key": "…",
  "status": "building|ready|failed|failed_temporary",
  "volume": "sbx_env_…",
  "python_version": "3.10",
  "manifests": [{ "path": "requirements.txt", "sha256": "…" }],
  "owner_job": "j_…",
  "started_at": "…",
  "finished_at": "…",
  "last_used_at": "…",
  "size_bytes": 12345678,
  "detail": "pip tail…"
}
```

Index: unique `env_key`. `failed` = definite failure, reused for 1 hour; `failed_temporary` is never
reused. `reap()` deletes entries (and volumes) unused for 7 days.

## `code_files` (changed at upload)

Support files (`requirements*.txt`, `pyproject.toml`, `setup.cfg`, `pytest.ini`, `conftest.py`) are
stored with `file_type: "support"` and `analysis_status: "NOT_ANALYSED"`.

## Bundle `records_summary.json` (changed)

Per record adds `attempts` (`n, purpose, outcome, cause`), `changed_assertions` (all attempts, for
review), `explanation` (when present). Records not
`ready` appear only here; `tests/generated/…` contains `ready` tests only (unchanged rule).
