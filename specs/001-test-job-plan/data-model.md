# Data Model: S1 — Test Job and Plan

## New: `test_jobs` (one document per job)

| Field | Type | Notes |
|-------|------|-------|
| `_id` | ObjectId | internal |
| `job_id` | string | `job_` + 12 hex characters; unique; used in URLs and responses |
| `user_id` | string | from the token's `user_id` claim; the only reader of this job |
| `project_id` | string | UPM project UUID |
| `version_number` | int | resolved at creation (latest when the request omitted it) |
| `paths` | list of string | as requested; empty means "all files of the version" |
| `levels` | list of string | subset of `unit`, `edge`, `integration`; stored for later slices |
| `status` | string | `pending` → `running` → `completed` or `failed` |
| `stage` | string | `queued` → `waiting_analysis` or `planning` → `planned` |
| `files` | list of object | one entry per selected file (see below) |
| `plan` | object or null | see below; null until the first pass has planned something |
| `progress` | object | `{total, done, by_status}` (see below) |
| `gate` | object | `{deadline_at, passes}` — bookkeeping for the analysis gate |
| `error` | object or null | `{code, message}` when `status` is `failed` |
| `created_at`, `updated_at` | datetime | UTC |

Index: unique on `job_id`.

### `files[]` entry

| Field | Type | Notes |
|-------|------|-------|
| `path` | string | the file's `filepath` |
| `file_id` | string | the `code_files` id (internal; not returned by the API) |
| `status` | string | `pending` (waiting or planned), `skipped` |
| `reason` | string or null | a skip reason code when `status` is `skipped` |
| `analysis_requests` | int | how many times this job requested analysis (0 to 2); internal |

In S1 a file is `pending` while it waits for analysis and stays `pending` once planned, because
none of its tests exist yet. `ready`, `partial` and `failed` arrive with later slices.

### `plan` object

| Field | Type | Notes |
|-------|------|-------|
| `units` | list | `{id, file, kind, body_hash}` — `kind` is `function` or `method`; `body_hash` is internal |
| `skipped` | list | `{path, reason}` for a file, `{path, unit, reason}` for a unit |
| `work_items_count` | int | number of units × number of requested levels |

### `progress` object

```json
{ "total": 42, "done": 0,
  "by_status": {"pending": 42, "ready": 0, "skipped": 0,
                "generation_failed": 0, "test_failed": 0, "environment_error": 0} }
```

`total` is the work-item count. `by_status.skipped` counts skipped files and units. `done` stays 0
in S1.

### Status and stage transitions

```text
status:  pending ──► running ──► completed
                         └─────► failed          (scope lost, or no file could be analysed)

stage:   queued ──► planning ──► planned
            └────► waiting_analysis ──► planning ──► planned
```

`completed_with_issues` and `cancelled` are valid job statuses of the API but are not produced in
S1.

### Skip reason codes

`unsupported_language`, `analysis_failed`, `no_units`, `empty_or_abstract`, `body_truncated`,
`private`.

## Read-only: existing collections

Nothing below is written by this slice.

### `project_versions`

| Field used | Purpose |
|------------|---------|
| `project_id` | find the project's versions |
| `version_number` | resolve the requested or the latest version |
| `file_ids` | the files that make up that version (includes files unchanged since earlier versions) |

### `code_files`

| Field used | Purpose |
|------------|---------|
| `_id` | file id |
| `filepath` | matched against the request's `paths`; first part of unit ids |
| `file_type` | `python` or not |
| `analysis_status` | `PENDING`, `IN_PROGRESS`, `COMPLETED`, `FAILED` — read by the gate |
| `analysis_id` | the file's analysis result |

### `analysis_results`

| Field used | Purpose |
|------------|---------|
| `code_file_id`, `status` | locate the completed result of a file |
| `dependency_graph` | stored graph: `nodes`, `edges`, `meta` |
| `class_diagram_data.classes[]` | `name`, `base_classes`, `methods[]` |
| `class_diagram_data.classes[].methods[]` | `name`, `parameters` (name, type), `decorators`, `is_abstract`, `body`, `body_hash`, `body_truncated` |
| `class_diagram_data.module_functions[]` | the same fields, for functions outside classes |
| `ast_structure.ast_tree.body` | top-level `Import` and `ImportFrom` nodes only, for cross-file resolution |

## In memory only: project graph

Built on each pass, not stored.

| Part | Shape |
|------|-------|
| node | `{id, label, type, local, file, parent?}` — `type` is `module`, `class`, `method`, `function` or `external` |
| edge | `{from, to, relation, confidence}` — `relation` is `imports`, `inherits` or `calls` |
| meta | `{total_nodes, total_edges, source: "merged", files: [...]}` |

Local ids are `filepath::Name`. External ids are `ext.name`.
