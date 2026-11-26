# API contract changes — S4

No new route. Existing routes under `/api/analysis/tests/` keep their paths, auth (JWT, creator only)
and error shape `{"error": {"code", "message", "details"}}`. Only fields are added.

## `GET jobs/{job_id}/`

```json
{
  "stage": "preflight | generating | sandbox_run | repairing | final_run | flaky_check | …",
  "progress": { "…": "…", "repaired": 1 },
  "llm_requests": 7,
  "preflight": {
    "status": "installed",
    "env_key": "3f…",
    "detail": null,
    "warnings": ["dropped line: -e ."],
    "install_tries": 1,
    "probe": {
      "modules": ["requests", "cv2"],
      "missing": ["requests"],
      "import_failed": [
        { "module": "cv2", "error": "ImportError: libGL.so.1: …" }
      ],
      "not_probed": []
    }
  },
  "flaky": { "status": "done", "removed": [] },
  "notices": ["flaky_check_inconclusive"],
  "snapshot_id": "s_…"
}
```

`notices` is always present (empty list when nothing to report).

## `GET jobs/{job_id}/records/` (list items)

Adds `attempts_used` and, when relevant, `reason_code` values `suspected_code_bug`, `flaky`,
`repair_budget_exhausted`, `run_timeout`, `out_of_memory`, `install_failed`, `import_failed`.

## `GET jobs/{job_id}/records/{record_id}/`

```json
{
  "attempts": [
    {
      "n": 1,
      "purpose": "generate",
      "outcome": "test_failed",
      "cause": "assertion",
      "run_id": "r_1"
    },
    {
      "n": 2,
      "purpose": "repair",
      "outcome": "ready",
      "cause": "assertion",
      "run_id": "r_2",
      "changed_assertions": [
        {
          "kind": "changed",
          "test": "test_total__unit_1",
          "index": 0,
          "before": "5",
          "after": "7"
        }
      ]
    },
    {
      "n": 3,
      "purpose": "repair",
      "outcome": "suspect_code",
      "cause": "assertion",
      "run_id": null
    }
  ],
  "explanation": {
    "location": "pkg/calc.py:14 (else branch)",
    "expected": "returns 0 for an empty list (docstring)",
    "explanation": "the code returns None"
  },
  "run_result": {
    "tests": [
      {
        "name": "…",
        "outcome": "failed",
        "error_type": "AssertionError",
        "message": "…"
      }
    ]
  },
  "evidence": { "…": "…", "repaired": true, "attempt": 2 }
}
```

## `GET jobs/{job_id}/coverage/`

Unchanged shape. Now comes from the last all-pass final run after the flaky check.

## `GET jobs/{job_id}/bundle/`

Unchanged layout. `records_summary.json` items add `attempts`, `changed_assertions` and `explanation`.
