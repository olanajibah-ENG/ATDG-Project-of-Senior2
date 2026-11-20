# Data Model: S2 — Unit Test Generation

## New: `test_records` (one document per work item)

Created when planning finishes: one per (planned unit, requested level).

| Field | Type | Notes |
|-------|------|-------|
| `record_id` | string | `t_` + 10 hex characters; unique; used in URLs and responses |
| `job_id` | string | the job it belongs to |
| `unit_id` | string | `path::Class.method` or `path::function` |
| `file` | string | the unit's file path |
| `level` | string | `unit`, `edge` or `integration` |
| `status` | string | `pending`, `generated`, `generation_failed` in this slice |
| `reason_code` | string or null | set when `generation_failed`: `no_code`, `syntax_error`, `forbidden_import`, `unsafe_code`, `weak_test` |
| `reason_detail` | string or null | one readable line, for example the forbidden module name |
| `test_path` | string or null | `tests/generated/test_<file>_<unit>__unit.py`, set when `generated` |
| `test_code` | string or null | the checked test text, set when `generated`; never returned by the list route |
| `body_hash` | string | fingerprint of the unit body the test was written for |
| `model` | string or null | the model that produced the answer |
| `prompt_version` | string or null | for example `unit-v1` |
| `reused` | bool | true when the answer came from an earlier attempt |
| `created_at`, `updated_at` | datetime | UTC |

Indexes: unique on `record_id`; on (`job_id`, `level`, `status`).

Record statuses of the whole feature: `pending`, `generated`, `ready`, `skipped`,
`generation_failed`, `test_failed`, `environment_error`. `ready`, `test_failed` and
`environment_error` are not produced before the sandbox slice.

## New: `test_attempts` (one document per model request, or per reuse)

| Field | Type | Notes |
|-------|------|-------|
| `attempt_id` | string | `a_` + 10 hex characters |
| `job_id`, `record_id`, `unit_id`, `level` | string | what the request served |
| `purpose` | string | `generate` (repair arrives in S4) |
| `prompt_version` | string | version label of the instructions |
| `request_hash` | string | SHA-256 of prompt version + context; the key for reuse |
| `reused` | bool | true when no request was sent and an earlier answer was used |
| `model` | string or null | the model that answered |
| `prompt_tokens`, `completion_tokens` | int | 0 when reused or when the request failed |
| `duration_ms` | int | time spent waiting for the model |
| `outcome` | string | `answered`, `model_unavailable` |
| `answer_text` | string or null | the raw answer, kept so it can be reused |
| `validation` | object or null | `{ok, reason_code, reason_detail}` after the checks |
| `created_at` | datetime | UTC |

Index: on `request_hash`.

## Changed: `test_jobs`

| Field | Change |
|-------|--------|
| `status` | `completed_with_issues` is now produced |
| `stage` | new value `generating`, between `planning` and the final stage; final stage is `generated` when the unit level was requested, `planned` otherwise |
| `error` | also set when generation stopped early: `{code: "model_unavailable" or "request_limit_reached", message}` with status `completed_with_issues` |
| `llm_requests` | new, int: model requests spent by this job (reuses do not count) |
| `plan.units[].externals` | new, list of external names the unit calls, without Python builtins |
| `progress.by_status` | new key `generated`; counters are computed from the records |
| `progress.done` | number of records that are no longer `pending` |

### Status and stage transitions

```text
stage:   queued → planning (→ waiting_analysis → planning) → generating → generated
status:  pending → running → completed
                         ├─► completed_with_issues   (a unit failed, or generation stopped early)
                         └─► failed                  (no file analysed, or the worker never ran it)
```

## In memory only: unit context

Built for one unit, sent to the model as JSON inside the prompt, and not stored. Its hash is.

```json
{
  "kind": "unit",
  "unit": {
    "id": "game.py::Student.enroll",
    "name": "enroll",
    "import_statement": "from game import Student",
    "signature": "enroll(course: Course): bool",
    "parameters": [{"name": "course", "type": "Course", "default": null}],
    "return_type": "bool",
    "decorators": [],
    "docstring": null,
    "body": "if len(self.courses) >= 5: ..."
  },
  "class": {
    "name": "Student",
    "bases": ["Person"],
    "constructor": "__init__(name: str, id_number: int, major: str)",
    "attributes": [{"name": "major", "type": "str"}]
  },
  "callees": [
    {"id": "game.py::Course.add_student", "signature": "add_student(student: Student): Any",
     "import_statement": "from game import Course"}
  ],
  "externals": [],
  "rules": {"framework": "pytest", "test_name": "test_Student_enroll__unit_<n>"}
}
```

`class` is null for a function outside a class. No field holds the body of another unit.
