# API Contract: S1 — Test Job and Plan

Base: `/api/analysis/tests/` (reachable through nginx on port 80, or directly on the AI service).

Every route needs `Authorization: Bearer <access token from UPM login>`.

## Common error body

```json
{ "error": { "code": "<code>", "message": "<readable text>", "details": { } } }
```

| HTTP | `code` | When |
|------|--------|------|
| 400 | `validation_error` | a field is missing, malformed or names something that does not exist |
| 401 | `unauthorized` | no token, a malformed token, an expired token, or a wrong signature |
| 403 | `forbidden` | the job belongs to another user |
| 404 | `not_found` | no job with that id |
| 409 | `plan_not_ready` | the plan was requested before the first planning pass finished |
| 422 | `no_python_files` | the selection contains no Python file |

`409 analysis_missing` from the API document is not returned: the job requests a missing analysis
itself (owner's decision, 2026-11-13).

---

## 1. Start a job

`POST /api/analysis/tests/jobs/`

### Request

```json
{
  "project_id": "3f2b6c1e-8a4d-4c0b-9d57-1e2a7f6b9c10",
  "version_number": 2,
  "paths": ["MyProject/utils.py", "MyProject/main.py"],
  "levels": ["unit", "edge", "integration"]
}
```

| Field | Required | Rule |
|-------|----------|------|
| `project_id` | yes | UPM project UUID; a project with no uploaded version → 400 |
| `version_number` | no | positive integer; omitted → latest version; unknown → 400 |
| `paths` | no | file paths as shown by the project tree; omitted or `[]` → all files of the version; an unknown path → 400, with the unknown paths in `details.paths` |
| `levels` | no | any of `unit`, `edge`, `integration`, no duplicates; omitted → all three; anything else → 400 |

The body never carries file content.

### Response `202 Accepted`

```json
{
  "job_id": "job_7f3a91c2d4e5",
  "status": "pending",
  "project_id": "3f2b6c1e-8a4d-4c0b-9d57-1e2a7f6b9c10",
  "version_number": 2
}
```

Errors: 400 `validation_error`, 401 `unauthorized`, 422 `no_python_files`.

---

## 2. Job status

`GET /api/analysis/tests/jobs/{job_id}/`

Meant to be polled about every 2 seconds.

### Response `200 OK`

```json
{
  "job_id": "job_7f3a91c2d4e5",
  "project_id": "3f2b6c1e-8a4d-4c0b-9d57-1e2a7f6b9c10",
  "version_number": 2,
  "status": "completed",
  "stage": "planned",
  "progress": {
    "total": 42,
    "done": 0,
    "by_status": {"pending": 42, "ready": 0, "skipped": 1,
                  "generation_failed": 0, "test_failed": 0, "environment_error": 0}
  },
  "files": [
    {"path": "MyProject/game.py", "status": "pending"},
    {"path": "MyProject/app.js", "status": "skipped", "reason": "unsupported_language"}
  ],
  "error": null
}
```

| Field | Values in S1 |
|-------|--------------|
| `status` | `pending`, `running`, `completed`, `failed` |
| `stage` | `queued`, `waiting_analysis`, `planning`, `planned` |
| `files[].status` | `pending`, `skipped` |
| `files[].reason` | present only when skipped: `unsupported_language`, `analysis_failed`, `no_units` |
| `error` | `null`, or `{"code": "...", "message": "..."}` when `status` is `failed` |

Error codes of a failed job:

| `error.code` | Meaning |
|--------------|---------|
| `analysis_failed` | no selected Python file could be analysed |
| `worker_unavailable` | the background worker never ran the job, or the job stopped making progress |

A job is never left `pending` forever. If it is still `queued` 120 seconds after it was created, or
`running` with no change for 720 seconds, the next read of the job reports it as `failed` with
`worker_unavailable`. Start a new job after the worker is back.

Errors: 401 `unauthorized`, 403 `forbidden`, 404 `not_found`.

---

## 3. Plan

`GET /api/analysis/tests/jobs/{job_id}/plan/`

### Response `200 OK`

```json
{
  "units": [
    {"id": "MyProject/game.py::Student.enroll", "file": "MyProject/game.py", "kind": "method"},
    {"id": "MyProject/utils.py::slugify", "file": "MyProject/utils.py", "kind": "function"}
  ],
  "skipped": [
    {"path": "MyProject/app.js", "reason": "unsupported_language"},
    {"path": "MyProject/utils.py", "unit": "MyProject/utils.py::_clean", "reason": "private"}
  ],
  "work_items_count": 6
}
```

| Field | Meaning |
|-------|---------|
| `units[].id` | `filepath::Class.method` or `filepath::function` |
| `units[].kind` | `method` or `function` |
| `skipped[]` | a skipped file has `path` and `reason`; a skipped unit also has `unit` |
| `work_items_count` | number of units × number of requested levels |

While files are still waiting for analysis the plan is partial: it lists what is planned so far,
and the job's `stage` is not yet `planned`.

Errors: 401 `unauthorized`, 403 `forbidden`, 404 `not_found`, 409 `plan_not_ready` (also returned,
with a message saying so, when the job failed before any plan was built).
