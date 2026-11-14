# API Contract: S2 — Unit Test Generation

Base: `/api/analysis/tests/`. Every route needs `Authorization: Bearer <access token from UPM>`.
The common error body and the error codes of S1 still apply.

## Changes to the S1 routes

### `POST jobs/` — unchanged

The job now continues into generation by itself when `unit` is among the requested levels.

### `GET jobs/{job_id}/` — more values

```json
{
  "job_id": "job_7f3a91c2d4e5",
  "project_id": "task_test",
  "version_number": 1,
  "status": "completed_with_issues",
  "stage": "generated",
  "progress": {
    "total": 27,
    "done": 9,
    "by_status": {"pending": 18, "generated": 8, "ready": 0, "skipped": 0,
                  "generation_failed": 1, "test_failed": 0, "environment_error": 0}
  },
  "files": [
    {"path": "task.py", "status": "partial",
     "levels": {"unit": "partial", "edge": "pending", "integration": "pending"}}
  ],
  "error": null
}
```

| Field | Values now |
|-------|------------|
| `status` | `pending`, `running`, `completed`, `completed_with_issues`, `failed` |
| `stage` | `queued`, `waiting_analysis`, `planning`, `generating`, `generated`, `planned` |
| `progress.by_status` | new key `generated` |
| `progress.done` | records that are no longer `pending` |
| `files[].status` | `pending` (nothing generated yet), `generated` (every unit record of the file is generated), `partial` (some are, or some failed), `failed` (every unit record failed), `skipped` |
| `files[].levels` | per requested level: `pending`, `generated`, `partial`, `failed` |
| `error` | also set, with status `completed_with_issues`, when generation stopped early |

`error.code` when generation stopped early:

| Code | Meaning |
|------|---------|
| `model_unavailable` | the language model could not be reached, or its quota is used up |
| `request_limit_reached` | the job spent its request limit (20 by default) |

In both cases the remaining unit records are still `pending`. Start a new job later: answers
already obtained are reused without a new request.

### `GET jobs/{job_id}/plan/` — unchanged

---

## New: list the records of a job

`GET /api/analysis/tests/jobs/{job_id}/records/`

Query parameters, all optional: `status`, `path`, `level`.

### Response `200 OK`

```json
{
  "items": [
    {
      "id": "t_91c2d4e5a0",
      "file": "task.py",
      "unit_id": "task.py::Car.drive",
      "level": "unit",
      "status": "generated",
      "reason_code": null,
      "test_path": "tests/generated/test_task_Car_drive__unit.py"
    },
    {
      "id": "t_0b7e11f3c2",
      "file": "task.py",
      "unit_id": "task.py::GPS.locate",
      "level": "unit",
      "status": "generation_failed",
      "reason_code": "weak_test",
      "test_path": null
    }
  ],
  "total": 2
}
```

The list never carries test code. An unknown `status` or `level` value → 400 `validation_error`.
Before planning has finished there are no records yet: `{"items": [], "total": 0}`.

Errors: 400 `validation_error`, 401 `unauthorized`, 403 `forbidden`, 404 `not_found`.

---

## New: read one record

`GET /api/analysis/tests/jobs/{job_id}/records/{record_id}/`

### Response `200 OK`

```json
{
  "id": "t_91c2d4e5a0",
  "file": "task.py",
  "unit_id": "task.py::Car.drive",
  "level": "unit",
  "status": "generated",
  "reason_code": null,
  "reason_detail": null,
  "test_path": "tests/generated/test_task_Car_drive__unit.py",
  "test_code": "import pytest\nfrom task import Car\n\n\ndef test_Car_drive__unit_1():\n    ...",
  "executed": false,
  "notice": "This test was generated and checked for form only. It has not been run.",
  "model": "google/gemma-4-31b-it:free",
  "prompt_version": "unit-v1"
}
```

`test_code` is null unless the record is `generated`. `executed` is always false in this slice.

Errors: 401 `unauthorized`, 403 `forbidden`, 404 `not_found` (unknown job, or a record that does
not belong to that job).

## Reason codes of `generation_failed`

| Code | Meaning |
|------|---------|
| `no_code` | the model's answer held no code |
| `syntax_error` | the code does not parse |
| `forbidden_import` | it imports something outside the standard library, pytest and the project |
| `unsafe_code` | it uses the network, a process, `eval`/`exec`, sleep, or writes outside a temporary directory |
| `weak_test` | no test function, a test with no check, or a test that never calls the unit |
