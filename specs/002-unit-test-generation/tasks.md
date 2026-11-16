---

description: "Task list for S2 — Unit Test Generation (not run yet)"
---

# Tasks: S2 — Unit Test Generation (not run yet)

**Input**: Design documents from `/specs/002-unit-test-generation/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/api.md, quickstart.md

**Tests**: included (the constitution requires tests for every slice). No test may make a real
model request.

**Organization**: tasks are grouped by user story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: US1, US2, US3
- Paths are relative to the repository root

---

## Phase 1: Setup (Shared Infrastructure)

- [x] T001 Add settings to `Ai_project/Ai_project/settings.py`: `TEST_RECORDS_COLLECTION = 'test_records'`, `TEST_ATTEMPTS_COLLECTION = 'test_attempts'`, `TESTGEN_MAX_REQUESTS_PER_JOB = 20`, `TESTGEN_LLM_MAX_TOKENS = 2000`, `TESTGEN_LLM_MODEL = None`
- [x] T002 [P] Create empty packages `Ai_project/core_ai/services/test_generation/prompts/__init__.py`, `Ai_project/core_ai/services/test_generation/strategies/__init__.py`, `Ai_project/core_ai/services/test_generation/validation/__init__.py`
- [x] T003 [P] Create `Ai_project/core_ai/tests/test_generation/fakes.py`: `FakeModel(answers)` — a callable with the signature of `call_model_ex` that returns scripted answers by unit name found in the prompt, counts its calls, can be told to raise `LLMUnavailable` from the n-th call on, and returns `{"text", "model": "fake/model", "prompt_tokens": 11, "completion_tokens": 22}`; plus `good_test_for(unit_name, import_statement, call)` that builds a valid answer inside a fenced block

---

## Phase 2: Foundational (Blocking Prerequisites)

**⚠️ CRITICAL**: no user story work starts before this phase is complete

- [x] T004 [P] Write `Ai_project/core_ai/tests/test_llm_client_ex.py` (HTTP replaced by a fake `requests.post`): `call_model` still returns only the text and still serves a repeated prompt from its cache; `call_model_ex` returns `text`, `model`, `prompt_tokens`, `completion_tokens` taken from the response's `usage`, sends the given `temperature` and `max_tokens`, and does not read or write the cache; when every model answers 429 both raise `LLMUnavailable`, which is an `Exception`
- [x] T005 Change `Ai_project/core_ai/ai_engine/llm_client.py`: add `class LLMUnavailable(Exception)`; move the model sweep into one inner static method returning `(text, model, usage)`; `call_model` keeps its signature, cache and return value and calls it; add `call_model_ex(system_prompt, user_prompt, *, model=None, temperature=0.0, max_tokens=4000, force_request=False) -> dict`; raise `LLMUnavailable` where the plain `Exception("All free models are busy...")` and the missing-key `Exception` are raised today
- [x] T006 [P] Extend `Ai_project/core_ai/services/test_generation/statuses.py`: `RecordStatus` = `pending`, `generated`, `ready`, `skipped`, `generation_failed`, `test_failed`, `environment_error`; `JobStage.GENERATING = "generating"`, `JobStage.GENERATED = "generated"`; `FailReason` = `no_code`, `syntax_error`, `forbidden_import`, `unsafe_code`, `weak_test`; `StopReason` = `model_unavailable`, `request_limit_reached`; add `generated` to `RECORD_STATUSES`
- [x] T007 [P] Write `Ai_project/core_ai/tests/test_generation/test_records.py`: record ids match `^t_[0-9a-f]{10}$`; `create_many`, `get`, `list(job_id, status=, path=, level=)`, `next_pending(job_id, level)` in a stable order, `update`, `counts(job_id)`; attempts: `add`, `find_reusable(request_hash)` returns the latest attempt that has an `answer_text` and ignores ones without
- [x] T008 Create `Ai_project/core_ai/services/test_generation/records.py`: `new_record(job_id, unit, level)` and `new_attempt(...)` with the fields of data-model.md; `RecordRepo` and `AttemptRepo`, each with an in-memory and a Mongo implementation (`settings.TEST_RECORDS_COLLECTION`, unique index on `record_id`, index on (`job_id`, `level`, `status`); `settings.TEST_ATTEMPTS_COLLECTION`, index on `request_hash`); providers `get_record_repo()` / `set_record_repo()`, `get_attempt_repo()` / `set_attempt_repo()`; add `records` and `attempts` fixtures to `Ai_project/core_ai/tests/test_generation/conftest.py`
- [x] T009 Create `Ai_project/core_ai/services/test_generation/languages/base.py`: `LanguageAdapter` interface (`supports(file_type, path)`, `list_units(path, analysis)`, `find_entry(analysis, unit_id)`, `import_statement(path, name)`, `allowed_import_roots(project_paths)`, `prompt_rules()`), `PythonAdapter` delegating to `python_adapter`, and `adapter_for(file_type, path)` backed by a one-entry registry
- [x] T010 Extend `Ai_project/core_ai/services/test_generation/languages/python_adapter.py`: `find_entry(analysis, unit_id) -> (class_entry | None, unit_entry)`; `module_name(path)` (`pkg/game.py` → `pkg.game`, a path with no extension is used as it is); `import_statement(path, name)` (`from pkg.game import Student`); `project_import_roots(project_paths)` (top-level package and module names of the project); `BUILTIN_NAMES`
- [x] T011 Extend `Ai_project/core_ai/services/test_generation/planner.py` so each planned unit also carries `externals`: the `ext.` targets of its `calls` edges, without the `ext.` prefix and without Python builtins; extend `Ai_project/core_ai/tests/test_generation/test_planner.py` (game: `Student.enroll` has no externals after `len` and `print` are dropped; a unit calling `os.getcwd()` lists `os.getcwd`)

**Checkpoint**: foundation ready — the whole existing suite still passes

---

## Phase 3: User Story 1 - A unit test is written for every planned unit (Priority: P1) 🎯 MVP

**Goal**: after planning, the job generates one checked pytest test per planned unit, one unit per
pass, and never marks anything `ready`.

**Independent Test**: with the fake model, run a job on `game.py` to the end: 14 `unit` records,
each `generated` with code that parses and follows the naming rule; the `edge` and `integration`
records still `pending`.

### Tests for User Story 1 ⚠️

- [x] T012 [P] [US1] Write `Ai_project/core_ai/tests/test_generation/test_validator.py`: code is taken from the first fenced Python block, or from the whole answer when it parses; an answer with no code → `no_code`; unparseable code → `syntax_error`; `import requests` or `import numpy` → `forbidden_import` with the module in the detail; `import pytest`, `from unittest import mock`, `from game import Student` pass; no test function, a test with no `assert` / `pytest.raises`, a test that never calls the unit (method name for a method, class call for `__init__`, function name for a function) → `weak_test`; test functions are renamed in order to `test_<unit>__unit_<n>` and the result still parses; the first failing check decides the reason
- [x] T013 [P] [US1] Write `Ai_project/core_ai/tests/test_generation/test_safety_lint.py`: each of `import socket`, `import subprocess`, `from urllib import request`, `eval(...)`, `exec(...)`, `os.system(...)`, `time.sleep(...)`, `open("x", "w")` is reported; `open(tmp_path / "x", "w")`, `open("x")` (read) and `monkeypatch.setattr(...)` are not
- [x] T014 [P] [US1] Write `Ai_project/core_ai/tests/test_generation/test_assembler.py`: path rule `tests/generated/test_<file>_<unit>__unit.py` (`game.py::Student.enroll` → `tests/generated/test_game_Student_enroll__unit.py`; `pkg/util.py::slugify` → `tests/generated/test_pkg_util_slugify__unit.py`); the file text starts with a header naming the unit id, the body hash and that the test has not been run; the text parses
- [x] T015 [P] [US1] Write `Ai_project/core_ai/tests/test_generation/test_generation.py` (fake model, in-memory storage): planning with `then_generate=True` creates 42 records for `game.py` and leaves the job `running` / `generating`; each generation pass handles exactly one unit record and returns not done until none is pending; at the end the job is `completed` / `generated`, 14 unit records are `generated` with `test_path`, `test_code`, `model`, `prompt_version`, and the 28 other records are `pending`; a bad answer for one unit gives `generation_failed` with its reason while the other 13 are generated, and the job ends `completed_with_issues`; no record is ever `ready`; a job that requested only `edge` ends `completed` / `planned` with no model call; `run_pass` without `then_generate` behaves exactly as in S1
- [x] T016 [P] [US1] Extend `Ai_project/core_ai/tests/test_generation/test_generation.py` with the stop cases: the model raising unavailable on the 4th call → 3 records `generated`, the 4th still `pending` (not failed), job `completed_with_issues` with `error.code` `model_unavailable`, and no further call is made; with a request limit of 5 → 5 generated, the rest `pending`, `error.code` `request_limit_reached`, `llm_requests` is 5

### Implementation for User Story 1

- [x] T017 [P] [US1] Create `Ai_project/core_ai/services/test_generation/validation/safety_lint.py`: `find_unsafe(tree) -> str | None` implementing rule 4 of research.md R7, returning one readable line or None
- [x] T018 [US1] Create `Ai_project/core_ai/services/test_generation/validation/validator.py`: `extract_code(answer)`, `validate(answer, *, unit_name, class_name, kind, allowed_roots) -> Result(ok, code, reason_code, reason_detail)` running the checks of research.md R7 in order and renaming test functions by editing their `def` lines (depends on T017)
- [x] T019 [P] [US1] Create `Ai_project/core_ai/services/test_generation/assembler.py`: `test_path(unit_id)` and `assemble(code, *, unit_id, body_hash, job_id) -> str` (header + code)
- [x] T020 [US1] Change `Ai_project/core_ai/services/test_generation/runner.py`: `run_pass(..., then_generate=False, record_repo=None)`; when `then_generate` is true, planning is complete and `unit` is among the levels, create one record per (unit, level) — once, guarded by a flag on the job — and set status `running`, stage `generating` instead of finishing; otherwise behave as in S1
- [x] T021 [US1] Create `Ai_project/core_ai/services/test_generation/generation.py`: `run_generation_pass(job_id, repo, record_repo, attempt_repo, reader, llm, now, *, max_requests) -> PassResult` implementing phase B of plan.md: next pending `unit` record → limit check → context → reuse or model → validate → assemble → update record and progress → finish or continue; on `ModelUnavailable` or the limit, end the job `completed_with_issues` with the stop reason and leave the record `pending` (depends on T018, T019, T020, and on T024, T026, T028 of User Story 2)
- [x] T022 [US1] Change `Ai_project/core_ai/celery_tasks/testgen_tasks.py`: `advance_job` runs `run_pass(..., then_generate=True)` while the stage is before `generating`, and `run_generation_pass` after; it re-enqueues with the gate's delay while files wait for analysis and with no delay between units; it builds the facade with `LLMClient.call_model_ex`
- [x] T023 [US1] Change the progress computation: `progress` is computed from the records when they exist (`total` = records, `done` = records not `pending`, `by_status` with the `generated` key), and from the plan as in S1 before that — in `Ai_project/core_ai/services/test_generation/runner.py` and `Ai_project/core_ai/services/test_generation/generation.py`

**Checkpoint**: T012 to T016 pass

---

## Phase 4: User Story 2 - The model sees only what it needs, and every call is recorded (Priority: P2)

**Goal**: a fixed-shape context per unit, one facade that records every call, and reuse of stored
answers.

**Independent Test**: build the context of `Student.enroll` and check it holds that body and the
callee's signature but no other body; run a job twice and check the second spends no request.

### Tests for User Story 2 ⚠️

- [x] T024 [P] [US2] Write `Ai_project/core_ai/tests/test_generation/test_context.py`: the context of `game.py::Student.enroll` has the unit's body, signature, parameters, return type and `from game import Student`; `class` has the name, bases `["Person"]` and the constructor's signature; `callees` has `Course.add_student` with its signature and import statement; the context's JSON does not contain the body of `add_student` nor of any other unit; a module-level function has `class` null; the hash is the same for the same input and changes when the body changes; in the two-file project a callee from another file is listed with that file's import statement
- [x] T025 [P] [US2] Write `Ai_project/core_ai/tests/test_generation/test_llm_facade.py`: `complete` calls the client with temperature 0 and the configured `max_tokens`; one attempt is written with `purpose` `generate`, the model, token counts, `duration_ms`, `request_hash`, `outcome` `answered` and the raw `answer_text`; `LLMUnavailable`, a missing key and a network error each become `ModelUnavailable` and write an attempt with `outcome` `model_unavailable`; the facade never touches a real network (the client is injected)
- [x] T026 [P] [US2] Write `Ai_project/core_ai/tests/test_generation/test_unit_strategy.py`: the system prompt asks for one pytest file in a fenced block and forbids network, processes and file writes outside `tmp_path`; the user prompt contains the context JSON and the naming rule; nothing from the project appears in the prompt except what the context holds (a marker string placed in another unit's body is absent); `PROMPT_VERSION` is `unit-v1`
- [x] T027 [P] [US2] Extend `Ai_project/core_ai/tests/test_generation/test_generation.py` with reuse: a second job on the same project makes zero model calls, its records are `generated` with `reused` true, its attempts have `reused` true and zero tokens, and its `llm_requests` is 0; changing one unit's body makes exactly that unit spend a request again; an answer that failed validation is still reused (and still fails) rather than asked for again

### Implementation for User Story 2

- [x] T028 [P] [US2] Create `Ai_project/core_ai/services/test_generation/context.py`: `build_unit_context(unit, analyses_by_path, adapter) -> dict` with the shape of data-model.md, and `context_hash(context, prompt_version) -> str` (SHA-256 of the canonical JSON)
- [x] T029 [P] [US2] Create `Ai_project/core_ai/services/test_generation/prompts/unit.py`: `PROMPT_VERSION = "unit-v1"`, `SYSTEM`, and `USER_TEMPLATE` (context JSON + rules)
- [x] T030 [US2] Create `Ai_project/core_ai/services/test_generation/strategies/base.py` (`TestKindStrategy`: abstract `level`, `build_context`, `prompt_sections`; concrete `build_prompt`, `test_name_rule`) and `Ai_project/core_ai/services/test_generation/strategies/unit.py` (`UnitStrategy`) (depends on T028, T029)
- [x] T031 [US2] Create `Ai_project/core_ai/services/test_generation/llm_facade.py`: `ModelUnavailable`, `LLMFacade(client, attempt_repo, *, max_tokens, model)` with `complete(*, job_id, record_id, unit_id, level, purpose, system, user, request_hash, prompt_version) -> LLMResult(text, model, prompt_tokens, completion_tokens)`; the only module of `core_testing` that imports `core_ai.ai_engine.llm_client`
- [x] T032 [US2] Add reuse to `Ai_project/core_ai/services/test_generation/generation.py`: before calling the facade, `attempt_repo.find_reusable(request_hash)`; when found, use its `answer_text`, write an attempt with `reused` true and zero tokens, and do not increase `llm_requests`
- [x] T033 [US2] Update `Ai_project/core_ai/tests/test_generation/test_boundaries.py`: `llm_client` may be imported by `core_ai/services/test_generation/llm_facade.py` only; every other module of `core_testing` still must not import it, nor any other feature

**Checkpoint**: T024 to T027 pass

---

## Phase 5: User Story 3 - See what was generated (Priority: P3)

**Goal**: list a job's records with filters, read one record with its code, and see the new
counters on the job.

**Independent Test**: after a finished job, list the records, filter by status, path and level,
open one record, and compare with the plan.

### Tests for User Story 3 ⚠️

- [x] T034 [P] [US3] Write `Ai_project/core_ai/tests/test_generation/test_api_records.py`: the list returns `items` (`id`, `file`, `unit_id`, `level`, `status`, `reason_code`, `test_path` — no `test_code`) and `total`; filters `status`, `path`, `level` and their combination; an unknown `status` or `level` → 400; before planning → `{"items": [], "total": 0}`; the detail returns `test_code`, `executed` false, the notice, `model`, `prompt_version`; `test_code` is null for a failed record; a record id of another job → 404; no token → 401; another user → 403 on both routes
- [x] T035 [P] [US3] Extend `Ai_project/core_ai/tests/test_generation/test_api.py`: after generation the status route shows `stage` `generated`, `progress.by_status.generated`, `progress.done`, `files[].status` (`generated` / `partial` / `failed`) and `files[].levels`; a job that stopped early shows `completed_with_issues` and `error.code`

### Implementation for User Story 3

- [x] T036 [US3] Extend `Ai_project/core_ai/serializers/testgen_serializer.py`: `records_response(records)`, `record_detail_response(record)` with `executed: false` and the notice, `validate_record_filters(query)`, and `status_response` computing `files[].status` and `files[].levels` from the records
- [x] T037 [US3] Add `JobRecordsView` and `JobRecordDetailView` to `Ai_project/core_ai/views/testgen_views.py` (same authentication, ownership and stale-job rules as the other routes) and their routes `jobs/<str:job_id>/records/` and `jobs/<str:job_id>/records/<str:record_id>/` to `Ai_project/core_ai/urls.py`

**Checkpoint**: the whole `core_ai/tests/test_generation` folder passes

---

## Phase 6: Polish & Cross-Cutting Concerns

- [x] T038 Run the whole suite in the `ai_web` image (`core_ai/tests/test_generation`, `core_ai/tests`, `test_graphify_implementation.py`) and fix what fails; the 343 tests that existed before this slice must still pass
- [x] T039 Run the Postman sequence of `specs/002-unit-test-generation/quickstart.md` against the running stack with the real model on the `task_test` project (9 units, 9 requests), read at least two generated tests by eye, repeat the job to see reuse, and record the responses
- [x] T040 Write the Arabic report `Ai_project/core_ai/tests/reports/testgen_s2_unit_generation.md`: goal; files added and changed; how tests were run; one table per test file; the acceptance run of T039 with one generated test quoted; requests spent and models that answered; problems found; what is left for S3 onward
- [x] T041 Commit the slice

### Follow-up found by the acceptance run

- [x] T042 Raise the answer limit: `TESTGEN_LLM_MAX_TOKENS = 4000` in `Ai_project/Ai_project/settings.py` (2000 cut two of nine real answers off mid-file)
- [x] T043 In `Ai_project/core_ai/services/test_generation/validation/validator.py` add `looks_cut_off(answer)` (odd number of fence markers), extract the text of an unclosed fence, and report its parse failure as `syntax_error` with a detail saying the answer was cut off; in `Ai_project/core_ai/services/test_generation/generation.py` never reuse a cut-off answer — ask again
- [x] T044 [P] Tests in `Ai_project/core_ai/tests/test_generation/test_validator.py` and `Ai_project/core_ai/tests/test_generation/test_generation.py`: a cut-off answer is recognised, named, and asked again by the next job while the other units are reused

---

## Dependencies & Execution Order

### Phase Dependencies

- Setup → Foundational → User Story 1 and User Story 2 → User Story 3 → Polish
- User Story 1's generation pass (T021) needs User Story 2's context, prompt and facade (T028 to
  T031). In practice Phase 4's implementation tasks are done before T021; the stories keep
  separate test sets and checkpoints.

### Within Each User Story

- tests first, failing before the implementation exists
- pure modules (`safety_lint`, `validator`, `assembler`, `context`, `prompts`) before `strategies`
  and `llm_facade`, then `generation`, then `tasks`, then serializers and views

### Parallel Opportunities

- T002, T003; T004, T006, T007; all test tasks inside a story; T017, T019; T028, T029

---

## Implementation Strategy

1. Setup + Foundational: the client can report model and tokens, records can be stored.
2. User Story 2's building blocks (context, prompt, facade), then User Story 1's generation pass.
3. **Stop and validate** with the fake model: a full job on `game.py`.
4. User Story 3: the two routes.
5. Polish: full suite, real-model run by the owner, report, commit.

---

## Notes

- 44 tasks: Setup 3, Foundational 8, User Story 1 12, User Story 2 10, User Story 3 4, Polish 4, follow-up 3
- Out of scope for every task: running a test, sandbox, coverage, `ready`, download, repair, edge,
  integration, cancel, a separate queue or worker
- The only files changed outside `core_testing`: `core_ai/ai_engine/llm_client.py` and
  `Ai_project/settings.py`
- A task is ticked only when its test passes inside the `ai_web` image
- Test files were grouped differently from the list above: the safety-lint tests are in
  `test_validator.py`; the facade tests are in `test_records.py`; the assembler and unit-strategy
  tests are in `test_context.py`. Every case listed in the tasks is covered.
