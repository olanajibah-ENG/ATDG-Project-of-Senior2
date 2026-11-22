---

description: "Task list for S3 — Isolated Run, Acceptance Gate, Coverage and Bundle"
---

# Tasks: S3 — Isolated Run, Acceptance Gate, Coverage and Bundle

**Input**: Design documents from `/specs/003-sandbox-run-ready/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/api.md, quickstart.md

**Tests**: included (the constitution requires tests for every slice). No automated test may start a
container or call the model; the run uses `FakeSandboxExecutor`.

**Organization**: tasks are grouped by user story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: US1 … US5
- Paths are relative to the repository root; `TG` = `Ai_project/core_ai/services/test_generation`,
  `TT` = `Ai_project/core_ai/tests/test_generation`

---

## Phase 1: Setup (Shared Infrastructure)

- [X] T001 Add settings to `Ai_project/Ai_project/settings.py`: `TEST_RUNS_COLLECTION = 'test_runs'`, `TESTGEN_SANDBOX_IMAGE = 'autotest-sandbox:py3.10-s3'`, `TESTGEN_SANDBOX_TIMEOUT_SECONDS = 60`, `TESTGEN_SANDBOX_FINAL_MAX_SECONDS = 300`, `TESTGEN_SANDBOX_MEMORY = '512m'`, `TESTGEN_SANDBOX_PIDS = 128`, `TESTGEN_SANDBOX_OUTPUT_LIMIT = 20000`, and `CELERY_TASK_ROUTES = {'core_ai.testgen.sandbox_pass': {'queue': 'test_sandbox'}}` (merge with any existing routes)
- [X] T002 [P] Add `docker==7.1.0` to `Ai_project/requirements.txt`
- [X] T003 [P] Create `TG/sandbox/__init__.py` and `TG/sandbox/image/Dockerfile`: `FROM python:3.10-slim`; `pip install --no-cache-dir pytest==8.3.3 pytest-cov==5.0.0`; `groupadd -g 10001 sbx && useradd -u 10001 -g 10001 -M sbx`; `mkdir -p /workspace/src /workspace/tests /out && chown 10001:10001 /out`; `WORKDIR /workspace`; `ENV PYTHONDONTWRITEBYTECODE=1`; `USER 10001:10001`
- [X] T004 [P] Add to `docker-compose.yml`: service `testgen_sandbox_image` (`build: ./Ai_project/core_ai/services/test_generation/sandbox/image`, `image: autotest-sandbox:py3.10-s3`, `command: ["true"]`, `restart: "no"`); service `testgen_sandbox_worker` (same `build` as `celery_worker`, `command: celery -A Ai_project.celery_app worker -Q test_sandbox --concurrency 2 -l INFO`, `volumes: ["/var/run/docker.sock:/var/run/docker.sock"]`, the Mongo/Redis/Django settings `celery_worker` has **minus** `OPENROUTER_API_KEY` and `UPM_JWT_SIGNING_KEY`, same networks, `depends_on` mongodb and redis)
- [X] T005 [P] Create `TT/fake_sandbox.py`: `FakeSandboxExecutor(script)` implementing the executor interface; `script` maps a test path (or `"final"`) to a scripted `RunOutput` (exit code, junit text, cov json, output, `start_error`); records every `RunSpec` it receives; helpers `junit_pass(names)`, `junit_fail(names, failing, message)`, `junit_collection_error(message)`, `cov_json(files)` that build realistic `junit.xml` / coverage-JSON (format 3) text

---

## Phase 2: Foundational (Blocking Prerequisites)

**⚠️ CRITICAL**: no user story work starts before this phase is complete

- [X] T006 [P] Extend `TG/statuses.py`: `JobStage.SANDBOX_RUN = "sandbox_run"`, `JobStage.FINAL_RUN = "final_run"`; `RunReason` = `assertion`, `collection_error`, `no_tests`, `skipped_test`, `timeout`, `fails_with_others`, `missing_dependency`, `sandbox_unavailable`, `no_result_file`; `RUN_FAILED_REASONS` (the six `test_failed` ones) and `RUN_ENV_REASONS` (the three `environment_error` ones)
- [X] T007 [P] Create `TG/sandbox/executor.py`: dataclasses `RunSpec(run_id, job_id, src_volume, test_files: dict[path, bytes], test_paths: list[str], timeout_s, with_coverage=True)` and `RunOutput(run_id, started, exit_code, timed_out, junit_xml, cov_json, output, start_error)`; abstract `SandboxExecutor` with `prepare_source(job_id, files: dict[path, bytes]) -> volume`, `run(spec) -> RunOutput`, `discard_source(volume)`; providers `get_executor()` / `set_executor()`
- [X] T008 [P] Create `TG/runs.py`: `new_run(...)` with the fields of data-model.md (`test_runs`), `RunRepo` in-memory + Mongo (`settings.TEST_RUNS_COLLECTION`, unique index `run_id`, index (`job_id`, `kind`)), providers `get_run_repo()` / `set_run_repo()`; add a `runs` fixture and an autouse `set_executor(FakeSandboxExecutor({}))` fixture to `TT/conftest.py`
- [X] T009 [P] Extend `TG/records.py`: `next_generated(job_id)` (stable order, level `unit`), `set_run_result(record_id, run_id, run_result)`, and the two write paths used ONLY by acceptance: `_mark_ready(record_id, evidence, contribution)` and `_mark_failed(record_id, status, reason, detail)`; extend `TT/test_records.py` for `next_generated` and the new fields
- [X] T010 Extend `TG/languages/base.py` and `TG/languages/python_adapter.py`: `run_argv(test_paths, timeout_s, with_coverage)` → `["timeout","--signal=KILL",str(timeout_s),"python","-m","pytest",*test_paths,"-q","-p","no:cacheprovider","--junitxml=/out/junit.xml"]` + (`"--cov=/workspace/src","--cov-branch","--cov-report=json:/out/cov.json"` when `with_coverage`); `top_level_names(project_paths)` (`demo/course.py` → `demo`, `game.py` → `game`); `expected_test_names(test_code)` (names of top-level `test_*` functions)
- [X] T011 [P] Write `TT/test_results.py` for `results.py`: junit parsing (passed / failure with message / error / skipped; a file over 1 MB or not XML → unreadable); coverage-JSON reduction (paths under `/workspace/src/` made relative; per-file statements, covered, branches, missing lines); and **every row** of the verdict table of research R5, including: exit 137 → `timeout`; missing file → `no_result_file`; `No module named 'requests'` with project names `{demo}` → `missing_dependency` (detail `requests`); `No module named 'demo.nope'` → `collection_error`; exit 5 → `no_tests`; a failure → `assertion` with the first message; a skip → `skipped_test`; exit 0 with all expected names passed → acceptable; exit 0 but a name missing → `no_result_file`
- [X] T012 Create `TG/results.py`: `parse_junit(text) -> list[{name, outcome, message}] | None` (stdlib `xml.etree.ElementTree`, 1 MB cap), `reduce_coverage(cov_json_text) -> dict | None`, `verdict(output: RunOutput, expected_names, project_names) -> Verdict(status, reason, detail, tests)` implementing research R5/R7 in order
- [X] T013 [P] Write tests for the new lint rules in `TT/test_validator.py`: `os._exit(0)`, `sys.exit()`, `os.kill(...)`, `import signal`, `open("/out/junit.xml", "w")` are each refused with `unsafe_code`
- [X] T014 Extend `TG/validation/safety_lint.py`: forbid calls `os._exit`, `sys.exit`, `os.kill`, `os.abort`; import root `signal`; any `open(..., "w"/"a"/"x")` or `Path(...).write_*` whose target text contains `/out` or `junit`

**Checkpoint**: foundation ready — the whole existing suite still passes

---

## Phase 3: User Story 1 - Every generated test is really run, and only passing ones become `ready` (Priority: P1) 🎯 MVP

**Goal**: after generation the job runs each `generated` record, one per pass; only the acceptance
gate sets `ready`, with evidence.

**Independent Test**: with `FakeSandboxExecutor`, a job of 5 `generated` records ends with each record
`ready` (with evidence) or failed with a reason; a scripted failing run never becomes `ready`.

### Tests for User Story 1 ⚠️

- [X] T015 [P] [US1] Write `TT/test_acceptance.py`: `accept()` sets `ready` and stores evidence `{run_id, version_number, body_hash, test_sha256, tests, passed, duration_s, accepted_at}`; `accept()` refuses a verdict that is not acceptable; `reject()` sets `test_failed` / `environment_error` with reason and detail and clears any evidence; a record already `ready` that is rejected with `fails_with_others` loses its evidence
- [X] T016 [P] [US1] Write `TT/test_run_stage.py`: generation end hands over (stage `sandbox_run`, sandbox pass enqueued, job not finished); one pass runs exactly one record; records `generation_failed` / `pending` are never run; the source volume is prepared once per job and discarded at the end; a record whose run cannot start → `environment_error / sandbox_unavailable` and the next record still runs; progress counts update after each pass; finish: `completed` when every run record is `ready`, else `completed_with_issues`; a job with no `generated` record → `completed_with_issues` without any run
- [X] T017 [P] [US1] Extend `TT/test_boundaries.py`: no module except `TG/acceptance.py` (and `records.py`'s private writers it calls) writes the value `"ready"` into a record; only `TG/sandbox/docker_executor.py` imports `docker`

### Implementation for User Story 1

- [X] T018 [US1] Create `TG/acceptance.py`: `accept(record, run, verdict, job, contribution)` → only when `verdict.status == "ready"`; builds evidence (`test_sha256` = SHA-256 of the stored `test_code`) and calls `records._mark_ready`; `reject(record, run, verdict)` → `records._mark_failed`
- [X] T019 [US1] Create `TG/run_stage.py` → `run_sandbox_pass(job_id, repo, record_repo, run_repo, reader, executor, now) -> PassResult`: first pass reads the version's files (`reader.files_of_version` + GridFS content via `workspace.py`) and calls `executor.prepare_source`; then picks `record_repo.next_generated(job_id)`; builds `RunSpec` (test file at its `test_path`, plus `pytest.ini` with `pythonpath = /workspace/src`), runs it, stores the run (`test_runs`), computes the verdict with `results.verdict(...)`, calls `acceptance.accept` or `acceptance.reject`, updates progress; returns `done=False` while records remain (final run is US4)
- [X] T020 [US1] Create `TG/sandbox/workspace.py`: `version_files(reader, job) -> dict[path, bytes]` (one file per path, deleted excluded, content from GridFS), `record_test_files(record) -> dict[path, bytes]` (the test file + `tests/pytest.ini`), `to_tar(files, uid=10001, mode=0o644) -> bytes`; write `TT/test_workspace.py` (paths kept, deleted files excluded, a path with two stored files from an incremental upload yields only the newest one, a file of a later version never appears, tar members owned by 10001)
- [X] T021 [US1] Change `TG/generation.py`: when no `pending` unit record is left, instead of finishing the job set stage `sandbox_run` and return a result that tells the task to hand over (generation stop reasons `model_unavailable` / `request_limit_reached` still finish the job as today, but already `generated` records are run first)
- [X] T022 [US1] Change `Ai_project/core_ai/celery_tasks/testgen_tasks.py`: new task `core_ai.testgen.sandbox_pass(job_id)` calling `run_sandbox_pass` with `get_executor()`, re-enqueueing itself while not done; `advance_job` enqueues `sandbox_pass` when generation hands over
- [X] T023 [US1] Change `Ai_project/core_ai/serializers/testgen_serializer.py` and `TG/statuses.py` use: record detail adds `executed`, `run` (`run_id`, `exit_code`, `duration_s`, `tests`, `output`), `evidence`, `coverage_contribution`; `test_code` shown for `ready`, `test_failed`, `environment_error` too; `notice` per status as in contracts/api.md; job status shows stages `sandbox_run` / `final_run`
- [X] T024 [US1] Extend `TT/test_api_records.py`: detail of a `ready` record (evidence, executed true, notice "run … and passed"); of a `test_failed` record (per-test messages, no evidence); of a `generated` record (unchanged S2 notice)

**Checkpoint**: with the fake executor, a whole job runs end to end and only passing records are `ready`

---

## Phase 4: User Story 2 - The run is isolated and bounded (Priority: P1)

**Goal**: the real executor starts each run with exactly the isolation options and leaks nothing.

**Independent Test**: `TT/test_docker_executor.py` passes with a recording stand-in for the SDK; the
quickstart's isolation table holds on the real engine.

### Tests for User Story 2 ⚠️

- [X] T025 [P] [US2] Write `TT/test_docker_executor.py` with a recording fake of the `docker` client (no engine): the run container is created with `image=settings.TESTGEN_SANDBOX_IMAGE`, `network_mode="none"`, `read_only=True`, `tmpfs={"/tmp": "rw,size=64m"}`, `nano_cpus=1_000_000_000`, `mem_limit="512m"`, `memswap_limit="512m"`, `pids_limit=128`, `cap_drop=["ALL"]`, `security_opt=["no-new-privileges"]`, `user="10001:10001"`, `environment` exactly `{"PYTHONPATH": "/workspace/src", "PYTHONDONTWRITEBYTECODE": "1", "COVERAGE_FILE": "/tmp/.coverage"}` (the third added while implementing: the working directory is read-only), volumes src and tests `ro` and out `rw`, `command` = `run_argv(...)`; the loader container is never started and is removed; the wait is bounded (timeout + 15 s) and an overrun kills the container and reports `timed_out`; `/out` is read with `get_archive`; the run container and the per-run volumes are always removed (also after an exception); a `docker` error at create/start returns `RunOutput(start_error=...)`

### Implementation for User Story 2

- [X] T026 [US2] Create `TG/sandbox/docker_executor.py` → `DockerSandboxExecutor(client=None)`: `prepare_source` (named volume `sbx_<job>_src`, filled through a loader container + `put_archive`), `run(spec)` (volumes `<run>_tests`, `<run>_out`; loader fills tests and creates `/out` owned by 10001; run container with the options of T025; bounded wait; collect `/out/junit.xml`, `/out/cov.json` and logs cut to `TESTGEN_SANDBOX_OUTPUT_LIMIT`; clean up in `finally`), `discard_source(volume)`; make it the default of `get_executor()` (tests override it)
- [X] T027 [US2] Confirm `TG/sandbox/workspace.py` never puts anything but project files and tests into a volume, and that `RunSpec` carries no environment from the worker; add the assertion to `TT/test_workspace.py`

**Checkpoint**: the executor's options are pinned by a test; the real engine is used only at acceptance

---

## Phase 5: User Story 3 - The real reason for every failure (Priority: P2)

**Goal**: each failed record stores the machine-read reason and per-test outcomes.

**Independent Test**: one scripted run per failure kind ends with the status, reason and stored test
outcomes of FR-012/FR-013.

- [X] T028 [P] [US3] Extend `TT/test_run_stage.py`: one record per reason of FR-012 (scripted through the fake executor) ends with that status and reason; `run_result.tests` holds every test with its message; `missing_dependency` stores the module name in `reason_detail`; a scripted output larger than the limit is stored cut, the outcome unchanged
- [X] T029 [US3] Wire `results.verdict` project names into `run_stage.py` (`python_adapter.top_level_names` of the version's paths) and store `reason_detail` (first failure message, or missing module) in `acceptance.reject`
- [X] T030 [P] [US3] Extend `TT/test_api_records.py`: records list filtered by `status=test_failed` and `status=environment_error`; each item shows `executed` and the S3 `reason_code`

**Checkpoint**: every failure kind is recorded with its real reason

---

## Phase 6: User Story 4 - Coverage from the final all-pass run (Priority: P2)

**Goal**: after all records, one final run of every `ready` test gives the official coverage.

**Independent Test**: with the fake executor, the job's coverage equals the reduced coverage of the
last all-pass final run, which contained exactly the `ready` tests.

### Tests for User Story 4 ⚠️

- [X] T031 [P] [US4] Write `TT/test_coverage.py`: report shape of data-model.md (per-file and totals, `combined_pct`); an uncovered line inside a unit the plan skipped (`private`) carries that reason in `missing_annotations`; non-Python files listed in `not_measured` with `unsupported_language`; no `ready` record → `{"available": false, "reason": "no_ready_tests"}`; a record's contribution is labelled "this record's own run"
- [X] T032 [P] [US4] Extend `TT/test_run_stage.py`: after the last record the stage becomes `final_run`; the final `RunSpec` holds exactly the `ready` tests with coverage on and timeout `min(60 + 15 × n, 300)`; a test failing in the final run → its record `test_failed / fails_with_others`, a new final run without it; the job's `coverage` and `final_run_id` come from the all-pass run; the job's coverage is never taken from a per-record run

### Implementation for User Story 4

- [X] T033 [US4] Create `TG/coverage.py`: `job_report(reduced_cov, plan, analyses, version_paths)` and `record_contribution(reduced_cov)` per data-model.md (skip-reason annotation uses each skipped unit's `line_start`–`line_end` from the stored analysis)
- [X] T034 [US4] Extend `TG/run_stage.py`: final-run step with the `fails_with_others` loop (at most as many repeats as `ready` records); store `job.coverage` and `job.final_run_id`; store each `ready` record's contribution at acceptance; then discard the source volume and finish the job
- [X] T035 [US4] Add `GET jobs/{job_id}/coverage/` in `Ai_project/core_ai/views/testgen_views.py`, `Ai_project/core_ai/urls.py`, serializer in `testgen_serializer.py`: `200` report, `409 coverage_not_ready` before the job is final, raised through a new helper `errors.coverage_not_ready()` in `TG/errors.py` so the body is the shared `{"error": {"code", "message", "details"}}` (the test asserts the exact body); the view subclasses `JobApiView`, so the UPM token and the job-owner check apply unchanged; job status response gains `coverage` totals; tests in `TT/test_api_sandbox.py` (200, 409, 403 other user, 401 no token)

**Checkpoint**: coverage comes only from the final all-pass run

---

## Phase 7: User Story 5 - Download the trusted tests as one package (Priority: P3)

**Goal**: one ZIP with the `ready` tests and their results, coverage, plan, summary, config, manifest.

**Independent Test**: the bundle of a finished fake job has exactly the files of FR-025, only `ready`
tests, and a manifest whose hashes match.

- [X] T036 [P] [US5] Write `TT/test_bundle.py`: file list = `MANIFEST.json`, `junit_results.xml`, `coverage_report.json`, `plan.json`, `records_summary.json`, `pytest.ini`, `tests/generated/unit/<ready tests>`; no `test_failed` test inside; `records_summary` gives every record's status and reason; every `MANIFEST` SHA-256 matches its file; `pytest.ini` holds `pythonpath = src` and `-p no:cacheprovider`; no project source, no secret
- [X] T037 [US5] Create `TG/bundle.py`: `build_bundle(job, records, final_run, coverage_report) -> (filename, bytes)` with `zipfile` in memory; filename `<job_id>_<project>_v<version>.zip`
- [X] T038 [US5] Add `GET jobs/{job_id}/bundle/` in `testgen_views.py` and `urls.py`: `200 application/zip` with `Content-Disposition: attachment`, `409 bundle_not_ready` before the job is final, through `errors.bundle_not_ready()` with the same shared body (asserted in the test); the view subclasses `JobApiView`; tests in `TT/test_api_sandbox.py` (200 content type and filename, 409, 403, 401)

**Checkpoint**: the package can be downloaded and holds only trusted tests

---

## Phase 8: Polish & Cross-Cutting Concerns

- [X] T039 Run the whole suite in the `ai_web` image (`core_ai/tests` + `test_graphify_implementation.py`): every test passes, conflict detection's tests unchanged
- [X] T040 Build and start the new services (`docker compose build testgen_sandbox_image testgen_sandbox_worker`, `up -d`), restart `ai_web` and `upm_api_gateway`; run the quickstart's Postman sequence and isolation table on the real engine (owner present); record results
- [X] T041 Write the Arabic report `Ai_project/core_ai/tests/reports/testgen_s3_sandbox_run.md` (what was built, every test file and its count, the real acceptance run with outputs, the isolation checks, known limits incl. research R6)
- [X] T042 Commit locally after the acceptance check passes (no push)

---

## Dependencies & Execution Order

### Phase Dependencies

- Setup → Foundational → US1 → (US2, US3 in parallel) → US4 → US5 → Polish
- US1 is tested with the fake executor and does not need US2; the real run (T040) needs US2.
- US4 needs US1's run pass; US5 needs US4's final run and coverage.

### Within Each User Story

- tests first, failing before the implementation exists
- pure modules (`results`, `workspace`, `coverage`, `bundle`) before `acceptance` and `run_stage`, then
  the task, then serializers and views

### Parallel Opportunities

- T002, T003, T004, T005; T006, T007, T008, T009; T011, T013; all test tasks inside a story; US2 and
  US3 once US1 is done

---

## Implementation Strategy

1. Setup + Foundational: statuses, run storage, result reading, executor interface, stricter lint.
2. **MVP = US1 + US2**: records really run and only passing ones are `ready`; isolation pinned.
3. **Stop and validate** on the real engine with the owner (part of T040).
4. US3: exact reasons. US4: coverage. US5: bundle.
5. Polish: full suite, acceptance run, Arabic report, local commit.

---

## Notes

- 42 tasks: Setup 5, Foundational 9, US1 10, US2 3, US3 3, US4 5, US5 3, Polish 4
- Out of scope for every task: repair (S4), quarantine, edge, integration, installing dependencies,
  the front end
- Files changed outside the package: `Ai_project/Ai_project/settings.py`, `Ai_project/requirements.txt`,
  `docker-compose.yml` (infrastructure only)
- A task is ticked only when its test passes inside the `ai_web` image
