# Research: S1 — Test Job and Plan

Decisions taken from reading the existing code. Each one names what was chosen, why, and what was
set aside.

## R1. Checking the user token

**Finding**: UPM signs tokens with HS256 and its own `SECRET_KEY`. Tokens carry `user_id`,
`role_type` and `full_name`. The AI service has a different `SECRET_KEY`, no `SIMPLE_JWT`
settings, and its views set `AllowAny`. The AI service has no table of UPM users.

**Decision**: `core_testing/auth.py` holds a small DRF authentication class that decodes the
`Authorization: Bearer <token>` header with simplejwt's `TokenBackend`, using a dedicated setting
`CORE_TESTING_JWT_SIGNING_KEY`. It accepts only `token_type == "access"`, and returns a light user
object built from the claims, with no database lookup. docker compose passes the UPM key to
`ai_web` as `UPM_JWT_SIGNING_KEY`. If the setting is empty, every test route answers 401.

**Why**: it is the smallest safe change. It does not touch global `SIMPLE_JWT`, so the behaviour
of every existing AI route stays exactly as it is.

**Set aside**: (a) global `SIMPLE_JWT` plus `JWTStatelessUserAuthentication` — changes the default
authenticator for the whole service; (b) leaving routes `AllowAny` and trusting the gateway — the
routes are reachable directly on port 8002; (c) asking UPM to verify each token over HTTP — an
extra call and a new UPM endpoint for no gain in this slice.

**Known gap, stated on purpose**: S1 checks that the caller is a signed-in user and that a job is
read only by its creator. It does not check that the user is a member of the project. That check
needs a UPM internal endpoint and is scheduled before the multi-user demo.

## R2. Background work and the analysis gate

**Finding**: `analyze_project_task` waits on subtasks with `task.get(timeout=600)`. Upload already
triggers `analyze_code_file_task` for every file. Completion is visible on the file document:
`analysis_status` moves `PENDING → IN_PROGRESS → COMPLETED | FAILED`, and `analysis_id` is set on
success.

**Decision**: one Celery task, `core_testing.tasks.advance_job(job_id)`, runs a single short pass
and returns. If some file is still waiting, the task re-enqueues itself with
`apply_async(countdown=CORE_TESTING_GATE_POLL_SECONDS)`. It never calls `.get()` on anything.
A missing analysis is requested with `analyze_code_file_task.delay(file_id)` and not awaited.
The job stores, per file, how many times it requested analysis (maximum 2) and one deadline for
the whole gate (`CORE_TESTING_GATE_MAX_WAIT_SECONDS`, default 600).

Gate rules per selected Python file:

| File state | Action |
|------------|--------|
| `COMPLETED` with an analysis result | ready |
| `PENDING` or `IN_PROGRESS` | wait |
| `FAILED`, or no result, and fewer than 2 requests made by this job | request analysis, wait |
| `FAILED` after 2 requests | skipped, `analysis_failed` |
| still not complete at the deadline | skipped, `analysis_failed` |

Each pass rebuilds the plan from all files that are ready. It is cheap, and it makes a pass
idempotent: running it twice gives the same job.

**Why**: polling by re-enqueue is the pattern that cannot deadlock the worker, and it is what the
overview document asks for.

**Set aside**: a Celery chord or group over analysis tasks (ties our job to the internals of the
analysis task); a dedicated queue and worker (not needed until the sandbox slice).

## R3. Storage and how it is tested

**Decision**: one collection, `test_jobs`, with the plan stored inside the job document. Access
goes through two small interfaces:

- `JobRepo` — create, get, update a job. `MongoJobRepo` for the service, `InMemoryJobRepo` for
  tests.
- `AnalysisReader` — read-only: latest version of a project, files of a version, analysis result
  of a file. `MongoAnalysisReader` for the service, `InMemoryAnalysisReader` for tests.

**Why**: the test container runs with no database. With these two interfaces every rule in the
slice is tested without Mongo, and the Mongo classes stay a few lines each. Real Mongo behaviour
is exercised in the acceptance run through Postman.

**Set aside**: separate `test_units` and `test_records` collections now (nothing reads them before
S2); `mongomock` (a new dependency for a problem the interface already solves).

## R4. Building the project graph

**Finding**: each analysis result stores `dependency_graph` (nodes / edges / meta) and
`class_diagram_data` (every method with its parameters, types, decorators and body). On the
sample file the stored graph reports `course.add_student(self)` as `ext.course.add_student`,
`super().__init__` as `ext.super`, and uses ids such as `Student.enroll` and `__module__` that
repeat across files.

**Decision**: a thin layer in `core_testing/graphify/`, in four steps:

1. `loader` reads, for one file, the stored graph, the unit list from `class_diagram_data`, and
   the top-level imports from the stored AST.
2. `merge` rewrites local ids to `filepath::Name` (`filepath::Class.method`,
   `filepath::function`, `filepath::__module__`) and joins the file graphs. External ids keep the
   form `ext.name` and are shared across files.
3. `resolver` re-points call edges that the stored graph left as external or dangling. It parses
   each unit's stored body with Python's `ast` and resolves, in order: `self.m()` through the
   class and its bases; `super().m()` to the parent class; `param.m()` through the parameter's
   type annotation; `Name()` to a local function or a local class constructor; an imported name
   to the unit in the other project file.
4. `queries.callees(unit_id)` returns the local units a unit calls directly.

The stored graph in `analysis_results` is never written back, so the explanation prompt sees
exactly what it saw before.

**Why**: it uses what analysis already stores, fixes the four gaps that block testing, and leaves
the analyser alone.

**Set aside**: changing the processors (breaks the "do not rewrite the analyser in S1" rule and
risks conflict detection); building a second, independent graph from source (two graphs to keep
in agreement).

**Limits accepted in S1**: no builtins category, no confidence tiers, no `io_kind`, no cache.
A unit whose stored body was truncated cannot be parsed; its stored edges are kept as they are.

## R5. Unit inventory and skip rules

**Decision**: units come from `class_diagram_data.classes[].methods[]` and
`class_diagram_data.module_functions[]`. Rules, applied in this order:

| Level | Condition | Result |
|-------|-----------|--------|
| file | `file_type` is not `python` | skipped, `unsupported_language` |
| file | gate gave up | skipped, `analysis_failed` |
| file | no function and no method | skipped, `no_units` |
| unit | name starts with `_` and is not a `__dunder__` | skipped, `private` |
| unit | abstract, or body is only `pass`, `...` or a docstring | skipped, `empty_or_abstract` |
| unit | `body_truncated` is true | skipped, `body_truncated` |
| unit | otherwise | planned, kind `method` or `function` |

`__init__` and other dunder methods are units. Nested functions are not listed by analysis and so
are not units.

## R6. Identifiers

- Job id: `job_` followed by 12 hexadecimal characters, generated by the service. It is the id in
  URLs and responses. The Mongo `_id` stays internal.
- Unit id: `filepath::Class.method` or `filepath::function`, where `filepath` is the file's path
  as stored at upload and shown in the project tree.
- Project id: the UPM project UUID, as a string. The API document's example shows a number; the
  code uses a UUID, and the code wins.

## R7. Test setup

**Finding**: the existing tests run with plain pytest and never call `django.setup()`. Importing
DRF views or simplejwt needs the app registry.

**Decision**: `core_testing/tests/conftest.py` calls `django.setup()` once, blocks
`LLMClient.call_model` for every test, and provides the in-memory repo and reader. Views are
called with DRF's `APIRequestFactory`. Stored-analysis fixtures are produced by running the real
`PythonProcessor` on small source files kept under `tests/fixtures/sources/`, so the fixtures
cannot drift from what analysis really stores.

## R8. Error body

The API document names error codes but not the body. One shape is used for every error:

```json
{ "error": { "code": "validation_error", "message": "unknown path", "details": {"paths": ["x.py"]} } }
```

## R9. Proving that no LLM is called

Two automated checks: a static test that no module under `core_testing/` imports the LLM client,
and a run of a full job with `LLMClient.call_model` replaced by a function that raises.

## R10. Where the code lives

**Decision** (owner, 2026-11-13): Feature 1 is a Django app of its own, `core_testing`, inside
the existing AI service and beside `core_ai`. It is not a new microservice: same container, same
MongoDB, same Celery and Redis, same gateway prefix `/api/analysis/`.

**Why**: this feature is the largest of the three (sandbox, extra workers, several collections,
a repair loop). An app of its own gives it a boundary that the folder structure enforces, keeps
teammates from editing the same shared files in `core_ai`, and matches the overview document,
the API document and the backend lead's brief.

**Set aside**: building it inside `core_ai` with the layout of conflict detection
(`services/test_generation/`, `views/testgen_views.py`, and so on). It is consistent with the
other two features, but the boundary would rest on discipline alone, the whole team would edit
`core_ai/urls.py`, and files would need a `testgen_` prefix so pytest does not collect them.

**Dependency rules that keep the boundary real**:

1. `core_testing` reads what `core_ai` stores and may call its analysis task.
2. `core_testing` imports nothing from conflict detection or the explanation engine.
3. Nothing in `core_ai` imports from `core_testing`.
4. Only `core_testing` writes to the `test_*` collections.
