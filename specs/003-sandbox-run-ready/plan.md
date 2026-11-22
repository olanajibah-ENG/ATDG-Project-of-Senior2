# Implementation Plan: S3 — Isolated Run, Acceptance Gate, Coverage and Bundle

**Branch**: `feature/core-testing` | **Date**: 2026-11-20 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/003-sandbox-run-ready/spec.md`

## Summary

After generation, the job goes on by itself into a run stage. Each `generated` record is run with
pytest in a fresh container (no network, read-only code, 1 CPU, 512 MB, 128 processes, 60 s,
non-root, no privileges). The outcome is read from `junit.xml` and the exit code; the **acceptance
gate** alone sets `ready`, with evidence. Then every `ready` test runs once more, together, and that
all-pass run gives the official coverage. Two new routes return the coverage report and a ZIP bundle.

Technical approach: a new Celery worker on its own queue `test_sandbox` is the only component with
the Docker socket; it has no keys. It runs **one record per pass** (same rule as S1/S2) through a
`SandboxExecutor` adapter (`DockerSandboxExecutor` for real, `FakeSandboxExecutor` in tests). Files
reach the read-only container through named volumes filled by a short-lived loader container. One
new collection, `test_runs`.

## Technical Context

**Language/Version**: Python 3.10 (the `ai_web` image); run image `python:3.10-slim` + pytest 8.3.3 +
pytest-cov 5.0.0.

**Primary Dependencies**: as in S2, plus the Docker SDK for Python (`docker==7.1.0`) in the `Ai_project`
image (used only by the sandbox worker).

**Storage**: MongoDB. New collection `test_runs`. `test_records` and `test_jobs` gain fields. Project
files read from GridFS (read-only).

**Testing**: pytest in the `ai_web` image, no database, no model, **no container**: the executor is
replaced by `FakeSandboxExecutor`; the real executor's container options are checked against a
recording stand-in for the SDK client.

**Target Platform**: Docker Compose on the development machine (Docker Engine 29, cgroup v2). New
services: `testgen_sandbox_worker` (Celery, queue `test_sandbox`, Docker socket, no keys) and
`testgen_sandbox_image` (build only).

**Project Type**: web service (`core_ai` grows).

**Performance Goals**: one record run ≈ 1–3 s of container time plus start-up; 5 records + final run
under 3 minutes (SC-007).

**Constraints**: runs isolated as FR-005; no secret in the run; no dependency installation; `ready`
written only by the acceptance gate; coverage only from the final all-pass run; automated tests start
no container and make no model call.

**Scale/Scope**: jobs of tens of records; at most 2 runs at the same time (worker concurrency).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | How this plan complies |
|-----------|--------|------------------------|
| I. Feature 1 only, one module | PASS | New code under `core_ai/services/test_generation/` (`sandbox/`, `acceptance.py`, `coverage.py`, `bundle.py`); entry files in `views/`, `serializers/`, `celery_tasks/`, `models/` as before. Outside the package: `settings.py`, `docker-compose.yml`, `requirements.txt` — infrastructure only. No import from another feature (checked by `test_boundaries.py`). |
| II. Trusted means proven (NON-NEGOTIABLE) | PASS | `ready` is set in one function, `acceptance.accept()`, only after a clean run with the network off on the job's version, and always with evidence (run id, version number, body hash). A boundary test checks no other module writes `ready`. Coverage is taken only from the final all-pass run. Notices say a passing test proves it runs on this version, not that the code is correct. |
| III. Bounded, recorded LLM use | PASS | S3 makes no model call. The sandbox worker has no model key. |
| IV. Python + pytest first | PASS | `run_argv()` and `parse_results()` are added to the `LanguageAdapter` interface and implemented in `PythonAdapter`; the executor stays language-neutral. |
| V. One shared graph | PASS | Not touched. The plan's skip reasons annotate uncovered lines. |
| VI. Small slices, reviewed before code | PASS | Spec approved 2026-11-20; plan and tasks reviewed before code. |
| VII. Honest statuses, batch continues | PASS | Every run record ends `ready`, `test_failed` or `environment_error` with a reason from a closed list; a failing or broken run never stops the other records; the job ends `completed_with_issues` when anything did not pass. |

Constitution rules on the sandbox ("test runs have the network off, a read-only filesystem and limits
on CPU, memory, time and process count"; "keys … never passed into the sandbox") are met by R4 and R1.
The constitution's "install runs with the network on" does not apply: this slice installs nothing.

Post-design re-check: no violation. Nothing under Complexity Tracking.

## Project Structure

### Documentation (this feature)

```text
specs/003-sandbox-run-ready/
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
│   ├── sandbox/
│   │   ├── __init__.py
│   │   ├── executor.py          # NEW  SandboxExecutor interface, RunSpec, RunOutput
│   │   ├── docker_executor.py   # NEW  DockerSandboxExecutor: volumes, loader, run, collect, clean up
│   │   ├── fake_executor.py     # NEW  FakeSandboxExecutor (scripted outcomes) — used by tests
│   │   ├── workspace.py         # NEW  version files from GridFS → tar; test files + pytest.ini → tar
│   │   └── image/Dockerfile     # NEW  autotest-sandbox:py3.10-s3
│   ├── results.py               # NEW  junit.xml + cov.json reading (size-capped), verdict table (R5, R7)
│   ├── acceptance.py            # NEW  the ONLY writer of `ready`: accept() with evidence; reject()
│   ├── run_stage.py             # NEW  one sandbox pass = one record; final run; finish the job
│   ├── coverage.py              # NEW  coverage report + per-record contribution + plan annotations
│   ├── bundle.py                # NEW  ZIP in memory (MANIFEST, junit, coverage, plan, summary, tests)
│   ├── runs.py                  # NEW  RunRepo (`test_runs`, Mongo + in-memory)
│   ├── languages/base.py        # CHANGED  + run_argv(), parse_results()
│   ├── languages/python_adapter.py  # CHANGED  pytest argv, top-level project names (R7)
│   ├── generation.py            # CHANGED  end of generation hands over to the run stage
│   ├── records.py               # CHANGED  run fields, evidence (set only via acceptance)
│   ├── statuses.py              # CHANGED  stages sandbox_run/final_run, run reason codes
│   └── validation/safety_lint.py    # CHANGED  + os._exit, sys.exit, os.kill, signal, writes to /out (R6)
├── core_ai/celery_tasks/testgen_tasks.py   # CHANGED  + sandbox_pass task (queue test_sandbox)
├── core_ai/serializers/testgen_serializer.py   # CHANGED  run details, notices, coverage, job coverage
├── core_ai/views/testgen_views.py          # CHANGED  + coverage view, + bundle view
├── core_ai/urls.py                          # CHANGED  + 2 routes
├── core_ai/models/testgen.py                # CHANGED  run document builder
├── core_ai/tests/test_generation/
│   ├── test_results.py          # NEW  junit/cov parsing, every row of the verdict table
│   ├── test_acceptance.py       # NEW  ready only with evidence; reject paths
│   ├── test_run_stage.py        # NEW  one record per pass, hand-over, final run, fails_with_others
│   ├── test_coverage.py         # NEW  report, annotations, contribution, no-ready case
│   ├── test_bundle.py           # NEW  content, only ready tests, manifest hashes, 409
│   ├── test_docker_executor.py  # NEW  exact container options via a recording SDK stand-in
│   ├── test_workspace.py        # NEW  version files → tar, paths, deleted files excluded
│   ├── test_api_sandbox.py      # NEW  record detail, coverage and bundle routes, access rules
│   ├── test_validator.py        # CHANGED  new lint rules
│   └── test_boundaries.py       # CHANGED  only acceptance.py writes `ready`; docker imported only by docker_executor.py
├── core_ai/tests/reports/testgen_s3_sandbox_run.md  # Arabic report (at acceptance)
├── Ai_project/settings.py                   # CHANGED  TESTGEN_SANDBOX_*, TEST_RUNS_COLLECTION, task route
└── requirements.txt                         # CHANGED  docker==7.1.0
docker-compose.yml                           # CHANGED  testgen_sandbox_worker, testgen_sandbox_image
```

**Structure Decision**: same style as S1/S2 — logic in plain functions that receive their storage and
their executor, so the whole run stage is tested in memory with the fake executor.

### Changes to existing files outside the package

| File | Change |
|------|--------|
| `docker-compose.yml` | `testgen_sandbox_image`: `build: Ai_project/core_ai/services/test_generation/sandbox/image`, `image: autotest-sandbox:py3.10-s3`, `command: ["true"]`, `restart: "no"`. `testgen_sandbox_worker`: same build as `celery_worker`, `command: celery -A Ai_project.celery_app worker -Q test_sandbox --concurrency 2 -l INFO`, volume `/var/run/docker.sock:/var/run/docker.sock`, environment = database/Redis/Mongo settings only (no `OPENROUTER_API_KEY`, no `UPM_JWT_SIGNING_KEY`), `depends_on` mongodb + redis. |
| `Ai_project/Ai_project/settings.py` | settings of research R12 and `CELERY_TASK_ROUTES` for `core_ai.testgen.sandbox_pass`. |
| `Ai_project/requirements.txt` | `docker==7.1.0`. |

The existing `celery_worker` is unchanged (it does not consume `test_sandbox` and has no socket).

### Flow of one job in this slice

```text
advance_job (default queue)              … planning → generation (S1, S2 unchanged) …
  generation finds no pending unit record:
      stage → sandbox_run ; enqueue sandbox_pass(job)          (was: finish the job)

sandbox_pass(job)  (queue test_sandbox, ONE record per pass)
  1. first pass: build the job's source volume from the version's files (GridFS)  → job.sandbox.src_volume
  2. pick the next `generated` record
        none left → go to 5
  3. executor.run(RunSpec(tests=[record test], timeout=60, …)) → RunOutput
        cannot start → verdict environment_error / sandbox_unavailable
  4. results.verdict(output, expected names, project top-level names)
        ready-able → acceptance.accept(record, run, evidence)        → ready
        otherwise  → acceptance.reject(record, run, status, reason)  → test_failed | environment_error
     store run (test_runs) ; update progress ; re-enqueue
  5. stage → final_run: run all `ready` tests together with coverage
        a test fails → that record: test_failed / fails_with_others ; repeat without it
        all pass     → coverage.report(run) → job.coverage, job.final_run_id
  6. remove the job's source volume ; finish: completed (all run records ready) | completed_with_issues
```

## Complexity Tracking

No violation to justify. Known limit written down: a test that deliberately forges `junit.xml` and
exits before pytest is caught only by the lint and the final run (research R6); full protection needs
a second user or a separate runner host, outside this slice.
