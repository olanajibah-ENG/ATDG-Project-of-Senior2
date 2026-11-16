---

description: "Task list for S1 — Test Job and Plan (no LLM)"
---

# Tasks: S1 — Test Job and Plan (no LLM)

**Input**: Design documents from `/specs/001-test-job-plan/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/api.md, quickstart.md

**Tests**: included. The constitution requires every slice to ship tests for its own code, and
the tests of a story are written before its implementation.

**Organization**: tasks are grouped by user story so each story can be implemented and checked on
its own.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: the user story the task belongs to (US1, US2, US3)
- Every task names the exact file it touches

## Path Conventions

- New code: `Ai_project/core_ai/services/test_generation/`
- Its tests: `Ai_project/core_ai/tests/test_generation/`
- Paths are relative to the repository root
- Tests run inside the `ai_web` image (see quickstart.md), never with the local Python

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: the app exists, is registered, and its tests can run

- [x] T001 Create the app skeleton: `Ai_project/core_ai/services/test_generation/__init__.py`, `Ai_project/core_ai/services/test_generation/apps.py` (`CoreTestingConfig`, `name = "core_testing"`), and empty packages `Ai_project/core_ai/services/test_generation/graphify/__init__.py`, `Ai_project/core_ai/services/test_generation/languages/__init__.py`, `Ai_project/core_ai/tests/test_generation/__init__.py`
- [x] T002 Register the app and add settings in `Ai_project/Ai_project/settings.py`: `'core_testing'` in `INSTALLED_APPS`; `TEST_JOBS_COLLECTION = 'test_jobs'`; `TESTGEN_JWT_SIGNING_KEY = os.environ.get('UPM_JWT_SIGNING_KEY', '')`; `TESTGEN_GATE_POLL_SECONDS = 5`; `TESTGEN_GATE_MAX_WAIT_SECONDS = 600`
- [x] T003 [P] Pass the UPM signing key to the AI service: add `UPM_JWT_SIGNING_KEY=${UPM_DJANGO_SECRET_KEY}` to the `ai_web` environment in `docker-compose.yml`
- [x] T004 [P] Add sample sources under `Ai_project/core_ai/tests/test_generation/fixtures/sources/`: `game.py` (the university sample: 6 classes, 14 methods), `shop/models.py` + `shop/service.py` (a two-file project where `service.py` imports a class from `models.py` and calls its method), `edge_cases.py` (a private function `_helper`, an abstract method, a function whose body is `pass`, a function whose body is only a docstring, a module with a top-level function), `no_units.py` (constants only)
- [x] T005 Create `Ai_project/core_ai/tests/test_generation/helpers.py`: `build_analysis(source: str) -> dict` runs the real `PythonProcessor` (`parse_source_code`, `extract_features`, `generate_class_diagram_data`, `generate_dependency_graph_data`, `extract_dependencies`) and returns a dict shaped like an `analysis_results` document (`status`, `ast_structure`, `dependency_graph`, `class_diagram_data`, `dependencies`); `load_source(name)` reads a fixture file
- [x] T006 Create `Ai_project/core_ai/tests/test_generation/conftest.py`: call `django.setup()` once at import; autouse fixture that replaces `LLMClient.call_model` with a function that raises; fixtures `repo` (in-memory job repo), `reader` (in-memory analysis reader) and `make_project(files: dict[path, source], *, statuses=None)` that fills the reader with one project version built through `helpers.build_analysis`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: what every story needs — statuses, errors, storage, readers, token check

**⚠️ CRITICAL**: no user story work starts before this phase is complete

- [x] T007 [P] Create `Ai_project/core_ai/services/test_generation/statuses.py` with string enums: `JobStatus` = `pending`, `running`, `completed`, `completed_with_issues`, `failed`, `cancelled`; `JobStage` = `queued`, `waiting_analysis`, `planning`, `planned`; `FileStatus` = `pending`, `ready`, `partial`, `failed`, `skipped`; `SkipReason` = `unsupported_language`, `analysis_failed`, `no_units`, `empty_or_abstract`, `body_truncated`, `private`; `Level` = `unit`, `edge`, `integration`
- [x] T008 [P] Create `Ai_project/core_ai/services/test_generation/errors.py`: `ApiError(http_status, code, message, details=None)` and constructors for `validation_error` (400), `unauthorized` (401), `forbidden` (403), `not_found` (404), `plan_not_ready` (409), `no_python_files` (422); `to_response(err)` returns a DRF `Response` with body `{"error": {"code", "message", "details"}}`
- [x] T009 [P] Write `Ai_project/core_ai/tests/test_generation/test_repo_readers.py`: create/get/update a job in `InMemoryJobRepo`; unknown `job_id` returns `None`; `job_id` matches `^job_[0-9a-f]{12}$` and is unique; `InMemoryAnalysisReader` returns the latest version, the files of a version (including files unchanged since an earlier version), and the analysis of a file
- [x] T010 Create `Ai_project/core_ai/services/test_generation/repo.py`: `new_job_id()` returning `job_` + 12 hex characters; `JobRepo` protocol (`create(job) -> job`, `get(job_id) -> job | None`, `update(job_id, fields) -> None`); `InMemoryJobRepo`; `MongoJobRepo` on `settings.TEST_JOBS_COLLECTION` with a unique index on `job_id`; `get_job_repo()` provider that tests can override; jobs carry the fields of data-model.md (`job_id`, `user_id`, `project_id`, `version_number`, `paths`, `levels`, `status`, `stage`, `files`, `plan`, `progress`, `gate`, `error`, `created_at`, `updated_at`)
- [x] T011 Create `Ai_project/core_ai/services/test_generation/readers.py`: `AnalysisReader` protocol — `latest_version(project_id) -> int | None`, `version_exists(project_id, n) -> bool`, `files_of_version(project_id, n) -> list[{file_id, path, file_type, analysis_status}]` (resolved through `project_versions.file_ids`), `file_state(file_id) -> {analysis_status, analysis_id}`, `analysis_of(file_id) -> dict | None`; `InMemoryAnalysisReader`; `MongoAnalysisReader` reading `project_versions`, `code_files`, `analysis_results` and writing nothing; `get_reader()` provider
- [x] T012 [P] Write `Ai_project/core_ai/tests/test_generation/test_auth.py`: a valid access token signed with the configured key authenticates and exposes `user_id` as a string; missing header, malformed header, wrong signature, expired token, a token with `token_type` other than `access`, and an empty `TESTGEN_JWT_SIGNING_KEY` each give 401 `unauthorized`
- [x] T013 Create `Ai_project/core_ai/services/test_generation/auth.py`: `UpmJWTAuthentication(BaseAuthentication)` that reads `Authorization: Bearer <token>`, decodes it with simplejwt's `TokenBackend("HS256", settings.TESTGEN_JWT_SIGNING_KEY)`, requires `token_type == "access"`, returns a light user object (`id`, `is_authenticated = True`, `claims`) with no database lookup, and fails closed when the key setting is empty; `authenticate_header` returns `Bearer` so DRF answers 401, not 403

**Checkpoint**: foundation ready — `pytest core_ai/tests/test_generation/test_repo_readers.py core_ai/tests/test_generation/test_auth.py` passes

---

## Phase 3: User Story 1 - Ask for tests and see what will be tested (Priority: P1) 🎯 MVP

**Goal**: a signed-in user starts a job and reads a plan listing every function and method of the
selected Python files, plus every skip with its reason. No LLM call.

**Independent Test**: build the sample project in the in-memory reader, call the start route, run
one pass, call the plan route, and compare units and skips with the source by hand: `game.py`
gives 14 units and no skips.

### Tests for User Story 1 ⚠️

> Write these tests first and see them fail before implementing

- [x] T014 [P] [US1] Write `Ai_project/core_ai/tests/test_generation/test_scope.py`: omitted `version_number` resolves to the latest; unknown version → 400; project with no version → 400; omitted or empty `paths` selects all files; an unknown path → 400 with the path in `details.paths`; omitted `levels` gives all three; an unknown or duplicated level → 400; a selection with no Python file → 422 `no_python_files`; a mixed selection keeps the non-Python files so they can be reported as skipped
- [x] T015 [P] [US1] Write `Ai_project/core_ai/tests/test_generation/test_gate.py` for the table in research.md R2: `COMPLETED` with a result → ready; `PENDING` / `IN_PROGRESS` → wait; `FAILED` or no result with fewer than 2 requests → request analysis and wait, and the request counter goes up; `FAILED` after 2 requests → skipped `analysis_failed`; not complete at the deadline → skipped `analysis_failed`; a non-Python file → skipped `unsupported_language` without any analysis request
- [x] T016 [P] [US1] Write `Ai_project/core_ai/tests/test_generation/test_python_adapter.py`: `game.py` yields 14 units, all of kind `method`, including the six `__init__`; a top-level function has kind `function`; `_helper` → skipped `private`; `__str__`-style dunder methods are units; an abstract method, a body of `pass`, a body of `...` and a body that is only a docstring → skipped `empty_or_abstract`; a unit with `body_truncated` true → skipped `body_truncated`; `no_units.py` → file skipped `no_units`; each unit carries its `body_hash`
- [x] T017 [P] [US1] Write `Ai_project/core_ai/tests/test_generation/test_graphify_merge.py`: local ids become `filepath::Class`, `filepath::Class.method`, `filepath::function`, `filepath::__module__`; external ids stay `ext.name` and are shared across files; two files that each define class `User` produce two distinct nodes; the merged graph keeps the keys `nodes`, `edges`, `meta` and every edge keeps `from`, `to`, `relation`, `confidence`; the stored per-file graph object is not mutated
- [x] T018 [P] [US1] Write `Ai_project/core_ai/tests/test_generation/test_graphify_resolver.py`: in `game.py`, `Student.enroll` calls `Course.add_student`, `Student.drop_course` calls `Course.remove_student`, `Professor.__init__` and `Student.__init__` call `Person.__init__`, `University.create_department` calls `Department.__init__`; a `self.m()` call to a method defined only on the parent resolves to the parent's method; in the two-file project a call through an imported class resolves to the unit in the other file; after resolution no `calls` edge points at a local unit through an `ext.` id, and no edge target is missing from the nodes; `queries.callees(unit_id)` returns exactly the local units called directly
- [x] T019 [P] [US1] Write `Ai_project/core_ai/tests/test_generation/test_planner.py`: every function and method of the input appears exactly once, as a unit or as a skip; `work_items_count` equals units × requested levels (`game.py` with three levels → 42, with one level → 14); a skipped file appears as `{path, reason}` and a skipped unit as `{path, unit, reason}`; a skip never removes the other files' units; units are listed in a stable order (file path, then position in the file)
- [x] T020 [P] [US1] Write the planning part of `Ai_project/core_ai/tests/test_generation/test_runner.py`: one pass on a fully analysed `game.py` project ends with status `completed`, stage `planned`, a plan of 14 units and `progress.total` 42 with every work item `pending`; a project with one Python and one JavaScript file plans the Python file and reports the other as skipped `unsupported_language`; a job restricted to one path plans only that file; running the same pass twice leaves the job unchanged
- [x] T021 [P] [US1] Write the start and plan parts of `Ai_project/core_ai/tests/test_generation/test_api.py` with `APIRequestFactory`: `POST jobs/` with only `project_id` → 202 with `job_id`, `status` `pending`, `project_id`, `version_number`, and one background pass enqueued; each validation case of contracts/api.md → 400; no Python file → 422; `GET jobs/{id}/plan/` returns `units` (`id`, `file`, `kind` only — no `body_hash`), `skipped`, `work_items_count`; plan requested before the first pass → 409 `plan_not_ready`; unknown job → 404

### Implementation for User Story 1

- [x] T022 [P] [US1] Implement `Ai_project/core_ai/services/test_generation/scope.py`: `resolve(request_data, reader) -> Scope(project_id, version_number, paths, levels, files)` raising `ApiError` for the 400 and 422 cases; file paths are matched exactly against each file's stored `filepath`
- [x] T023 [P] [US1] Implement `Ai_project/core_ai/services/test_generation/gate.py`: pure function `decide(file_entry, file_state, now, deadline) -> Decision(ready | wait | request_analysis | skip(reason))` implementing the table in research.md R2, with at most 2 analysis requests per file; no I/O inside
- [x] T024 [P] [US1] Implement `Ai_project/core_ai/services/test_generation/languages/python_adapter.py`: `list_units(file_path, analysis) -> (units, skips)` reading `class_diagram_data.classes[].methods[]` and `class_diagram_data.module_functions[]`, applying the rules of research.md R5 in order; `is_python(file_type)`
- [x] T025 [US1] Implement `Ai_project/core_ai/services/test_generation/graphify/loader.py`: `load_file(file_path, analysis) -> FileGraph` with the stored `dependency_graph` (copied, never mutated), the class and unit table from `class_diagram_data` (names, `base_classes`, parameters with types, bodies), and the top-level `Import` / `ImportFrom` entries from `ast_structure.ast_tree.body`
- [x] T026 [US1] Implement `Ai_project/core_ai/services/test_generation/graphify/merge.py`: `merge(file_graphs) -> ProjectGraph` that rewrites local ids to `filepath::Name`, keeps `ext.name` ids shared, joins nodes and edges, and sets `meta` to `{total_nodes, total_edges, source: "merged", files}` (depends on T025)
- [x] T027 [US1] Implement `Ai_project/core_ai/services/test_generation/graphify/resolver.py`: `resolve_calls(project_graph, file_graphs) -> ProjectGraph` that parses each unit's stored body with `ast` and resolves, in order, `self.m()` through the class and its bases, `super().m()` to the parent class, `param.m()` through the parameter's type annotation, `Name()` to a local function or a local class constructor, and an imported name to the unit in the other project file; replaces `ext.`/dangling call edges that it can resolve; skips units whose body is truncated or does not parse (depends on T026)
- [x] T028 [P] [US1] Implement `Ai_project/core_ai/services/test_generation/graphify/queries.py`: `callees(project_graph, unit_id) -> list[unit_id]` returning the local units a unit calls directly, without duplicates
- [x] T029 [US1] Implement `Ai_project/core_ai/services/test_generation/planner.py`: `build_plan(ready_files, skipped_files, levels) -> {units, skipped, work_items_count}` using `python_adapter.list_units`, in a stable order; units carry `id`, `file`, `kind`, `body_hash` (depends on T024)
- [x] T030 [US1] Implement `Ai_project/core_ai/services/test_generation/runner.py`: `run_pass(job_id, repo, reader, request_analysis, now) -> PassResult(done: bool)` — load the job, set status `running`, apply `gate.decide` to every selected file and call `request_analysis(file_id)` when asked, build the graph for ready files (loader → merge → resolver), build the plan, save `files`, `plan`, `progress` and `stage`, and end with status `completed` / stage `planned` when no file is waiting, or status `failed` with an error when no Python file could be analysed (depends on T022, T023, T027, T029)
- [x] T031 [US1] Implement `Ai_project/core_ai/celery_tasks/testgen_tasks.py`: Celery task `advance_job(job_id)` that calls `runner.run_pass` with the Mongo repo and reader and with `request_analysis = analyze_code_file_task.delay`, and never calls `.get()` on any task (re-enqueue is added in T037)
- [x] T032 [US1] Implement `Ai_project/core_ai/serializers/testgen_serializer.py`: `StartJobSerializer` (`project_id` required string; `version_number` optional positive integer; `paths` optional list of non-empty strings; `levels` optional list drawn from `unit`, `edge`, `integration`, no duplicates) and `plan_response(job)` that drops internal fields
- [x] T033 [US1] Implement the start and plan views in `Ai_project/core_ai/views/testgen_views.py`: `JobListView.post` (validate → `scope.resolve` → create the job as `pending` / `queued` with `user_id` from the token → `advance_job.delay(job_id)` → 202) and `JobPlanView.get` (404 when unknown, 409 `plan_not_ready` while `plan` is null); both use `UpmJWTAuthentication` and turn `ApiError` into the common error body
- [x] T034 [US1] Wire the routes: create `Ai_project/core_ai/urls.py` with `jobs/` and `jobs/<str:job_id>/plan/`, and add `path('api/analysis/tests/', include('core_testing.urls'))` before the `core_ai` include in `Ai_project/Ai_project/urls.py`

**Checkpoint**: User Story 1 works on its own — T014 to T021 pass

---

## Phase 4: User Story 2 - Follow the job while it works (Priority: P2)

**Goal**: the user polls one route and sees status, stage, progress and one line per file, also
while a file waits for its analysis.

**Independent Test**: start a job where one file has no analysis yet, poll, see that file as
pending while the others are planned, complete its analysis in the reader, run the next pass, and
see its units join the plan.

### Tests for User Story 2 ⚠️

- [x] T035 [P] [US2] Extend `Ai_project/core_ai/tests/test_generation/test_runner.py` with the waiting cases: with one analysed file and one file without analysis, the first pass plans the analysed file, requests analysis of the other exactly once, leaves the job `running` and reports `done = False`; when the reader then shows that file as `COMPLETED`, the next pass adds its units and ends `completed` / `planned`; a file that is `FAILED` is requested a second time and, if still `FAILED`, is skipped `analysis_failed` while the job still completes; when every Python file fails, the job ends `failed` with an error; past the deadline a waiting file is skipped `analysis_failed`; stage is `waiting_analysis` only while nothing else is left to work on
- [x] T036 [P] [US2] Extend `Ai_project/core_ai/tests/test_generation/test_api.py` with the status route: `GET jobs/{id}/` returns `job_id`, `project_id`, `version_number`, `status`, `stage`, `progress` (`total`, `done`, `by_status` with the six keys `pending`, `ready`, `skipped`, `generation_failed`, `test_failed`, `environment_error`), `files[]` and `error`; a skipped file shows `status` `skipped` and its `reason`; a waiting file shows `pending`; internal fields (`file_id`, `analysis_requests`, `gate`, `user_id`) are absent; unknown job → 404

### Implementation for User Story 2

- [x] T037 [US2] Add re-enqueue to `Ai_project/core_ai/celery_tasks/testgen_tasks.py`: when `run_pass` reports `done = False`, call `advance_job.apply_async((job_id,), countdown=settings.TESTGEN_GATE_POLL_SECONDS)`; set the gate deadline once, on the first pass, to now + `TESTGEN_GATE_MAX_WAIT_SECONDS`
- [x] T038 [US2] Complete the gate bookkeeping in `Ai_project/core_ai/services/test_generation/runner.py`: keep `analysis_requests` per file and `gate.deadline_at` / `gate.passes` on the job, compute `stage` (`waiting_analysis` when only waiting files remain, otherwise `planning`, and `planned` at the end), and compute `progress` (`total` = work items, `done` = 0, `by_status.pending` = work items, `by_status.skipped` = skipped files + skipped units)
- [x] T039 [US2] Add `status_response(job)` to `Ai_project/core_ai/serializers/testgen_serializer.py` (shape of contracts/api.md section 2) and `JobDetailView.get` to `Ai_project/core_ai/views/testgen_views.py`; add the route `jobs/<str:job_id>/` to `Ai_project/core_ai/urls.py`

**Checkpoint**: User Stories 1 and 2 both work — T035 and T036 pass

---

## Phase 5: User Story 3 - Only the owner can use the job (Priority: P3)

**Goal**: every test route refuses a caller without a valid token, and a job is readable only by
the user who created it.

**Independent Test**: call each of the three routes with no token, with the owner's token and with
another user's token.

### Tests for User Story 3 ⚠️

- [x] T040 [P] [US3] Extend `Ai_project/core_ai/tests/test_generation/test_api.py` with access cases: each of the three routes without a token → 401 `unauthorized`; with an invalid token → 401; a job created by user A read by user B on the status route and on the plan route → 403 `forbidden`; the owner still gets 200; the job stores the creator's `user_id`

### Implementation for User Story 3

- [x] T041 [US3] Add `require_owner(job, user)` to `Ai_project/core_ai/services/test_generation/auth.py` (raises `forbidden` when `job.user_id != str(user.id)`) and call it in `JobDetailView.get` and `JobPlanView.get` in `Ai_project/core_ai/views/testgen_views.py`, after the 404 check
- [x] T042 [US3] Make sure the three views in `Ai_project/core_ai/views/testgen_views.py` set `authentication_classes = [UpmJWTAuthentication]` and `permission_classes = [IsAuthenticated]` explicitly, so they never fall back to the service defaults or to `AllowAny`

**Checkpoint**: all three user stories work — the whole `core_ai/tests/test_generation` folder passes

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: prove the boundaries, run the acceptance check, write the report

- [x] T043 [P] Write `Ai_project/core_ai/tests/test_generation/test_boundaries.py`: no module under `core_ai/services/test_generation/` (tests excluded) imports `llm_client`, `core_ai.ai_engine` or `core_ai.services.conflict_detection`; no module under `core_ai/` imports `core_testing`; a full job on `game.py` completes while `LLMClient.call_model` raises on any call
- [x] T044 Run the whole suite in the `ai_web` image with the command of quickstart.md (`core_ai/tests/test_generation` and `core_ai/tests`) and fix what fails; the 210 tests that existed before this slice must still pass
- [x] T045 Run the Postman sequence and the negative checks of `specs/001-test-job-plan/quickstart.md` against the running stack (real Mongo, real Celery worker) and record the responses: the plan of `game.py` shows 14 units, an empty `skipped` list and `work_items_count` 42
- [x] T046 Write the Arabic report `Ai_project/core_ai/tests/reports/testgen_s1_job_and_plan.md`: goal of the slice; files added and changed; how the tests were run; one table per test file (what it checks, result); the acceptance run of T045; the existing collections and fields this slice reads; how to call the three routes; the list of items left for S2 onward; any problem found
- [x] T047 Remove the temporary "Sync Impact Report" comment from `.specify/memory/constitution.md` and commit the slice (Spec Kit files, `core_testing`, the three changed files, the report)

### Follow-up found by the acceptance run

- [x] T048 Add `Ai_project/core_ai/services/test_generation/staleness.py`: `stale_error(job, now, queue_timeout_seconds, gate_max_wait_seconds)` and `fail_if_stale(job, repo, now, ...)` — a job `pending`/`queued` for more than 120 s, or `running` with no update for more than the gate's maximum wait + 120 s, is marked `failed` with `error.code` `worker_unavailable`; add `TESTGEN_QUEUE_TIMEOUT_SECONDS = 120` to `Ai_project/Ai_project/settings.py`
- [x] T049 Call `staleness.fail_if_stale` when a job is read in `Ai_project/core_ai/views/testgen_views.py` (status and plan routes), and make the plan route answer 409 with a clear message when the job failed before any plan was built
- [x] T050 [P] Write `Ai_project/core_ai/tests/test_generation/test_staleness.py` and extend `Ai_project/core_ai/tests/test_generation/test_api.py`: queued too long → failed; running with no progress → failed; finished jobs never change; a late pass does not revive a failed job

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies
- **Foundational (Phase 2)**: depends on Setup; blocks every user story
- **User Story 1 (Phase 3)**: depends on Foundational
- **User Story 2 (Phase 4)**: depends on User Story 1 (it extends `runner.py`, `tasks.py`, `views.py`)
- **User Story 3 (Phase 5)**: depends on User Story 2 (it guards the status route as well)
- **Polish (Phase 6)**: depends on all three stories

### User Story Dependencies

The three stories share the same few files, so they are done in priority order, not in parallel.
Each one still has its own test set and its own checkpoint.

### Within Each User Story

- tests first, and they must fail before the implementation exists
- pure logic (`scope`, `gate`, `python_adapter`, `graphify`) before `planner`, then `runner`, then
  `tasks`, then serializers, views and routes
- T025 → T026 → T027 are sequential (loader → merge → resolver)

### Parallel Opportunities

- T003 and T004 with each other
- T007, T008, T009, T012 with each other
- all test tasks of User Story 1 (T014 to T021) with each other
- T022, T023, T024, T028 with each other

---

## Parallel Example: User Story 1

```bash
# Tests of User Story 1 — different files, no dependency between them:
Task: "Write Ai_project/core_ai/tests/test_generation/test_scope.py"
Task: "Write Ai_project/core_ai/tests/test_generation/test_gate.py"
Task: "Write Ai_project/core_ai/tests/test_generation/test_python_adapter.py"
Task: "Write Ai_project/core_ai/tests/test_generation/test_graphify_merge.py"

# Pure-logic modules of User Story 1:
Task: "Implement Ai_project/core_ai/services/test_generation/scope.py"
Task: "Implement Ai_project/core_ai/services/test_generation/gate.py"
Task: "Implement Ai_project/core_ai/services/test_generation/languages/python_adapter.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Phase 1: Setup
2. Phase 2: Foundational
3. Phase 3: User Story 1
4. **Stop and validate**: start a job and read the plan of `game.py`

### Incremental Delivery

1. Setup + Foundational → the app loads and a token can be checked
2. User Story 1 → a job can be started and its plan read (the slice's acceptance check)
3. User Story 2 → the job can be followed, and files without analysis are handled
4. User Story 3 → jobs are private to their creator
5. Polish → boundaries proven, acceptance run recorded, report written, commit

---

## Notes

- 50 tasks: Setup 6, Foundational 7, User Story 1 21, User Story 2 5, User Story 3 3, Polish 5, follow-up 3
- Out of scope for every task here: any LLM call, prompt or context building, test file writing,
  sandbox, coverage, download, repair, edge hints, integration groups, cancel, records listing,
  and the graph additions that S1 does not need (builtins, confidence tiers, `io_kind`, cache)
- Nothing under `Ai_project/core_ai/` is edited by any task
- A task is ticked only when its test passes inside the `ai_web` image
