# Implementation Plan: S1 — Test Job and Plan (no LLM)

**Branch**: `feature/core-testing` | **Date**: 2026-11-13 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-test-job-plan/spec.md`

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

A signed-in user starts a test job for a project version and reads back a plan: the functions and
methods that will be tested and everything that was skipped, with reasons. No test is generated
and no language model is called.

Technical approach: a new Django app `core_testing` inside the existing AI service, beside
`core_ai`. It is not a new microservice. One Celery task advances a job in short, non-blocking
passes: resolve scope → analysis gate per file → build the project graph from stored analysis →
plan → save the plan inside the job. Three JWT-protected routes expose the job and the plan. All
data about code comes from what analysis already stores; one new Mongo collection (`test_jobs`)
is added.

## Technical Context

**Language/Version**: Python 3.10 (the `ai_web` Docker image)

**Primary Dependencies**: Django 4.2, Django REST Framework 3.17, djangorestframework-simplejwt
5.5 (token decoding only), Celery 5.6 with Redis, PyMongo 4.17. No new dependency is added.

**Storage**: MongoDB. New collection `test_jobs`. Read-only use of `project_versions`,
`code_files` and `analysis_results`.

**Testing**: pytest, run inside the `ai_web` image with no database and no network. Storage and
analysis readers have in-memory implementations for tests.

**Target Platform**: Linux containers (docker compose): `ai_web` for the API, the existing
`celery_worker` for the background task.

**Project Type**: web service (one Django app added to an existing service)

**Performance Goals**: start request answered in under 2 s; plan of the sample project readable
within 10 s when analysis already exists.

**Constraints**: zero LLM calls; a Celery task never waits on another task; no change to analysis,
explanation or conflict detection; tests make no real LLM call and need no database.

**Scale/Scope**: senior-project scale — projects of tens of files, hundreds of units; one job at
a time per user is enough.

## Architecture

```text
Client (Web App)
      │
API Gateway (nginx)
      │
      ├── User & Project Service ── SQL            login, projects, JWT
      │
      ├── Code Intelligence Service (Ai_project) ── NoSQL (Mongo + GridFS)
      │     ├── core_ai                 analysis, logical explanation, conflict detection
      │     └── core_testing            test generation            ← this feature
      │           reads core_ai's stored analysis; never the reverse
      │
      └── Notification Service
```

Dependency rules:

1. `core_testing` reads what `core_ai` stores and may call its analysis task.
2. `core_testing` imports nothing from conflict detection or the explanation engine.
3. Nothing in `core_ai` imports from `core_testing`.
4. Only `core_testing` writes to the `test_*` collections.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | How this plan complies |
|-----------|--------|------------------------|
| I. Feature 1 only, one module | PASS | All new code is under `Ai_project/core_ai/services/test_generation/`. Three existing files change, each by a few lines (listed below). The four dependency rules above are checked by a test. |
| II. Trusted means proven | N/A in S1 | No record can become `ready` in this slice: there is no sandbox and no acceptance gate yet. Work items stay `pending`. |
| III. Bounded, recorded LLM use | PASS | `core_testing` imports no LLM client in this slice. A test asserts it, and another blocks `LLMClient.call_model` during a full job run. |
| IV. Python + pytest first | PASS | Non-Python files are skipped with `unsupported_language`. Unit extraction sits in `languages/python_adapter.py`. The adapter interface and registry are deferred to the slice that adds generation (see Complexity Tracking). |
| V. One shared graph | PASS | The stored graph is read, never rewritten. Additions live in `core_ai/services/test_generation/graphify/` and keep the nodes / edges / meta shape. Only additions 1, 5, 6, 7 are built now. |
| VI. Small slices, reviewed before code | PASS | Spec approved 2026-11-13. This plan and the task list are reviewed before any code. Out-of-scope list is explicit in the spec. |
| VII. Honest statuses, batch continues | PASS | Every skip carries one of six reason codes. A failed or skipped file never stops the job. |

Post-design re-check (after Phase 1): no new violation. One simplification against principle IV
is recorded under Complexity Tracking.

## Project Structure

### Documentation (this feature)

```text
specs/001-test-job-plan/
├── plan.md              # This file
├── research.md          # Decisions and their reasons
├── data-model.md        # test_jobs document + what is read from existing collections
├── quickstart.md        # How to try S1 end to end (Postman)
├── contracts/
│   └── api.md           # The three routes: request, response, errors
├── checklists/
│   └── requirements.md
└── tasks.md             # Created by /speckit-tasks, not by this plan
```

### Source Code (repository root)

```text
Ai_project/
├── core_ai/services/test_generation/                      # NEW app
│   ├── __init__.py
│   ├── apps.py                        # app config
│   ├── urls.py                        # the three routes
│   ├── views.py                       # thin DRF views
│   ├── serializers.py                 # request validation, response shaping
│   ├── auth.py                        # UPM token check + job ownership
│   ├── errors.py                      # error codes and the common error body
│   ├── statuses.py                    # JobStatus, JobStage, FileStatus, SkipReason
│   ├── repo.py                        # JobRepo: Mongo + in-memory
│   ├── readers.py                     # AnalysisReader: Mongo + in-memory (read-only)
│   ├── scope.py                       # version, files, levels; 400 / 422
│   ├── gate.py                        # per-file analysis gate (pure decision logic)
│   ├── planner.py                     # units, skips, work-item count
│   ├── runner.py                      # one pass of a job: scope → gate → graph → plan
│   ├── tasks.py                       # Celery task: runs a pass, re-enqueues if waiting
│   ├── graphify/
│   │   ├── __init__.py
│   │   ├── loader.py                  # stored graph + units + imports of one file
│   │   ├── merge.py                   # file-qualified ids, project graph
│   │   ├── resolver.py                # local call resolution
│   │   └── queries.py                 # direct callees of a unit
│   ├── languages/
│   │   ├── __init__.py
│   │   └── python_adapter.py          # unit inventory + skip rules for Python
│   └── tests/
│       ├── __init__.py
│       ├── conftest.py                # django.setup(), LLM block, shared fakes
│       ├── fixtures/sources/          # game.py, two-file project, edge-case files
│       ├── helpers.py                 # builds stored-analysis dicts with the real processor
│       ├── test_auth.py
│       ├── test_scope.py
│       ├── test_gate.py
│       ├── test_graphify_merge.py
│       ├── test_graphify_resolver.py
│       ├── test_python_adapter.py
│       ├── test_planner.py
│       ├── test_runner.py
│       ├── test_api.py
│       ├── test_boundaries.py         # no LLM import, no import from other features
│       └── reports/s1_job_and_plan.md # Arabic report (written at acceptance)
│
├── Ai_project/settings.py             # CHANGED: app in INSTALLED_APPS + 4 settings
└── Ai_project/urls.py                 # CHANGED: one include line

docker-compose.yml                     # CHANGED: one env line for ai_web
```

**Structure Decision**: one new Django app, flat modules, two small sub-packages (`graphify`,
`languages`). Views are thin; all logic is in plain functions that take a repo and a reader, so
the whole slice is testable without Mongo, Redis or Celery.

### Changes to existing files

| File | Change |
|------|--------|
| `Ai_project/Ai_project/settings.py` | Add `'core_testing'` to `INSTALLED_APPS`. Add `TEST_JOBS_COLLECTION`, `TESTGEN_JWT_SIGNING_KEY` (from env `UPM_JWT_SIGNING_KEY`), `TESTGEN_GATE_POLL_SECONDS` (5), `TESTGEN_GATE_MAX_WAIT_SECONDS` (600). |
| `Ai_project/Ai_project/urls.py` | Add `path('api/analysis/tests/', include('core_testing.urls'))` before the `core_ai` include. |
| `docker-compose.yml` | Add `UPM_JWT_SIGNING_KEY=${UPM_DJANGO_SECRET_KEY}` to the `ai_web` environment. |

Nothing in `core_ai` changes. `core_testing` calls the existing `analyze_code_file_task` to request
a missing analysis; it does not modify it.

### Flow of one job

```text
POST jobs/  ──►  scope.resolve()  ──►  save job (pending)  ──►  enqueue advance_job  ──►  202
                 400 / 422 here

advance_job(job_id)                      one short pass, never blocks
  1. gate: for each selected Python file
        COMPLETED            → ready
        PENDING / IN_PROGRESS → waiting
        none / FAILED        → request analysis (max 2 requests) → waiting
        FAILED after 2 requests, or past the deadline → skipped: analysis_failed
  2. ready files → loader → merge → resolver → project graph
  3. planner → units, skips, work-item count → saved inside the job
  4. any file still waiting?
        yes → stage waiting_analysis (or planning), re-enqueue with countdown
        no  → status completed, stage planned     (failed if no file could be analysed)
```

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| Principle IV asks for language logic behind a `LanguageAdapter` interface; S1 ships only `languages/python_adapter.py` with plain functions and no interface or registry. | The owner and the backend lead asked for the minimum structure S1 needs; full Strategy and Adapter patterns arrive with generation. | Building the interface now would define methods (`validate`, `run_argv`, `parse_results`) that nothing calls until S2 and S3. The Python-specific code is still isolated in one module, so adding the interface later moves no logic. |
