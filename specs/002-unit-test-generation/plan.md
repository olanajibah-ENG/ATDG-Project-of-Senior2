# Implementation Plan: S2 — Unit Test Generation (not run yet)

**Branch**: `feature/core-testing` | **Date**: 2026-11-13 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/002-unit-test-generation/spec.md`

## Layout update (2026-11-16)

On the supervisor's advice the owner moved Feature 1 out of its own Django app and into `core_ai`,
laid out like logical explanation and conflict detection. File paths in this folder were updated
to the new places. Where the text still says "the `core_testing` app", read it by this table.

| Was | Is now |
|-----|--------|
| `Ai_project/core_testing/` (logic) | `Ai_project/core_ai/services/test_generation/` |
| `core_testing/views.py` | `core_ai/views/testgen_views.py` |
| `core_testing/serializers.py` | `core_ai/serializers/testgen_serializer.py` |
| `core_testing/tasks.py` | `core_ai/celery_tasks/testgen_tasks.py` |
| `core_testing/urls.py` | merged into `core_ai/urls.py` (block "Test Generation") |
| `core_testing/apps.py`, `INSTALLED_APPS` entry | removed: `core_ai` is the app |
| document builders in `repo.py` / `records.py` | `core_ai/models/testgen.py` |
| `core_testing/tests/` | `core_ai/tests/test_generation/` |
| `core_testing/tests/reports/s*.md` | `core_ai/tests/reports/testgen_s*.md` |
| settings `CORE_TESTING_*` | `TESTGEN_*` |
| Celery task `core_testing.advance_job` | `core_ai.testgen.advance_job` |

Routes, request and response shapes, collections and behaviour are unchanged. The boundary that
the separate app used to give is now checked by `core_ai/tests/test_generation/test_boundaries.py`:
only Feature 1's own entry files import the package, the package imports no other feature, and
only `llm_facade.py` imports the model client.

## Summary

After a job's plan is built, the job goes on by itself: for each planned unit it builds a small
context, asks the language model for one pytest unit test, checks the answer without running it,
and stores the test. A checked test gets the status `generated`; nothing becomes `ready`.

Technical approach: the existing background task gains a second phase. Planning ends by creating
one record per work item, then the task handles **one unit per pass** and re-enqueues itself until
no `unit` record is pending or generation has to stop. All model access goes through one small
facade that records every call. Two collections are added (`test_records`, `test_attempts`) and
two routes (list records, read one record).

## Technical Context

**Language/Version**: Python 3.10 (the `ai_web` Docker image)

**Primary Dependencies**: as in S1 (Django 4.2, DRF 3.17, Celery 5.6, PyMongo 4.17). The existing
`LLMClient` (OpenRouter) is reused. No new dependency.

**Storage**: MongoDB. New collections `test_records` and `test_attempts`. `test_jobs` gains a few
fields. Read-only use of the analysis collections, as in S1.

**Testing**: pytest in the `ai_web` image, no database, no network. The model is replaced by a
scripted fake; a real model call is impossible in the test run.

**Target Platform**: the existing `ai_web` and `celery_worker` containers. No new queue or worker
in this slice (they arrive with the sandbox).

**Project Type**: web service (the `core_testing` app grows)

**Performance Goals**: one pass handles one unit; a pass lasts as long as one model request
(seconds to a few minutes on the free tier). Progress is visible after every unit.

**Constraints**: at most one model request per unit; at most 20 requests per job by default;
temperature 0; the model sees the context only; no test is executed; automated tests make no real
model request.

**Scale/Scope**: jobs of tens of units. The free tier allows about 50 requests a day.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | How this plan complies |
|-----------|--------|------------------------|
| I. Feature 1 only, one module | PASS | New code is under `core_ai/services/test_generation/`. Existing files changed: `core_ai/ai_engine/llm_client.py` (add `call_model_ex`; `call_model` keeps its behaviour), `settings.py`. Both are in the list the constitution allows. |
| II. Trusted means proven | PASS | No record can become `ready`: there is no code path that sets it. Checked tests are `generated`, and the route that shows their code says they were not run. |
| III. Bounded, recorded LLM use | PASS | The model is reached only through `LLMFacade`, which is the only module allowed to import the client (checked by `test_boundaries.py`). Every call writes an attempt. One request per unit, no repair. The context is the only project data in the prompt. Tests use a fake model. |
| IV. Python + pytest first | PASS | Python-specific checks and rules stay in `languages/python_adapter.py`. The `LanguageAdapter` interface and its registry are added now, as promised in S1. |
| V. One shared graph | PASS | The graph is read as in S1. The planner stores each unit's direct callees and externals, so generation needs no new graph feature. |
| VI. Small slices, reviewed before code | PASS | Spec approved 2026-11-13. This plan and the task list are reviewed before code. |
| VII. Honest statuses, batch continues | PASS | Each record ends `generated` or `generation_failed` with a reason, or stays `pending` under a job that says why it stopped. One unit's failure never stops the others. |

Post-design re-check: no violation. Nothing to record under Complexity Tracking.

## Project Structure

### Documentation (this feature)

```text
specs/002-unit-test-generation/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/api.md
├── checklists/requirements.md
└── tasks.md             # created by /speckit-tasks
```

### Source Code (repository root)

```text
Ai_project/
├── core_ai/services/test_generation/
│   ├── records.py                 # NEW  RecordRepo + AttemptRepo (Mongo + in-memory)
│   ├── context.py                 # NEW  UnitContext: what the model is allowed to see
│   ├── llm_facade.py              # NEW  the only door to the model; records every call
│   ├── generation.py              # NEW  one generation pass = one unit
│   ├── assembler.py               # NEW  test path, file header, final test text
│   ├── prompts/
│   │   ├── __init__.py            # NEW
│   │   └── unit.py                # NEW  system + user templates, PROMPT_VERSION
│   ├── strategies/
│   │   ├── __init__.py            # NEW
│   │   ├── base.py                # NEW  TestKindStrategy (abstract)
│   │   └── unit.py                # NEW  UnitStrategy
│   ├── validation/
│   │   ├── __init__.py            # NEW
│   │   ├── validator.py           # NEW  extract code, parse, imports, naming, weak test
│   │   └── safety_lint.py         # NEW  network / process / eval / sleep / writes
│   ├── languages/
│   │   ├── base.py                # NEW  LanguageAdapter interface + registry
│   │   └── python_adapter.py      # CHANGED  import statement, allowed imports, entry lookup
│   ├── planner.py                 # CHANGED  units also carry their externals
│   ├── runner.py                  # CHANGED  planning can hand over to generation
│   ├── tasks.py                   # CHANGED  runs the generation phase, one unit per pass
│   ├── statuses.py                # CHANGED  RecordStatus, stage `generating`, reason codes
│   ├── serializers.py             # CHANGED  records list, record detail, `generated` counter
│   ├── views.py                   # CHANGED  two record routes
│   ├── urls.py                    # CHANGED  two routes
│   ├── staleness.py               # unchanged (already covers a running job that stops)
│   └── tests/
│       ├── fakes.py               # NEW  scripted fake model
│       ├── test_records.py
│       ├── test_context.py
│       ├── test_llm_facade.py
│       ├── test_validator.py
│       ├── test_safety_lint.py
│       ├── test_assembler.py
│       ├── test_unit_strategy.py
│       ├── test_generation.py
│       ├── test_api_records.py
│       ├── test_boundaries.py     # CHANGED  only llm_facade may import the client
│       └── reports/s2_unit_generation.md   # Arabic report (written at acceptance)
│
├── core_ai/ai_engine/llm_client.py     # CHANGED  + call_model_ex, + LLMUnavailable
└── Ai_project/settings.py              # CHANGED  5 settings
```

**Structure Decision**: same app, same style as S1 — logic in plain functions that receive their
storage and their model, so the whole slice runs in tests with in-memory storage and a fake model.

### Changes to existing files outside `core_testing`

| File | Change |
|------|--------|
| `core_ai/ai_engine/llm_client.py` | Add `call_model_ex(...)`, which returns the text **and** the model name and token counts, and accepts `max_tokens`. Add `LLMUnavailable(Exception)`, raised where the client today raises a plain `Exception` when every model is busy. `call_model` keeps its signature, its cache and its return value; it is rewritten to call the same inner loop. |
| `Ai_project/Ai_project/settings.py` | `TEST_RECORDS_COLLECTION`, `TEST_ATTEMPTS_COLLECTION`, `TESTGEN_MAX_REQUESTS_PER_JOB = 20`, `TESTGEN_LLM_MAX_TOKENS = 4000`, `TESTGEN_LLM_MODEL = None` (None = the client's own order). |

The change to `llm_client.py` touches code that conflict detection uses. It is guarded by running
the whole existing suite, and by new tests that pin `call_model`'s behaviour (text returned, cache
hit, exception type still an `Exception`).

### Flow of one job in this slice

```text
advance_job(job_id)                           one short pass, then re-enqueue if not done

  phase A — planning (S1, unchanged)
      ... gate → graph → plan ...
      when no file is waiting:
          create one record per (unit, level)          status: pending
          stage → generating            (was: status completed / stage planned)

  phase B — generation, ONE unit per pass
      1. pick the next pending record of level `unit`
            none left → finish:
                any generation_failed → completed_with_issues
                else                  → completed
      2. job's request count ≥ limit → stop: completed_with_issues, request_limit_reached
      3. build the context (unit, class, callee signatures, externals)
      4. stored answer for the same context + prompt version?
            yes → reuse it, no request spent
            no  → LLMFacade.complete()                  attempt recorded, request count + 1
                  model unavailable → stop: completed_with_issues, model_unavailable
                                      (the record stays pending)
      5. validate: extract → parse → imports → safety → weak test → rename
            ok   → record: generated, test_path, test_code
            fail → record: generation_failed, reason
      6. update progress → re-enqueue
```

`edge` and `integration` records are created `pending` and are not touched.

## Complexity Tracking

No violation to justify.
