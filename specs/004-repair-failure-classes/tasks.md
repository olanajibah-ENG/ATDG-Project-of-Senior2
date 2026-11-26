---
description: "Task list for S4 — Repair Loop, Failure Classes, Stable Results and Environment Preflight"
---

# Tasks: S4 — Repair Loop, Failure Classes, Stable Results and Environment Preflight

**Input**: Design documents from `/specs/004-repair-failure-classes/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/api.md, quickstart.md

**Tests**: included (the constitution requires tests for every slice). No automated test may start a
container or call the model: `FakeModel` (`TT/fakes.py`) and `FakeSandboxExecutor` (`TT/fake_sandbox.py`).

**Organization**: tasks are grouped by user story (US1 … US4 of spec.md).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: US1 … US4
- Paths are relative to the repository root:
  - `TG` = `Ai_project/core_ai/services/test_generation`
  - `TT` = `Ai_project/core_ai/tests/test_generation`

## Before any task

- [ ] T000 Push S3 (commit `34bbb69`, branch `feature/testing-v1/evaluation`) to the remote and create
      branch `004-repair-failure-classes` from it (spec Assumptions; constitution VI)

---

## Phase 1: Setup (Shared Infrastructure)

- [X] T001 Add settings to `Ai_project/Ai_project/settings.py` (research R13):
      `TESTGEN_MAX_REQUESTS_PER_JOB = 30` (was 20), `TESTGEN_MAX_REPAIR_ATTEMPTS = 2`,
      `TESTGEN_REPAIR_OUTPUT_CHARS = 3000`, `TESTGEN_PER_TEST_TIMEOUT_SECONDS = 30`,
      `TESTGEN_FLAKY_RERUNS = 2`, `TESTGEN_SANDBOX_IMAGE` default `autotest-sandbox:py3.10-s4`,
      `TESTGEN_INSTALL_TIMEOUT_SECONDS = 300`, `TESTGEN_INSTALL_MEMORY = '2g'`,
      `TESTGEN_ENV_LOCK_STALE_SECONDS = 900`, `TESTGEN_ENV_FAILED_TTL_SECONDS = 3600`,
      `TESTGEN_ENV_KEEP_DAYS = 7`, `TESTGEN_INSTALL_TMPFS = '1g'`, `TESTGEN_PROBE_TIMEOUT_SECONDS = 60`,
      `TESTGEN_PROBE_MEMORY = '1g'`,
      `TEST_COVERAGE_SNAPSHOTS_COLLECTION = 'test_coverage_snapshots'`, `TEST_ENVS_COLLECTION = 'test_envs'`
- [X] T002 [P] Update `TG/sandbox/image/Dockerfile`: add `pytest-timeout==2.3.1 pytest-socket==0.7.0`
      to the `pip install` line; create `/workspace/deps` (owned by 10001); add `tomli>=2.0` to
      `Ai_project/requirements.txt`
- [X] T003 [P] Update `docker-compose.yml`: `testgen_sandbox_image` image tag `autotest-sandbox:py3.10-s4`
- [ ] T004 [P] Extend `TT/fakes.py`: `FakeModel` accepts a list of scripted answers per call, so a test
      can script "generate → repair 1 → repair 2"; helpers `repair_fix(code, reason)` and
      `repair_suspect(location, expected, explanation)` that build `repair-v1` answers (research R3)
- [ ] T005 [P] Extend `TT/fake_sandbox.py`: a script entry may be a **list** of `RunOutput` (one per call,
      for flaky and re-run sequences); scripted `install()` results (`ok`, `failed`, `missing`); helper
      `junit_timeout(names, hanging)` (case message `Failed: Timeout >30.0s`) and `junit_with_types(...)`
      (cases with `type=` / `E   ImportError:` text)

---

## Phase 2: Foundational (Blocking Prerequisites)

**⚠️ CRITICAL**: no user story work starts before this phase is complete

- [X] T006 Extend `TG/statuses.py`:
  - `JobStage.PREFLIGHT`, `JobStage.REPAIRING`, `JobStage.FLAKY_CHECK`;
  - `RunReason.RUN_TIMEOUT`, `RunReason.OUT_OF_MEMORY`, `RunReason.INSTALL_FAILED`,
    `RunReason.IMPORT_FAILED`
    (add to `RUN_ENV_REASONS`);
  - `RepairReason.SUSPECTED_CODE_BUG`, `FLAKY`, `REPAIR_BUDGET_EXHAUSTED`;
  - `SkipReason.SYNTAX_ERROR`, `BINARY_FILE`, `EMPTY_FILE`;
  - `REPAIRABLE_CAUSES` = run causes `collection_error, no_tests, skipped_test, timeout, assertion,
fails_with_others` + static causes `syntax_error, forbidden_import, weak_test`;
  - `Actor` constants and the `TRANSITIONS` table exactly as research R2, with
    `allowed(from_status, to_status, actor) -> bool` and `sources_of(to_status, actor) -> set`
- [X] T007 [P] Write `TT/test_transitions.py`: every allowed row passes; every other
      (from, to, actor) pair raises `IllegalTransition`; `ready` reachable only with actor `gate`;
      `test_failed → generated` and `generation_failed → generated` refused when
      `attempts_used >= settings.TESTGEN_MAX_REPAIR_ATTEMPTS` (also with a changed setting, e.g. 1);
      `generation_failed → generation_failed` (reason change) allowed for repair and finalize
- [X] T008 Extend `TG/records.py` (both repos): `transition(record_id, to_status, actor, fields)` using
      the filter `{"status": {"$in": sources_of(to_status, actor)}}` **plus**
      `{"attempts_used": {"$lt": settings.TESTGEN_MAX_REPAIR_ATTEMPTS}}` when `actor == repair` and
      `to_status == generated` (atomic, never hard-coded), raising `IllegalTransition` when nothing
      matched; `update()` refuses any `status` key; `accept_ready()` checks the table with actor `gate`;
      `push_attempt(record_id, item)` appends to `attempts` (item `outcome="written"`, `run_id=None`);
      `update_attempt(record_id, n, fields)` sets `run_id` / `outcome` of attempt `n`;
      `next_repairable(job_id)` (status `test_failed` or `generation_failed`, `reason_code` in
      `REPAIRABLE_CAUSES`, `attempts_used < TESTGEN_MAX_REPAIR_ATTEMPTS`, stable order); new defaults in
      `Ai_project/core_ai/models/testgen.py` (`attempts=[]`, `attempts_used=0`, `explanation=None`,
      `fwo_repaired=False`, `last_rejection=None`)
- [X] T009 Move every status write in `TG/generation.py`, `TG/acceptance.py`, `TG/run_stage.py`,
      `TG/runner.py` to `records.transition(...)` with the right actor; extend `TT/test_records.py`
      for `transition`, `push_attempt`, `update_attempt`, `next_repairable`; add
      `TT/helpers.py: put_record(status=…, **fields)` (creates the record with that status in the
      in-memory repo) and switch every existing S1–S3 test that sets a status through `update(status=…)`
      to it — setup lines only, no assertion changes
- [X] T010 In `TG/generation.py`: on every write push an `attempts[]` item
      `{n: 1, purpose: "generate", attempt_id, run_id: null, outcome, cause, test_sha256, created_at}`
      (`test_sha256` = sha256 of `test_code`; for an invalid answer, of the extracted code or answer text)
- [X] T011 [P] In `TG/sandbox/executor.py`: rename `RunSpec` to `RunRequest`, add
      `mode: str = RunMode.FULL` (also support `collect_only` for import/collection checks), keep `RunSpec = RunRequest`;
      `RunOutput` gains `oom_killed: bool = False`; `DockerSandboxExecutor.run()` raises `ValueError`
      for any other mode and, after `wait()`, does `container.reload()` and reads
      `container.attrs["State"]["OOMKilled"]` into `oom_killed`
- [X] T012 [P] Extend `TT/test_docker_executor.py`: `RunRequest(mode="full")` produces **the same argv**
      as S3 (compare with the S3 expected list unchanged); unknown mode raises; a recorded container
      with `State.OOMKilled=True` gives `oom_killed=True`
- [ ] T013 [P] Update `TG/sandbox/workspace.py`: `PYTEST_INI` =
      `[pytest]\naddopts = -p no:cacheprovider --timeout=<TESTGEN_PER_TEST_TIMEOUT_SECONDS> --timeout-method=signal --disable-socket --allow-unix-socket\n`;
      update `TT/test_workspace.py`
- [X] T014 [P] Extend `TT/test_results.py`: `error_type` read from `type=` or from the last `E   Name:`
      line; a case with `Failed: Timeout` → `test_failed / timeout` with `error_type="Timeout"`;
      the **real** S3 whole-run timeout (`timeout --signal=KILL` → exit 137, `timed_out=False`,
      `oom_killed=False`, no junit) → `environment_error / run_timeout`; exit 124 or the worker guard
      (`timed_out=True`) → `run_timeout`; exit 137 with `oom_killed=True` →
      `environment_error / out_of_memory`; a `SocketBlockedError` case stays `assertion` with that message;
      `No module named 'requests'` (not project, not stdlib) → `environment_error / missing_dependency`
      even when pytest exits 2 (checked before `collection_error`)
- [X] T015 Update `TG/results.py` to pass T014 (research R6)
- [ ] T016 Update `Ai_project/core_ai/celery_tasks/testgen_tasks.py`: dispatch by `job["stage"]`:
  - `advance_job`: planning stages → S1; `generating` → generation pass; `repairing` → repair pass;
  - `sandbox_pass`: `preflight` → preflight pass; `sandbox_run` / `final_run` / `flaky_check` → run stage;
  - each pass returns `next` (`advance` | `sandbox` | `self` | `done`, optional countdown) and the task
    enqueues accordingly (no task waits on another)

**Checkpoint**: foundation ready — the whole existing S1–S3 suite still passes; only the setup lines
of tests that set a status with `update(status=…)` change (to `put_record(status=…)`, T009), never
their assertions

---

## Phase 3: User Story 1 - A failing test that the test itself can fix is repaired (Priority: P1) 🎯 MVP

**Goal**: repairable records go back to the model with their real failure, at most 2 repairs each,
inside the shared budget of 30, and become `ready` only through the gate.

**Independent Test**: with `FakeModel` + `FakeSandboxExecutor`, one record per repairable cause ends
`ready` after one repair or with its last cause after two; budget and model-down paths end
`repair_budget_exhausted`; no record has more than 3 writes.

### Tests for User Story 1

- [ ] T017 [P] [US1] Write `TT/test_repair_prompt.py`: the prompt holds the context JSON, the full
      failing test, each failing test's `name / error_type / message`, output cut to 3000 characters,
      the cause and the generation rules; for a static cause it holds the validator reason and the attempt's
      `answer_text` instead of output; after a rejected candidate it starts with "Your previous fix was
      rejected: <rule>" and includes that candidate; parsing of `VERDICT: fix_test` (reason + code block),
      `VERDICT: suspect_code` (3 fields), and invalid answers
- [ ] T018 [P] [US1] Write `TT/test_repair.py`:
  - each run cause (`collection_error`, `no_tests`, `skipped_test`, `timeout` of one test, `assertion`)
    is repaired and, when the next run passes, ends `ready` with `evidence.repaired=True`,
    `evidence.attempt=2`; a single-test `timeout` that still hangs after 2 repairs (or repeats its hash,
    or fails the guards on the last attempt) ends `test_failed / timeout`;
  - each static cause (`syntax_error`, `forbidden_import`, `weak_test`) is repaired with the same budget;
  - `no_code`, `unsafe_code` and every `environment_error` are never selected;
  - two failed repairs → no third request; attempts list has 3 items;
  - a repaired candidate failing validation counts as an attempt;
  - repeated `test_sha256` on the **first** repair → `finalize()` at once, no second repair request;
  - `missing_dependency` records are never selected;
  - `llm_requests` reaching 30 while records wait → the job still enters `repairing`, the pass runs
    `exhaust_all()`: every repairable record keeps its status (`test_failed` or `generation_failed`)
    with reason `repair_budget_exhausted` (never left with its raw cause), job `completed_with_issues`,
    `ready` records kept;
  - after each run the attempt's `run_id` and `outcome` are filled (`update_attempt`);
  - limit reached during generation → remaining records stay `pending` (S2 rule), generated ones
    still run, no repair request;
  - `ModelUnavailable` → same as budget;
  - every repair writes a `test_attempts` document with `purpose="repair"`, `prompt_version="repair-v1"`,
    `repair_of`
- [ ] T019 [P] [US1] Extend `TT/test_run_stage.py`: with no `generated` left and repairable records →
      stage `repairing` and hand-over to `advance`; with none → `final_run`; a `fails_with_others` record
      with an attempt left is repaired once (`fwo_repaired=True`), run alone, then joins the final run;
      a `fails_with_others` record with `attempts_used == 2` stays `test_failed / fails_with_others` at once;
      failing with others again after its repair → stays `test_failed`, not repaired again; the record run
      gets `timeout_s = min(300, max(60, 30 × tests + 30))`

### Implementation for User Story 1

- [X] T020 [P] [US1] Create `TG/prompts/repair.py`: `PROMPT_VERSION = "repair-v1"`, `SYSTEM`,
      `USER_TEMPLATE` with placeholders `{context_json} {failing_test} {failures} {output} {cause} {rules}`,
      and the answer format of research R3
- [X] T021 [US1] Extend `TG/strategies/base.py`: `build_repair_prompt(context, failure, adapter)`
      (same rules block as `build_prompt`; output cut to `TESTGEN_REPAIR_OUTPUT_CHARS`) and
      `parse_repair_answer(text) -> RepairAnswer(verdict, reason, code, location, expected, explanation)`;
      `request_hash` covers the repair prompt too
- [X] T022 [US1] Create `TG/repair.py` `run_repair_pass(job_id, *, jobs, records, attempts, llm, strategy,
adapter, reader)` — one record per pass:
  1. budget: `job.llm_requests >= TESTGEN_MAX_REQUESTS_PER_JOB` → `exhaust_all()`;
  2. `next_repairable()`; none → stage `sandbox_run`, `next="sandbox"`;
  3. build the failure block (run cause → `run_result`; static cause → validator reason + `answer_text`;
     if `record.last_rejection` is set, prepend "Your previous fix was rejected: <rule>" and the
     rejected code cut to 3000 characters);
  4. call through `LLMFacade` (reuse by `request_hash`), `ModelUnavailable` → `exhaust_all()`;
  5. parse; `fix_test` → S2 validator → (US2 guards hook) → sha256 seen in `attempts[]`? ;
  6. ok → `transition(→ generated, actor repair)`, store `test_code`, `attempts_used += 1`,
     `push_attempt(purpose repair)`; duplicate hash → `push_attempt(outcome duplicate)` and
     `finalize()` **at once**; invalid → `push_attempt(outcome invalid)`, `attempts_used += 1`,
     out of attempts → `finalize()`; a rejected candidate is kept in `record.last_rejection`
     `{rule, detail, code}` (cleared after a written attempt);
  7. `next="self"`
- [X] T023 [US1] In `TG/repair.py` add `finalize(record, cause)` with the outcomes of plan.md
      (`syntax_error`/`forbidden_import`/`weak_test`/`collection_error`/`no_tests` → `generation_failed`,
      reason kept; `assertion`/`timeout`/`skipped_test`/`fails_with_others` → `test_failed`, reason kept) and
      `exhaust_all(job)` (reason `repair_budget_exhausted`, original cause in `reason_detail`, status kept)
- [ ] T024 [US1] Update `TG/run_stage.py`: when no `generated` record is left, hand over to `repairing`
      whenever `next_repairable()` finds one (**the budget is checked by the repair pass**, so
      `exhaust_all()` always runs); after every record run and after `reject()` call
      `update_attempt(record_id, n, {run_id, outcome})`; per-record run `timeout_s =
min(300, max(60, 30 × expected test cases + 30))` (a test function counts 1, or the length of a
      literal `parametrize` list, multiplied over stacked decorators); in the final-run loop mark a failing record
      `fails_with_others`; if `attempts_used < TESTGEN_MAX_REPAIR_ATTEMPTS` and `fwo_repaired` is False
      make it repairable once (set `fwo_repaired=True`), otherwise finalize it at once; a record repaired
      for `fails_with_others` that fails with others again stays `test_failed`
- [X] T025 [US1] Update `TG/acceptance.py`: evidence adds `repaired` (`attempts_used > 0`) and
      `attempt` (`attempts_used + 1`); calls `update_attempt(…, {run_id, outcome: "ready"})`; job
      `progress.repaired` counts ready records with `repaired=True`; extend `TT/test_acceptance.py` for
      these fields and for `ready` going through the transition table
- [X] T026 [US1] Wire `advance_job` stage `repairing` to `run_repair_pass` in
      `Ai_project/core_ai/celery_tasks/testgen_tasks.py`

**Checkpoint**: US1 works alone with fakes — T017–T019 pass, S1–S3 suite still green

---

## Phase 4: User Story 2 - Honest classification and no cheating (Priority: P1)

**Goal**: `suspect_code` is reported, never hidden; cheating repairs are rejected; every record ends with
one status and reason from the table; failures carry `error_type`; finer skip reasons.

**Independent Test**: a planted-bug fixture ends `test_failed / suspected_code_bug` with an explanation;
one cheating repair per guard rule is rejected; every row of FR-016 is reproduced.

### Tests for User Story 2

- [ ] T027 [P] [US2] Write `TT/test_repair_guards.py`: one clean repair passes; each rule fails with its
      code — `unit_not_called`, `skip_marker` (`pytest.skip`, `@pytest.mark.skipif`, `@pytest.mark.xfail`),
      `swallowed_failure` (`try/except Exception: pass`), `mocks_unit` (`mock.patch("pkg.mod.unit")`,
      `monkeypatch.setattr(mod, "unit", …)`), `generic_raises` (`pytest.raises(Exception)` new),
      `fewer_tests`, `fewer_asserts`; `pytest.raises(Exception)` already in the original is allowed;
      an original that does not parse → only the absolute rules run (no comparison rules);
      `Customer.__init__` counts as called by `Customer(...)`; `__eq__` by `==`, `__len__` by `len()`,
      `__contains__` by `in`, `__getitem__` by subscript; a repair that changes `== 5` to `== 7` passes
      but returns `changed_assertions=[{test, before: "5", after: "7"}]`
- [ ] T028 [P] [US2] Write `TT/test_classification.py`: one case per row of spec FR-016, including
      `weak_test` after 2 failed repairs → `generation_failed / weak_test`, `suspected_code_bug`, `flaky`,
      `repair_budget_exhausted`, `run_timeout`, `out_of_memory`, `install_failed`, `import_failed`
- [X] T029 [P] [US2] Extend `TT/test_repair.py`: `suspect_code` on an `assertion` → `test_failed /
suspected_code_bug`, `explanation` stored, `test_code` unchanged, not in bundle tests; `suspect_code`
      with an empty field, or on a non-assertion cause → failed attempt
- [ ] T030 [P] [US2] Extend `TT/test_planner.py` / `TT/test_runner.py`: an empty file → `empty_file`;
      a file with NUL bytes → `binary_file`; a file that does not parse → `syntax_error`; otherwise
      `analysis_failed` stays

### Implementation for User Story 2

- [ ] T031 [P] [US2] Create `TG/validation/repair_guards.py`: `check(original_code, repaired_code,
unit_name, class_name) -> GuardResult(ok, rule, detail, changed_assertions)` with the rules of research
      R4 (AST only): comparison rules skipped when the original does not parse; the constructor and
      special-method table for `unit_not_called`; `changed_assertions` from `ast.unparse` of assert
      right-hand sides and `pytest.approx` / `pytest.raises` arguments
- [X] T032 [US2] In `TG/repair.py`: call the guards after the S2 validator; a violation →
      `push_attempt(outcome guard_violation, cause "guard:<rule>", rejection)`, attempt counted, candidate
      kept in `record.last_rejection` for the next request; a passing candidate stores
      `changed_assertions` on its attempt; `suspect_code`
      handling (assertion only, three non-empty fields) → `transition(test_failed → test_failed, actor
repair, reason suspected_code_bug, explanation)`, no further repair
- [X] T033 [US2] In `TG/runner.py`: finer skip reasons of research R12 where `analysis_failed` was set
- [X] T034 [US2] Update `Ai_project/core_ai/serializers/testgen_serializer.py`: record detail shows
      `attempts`, `attempts_used`, `explanation`, `run_result.tests[].error_type`; list shows `attempts_used`
      (contracts/api.md)

**Checkpoint**: US1 + US2 pass with fakes; no repaired test reaches `ready` after a guard violation

---

## Phase 5: User Story 3 - Stable results: flaky check, final run, coverage snapshot (Priority: P2)

**Goal**: two re-runs remove flaky tests; coverage from the last all-pass run; exactly one snapshot per
finished job.

**Independent Test**: a scripted test that passes, fails, passes is removed as `flaky`; coverage comes
from a run without it; one snapshot exists for the job.

### Tests for User Story 3

- [ ] T035 [P] [US3] Write `TT/test_flaky.py`: stage `flaky_check` after the final run passes; two
      re-runs with no model call; a differing record → `ready → test_failed / flaky`, not repairable;
      something removed → another final run; a test failing in that run → `fails_with_others` with no repair
      and no second flaky check, and the run repeats without it until all pass; coverage from the last
      all-pass run; nothing removed → no extra run; a re-run with no junit (`run_timeout` / OOM /
      `sandbox_unavailable`) is retried once, and if it fails again `job.flaky.status="inconclusive"`,
      records stay `ready`, job `completed_with_issues` with notice `flaky_check_inconclusive`
- [ ] T036 [P] [US3] Write `TT/test_snapshots.py`: exactly one snapshot for a job with an all-pass final
      run, with the fields of data-model.md; **no** snapshot for a job without one (no `ready` test);
      calling `finish()` twice writes one snapshot (duplicate key ignored); the repo has no update or
      delete method

### Implementation for User Story 3

- [ ] T037 [P] [US3] Create `TG/snapshots.py`: `new_snapshot(...)` in `Ai_project/core_ai/models/testgen.py`,
      `CoverageSnapshotRepo` in-memory + Mongo (`settings.TEST_COVERAGE_SNAPSHOTS_COLLECTION`, unique
      `job_id`, index (`project_id`, `version_number`, `source`, `created_at`)), insert-only (`add`, `get`,
      `list_for_project`), providers `get_snapshot_repo()` / `set_snapshot_repo()`; fixture in `TT/conftest.py`
- [X] T038 [P] [US3] Create `TG/flaky.py`: `differing_records(final_run, reruns, records)` — compares
      per-test outcomes by name across the three runs and returns the record ids with any difference
- [X] T039 [US3] Update `TG/run_stage.py`: after an all-pass final run → stage `flaky_check`; one re-run
      per pass (`with_coverage=False`), stored in `job.flaky.runs`; after `TESTGEN_FLAKY_RERUNS` runs apply
      `differing_records` (`transition(ready → test_failed, actor flaky, reason flaky)`); removed → stage
      `final_run` again with flag `after_flaky=True` (a failure there → `fails_with_others`, no repair, no
      second flaky check, repeat without it); a re-run without per-test results is retried once, then
      the check is `inconclusive` (research R8); `finish()` writes the snapshot only when an all-pass final run
      exists, ignores a duplicate key, and stores `job.snapshot_id`

**Checkpoint**: US3 passes with fakes; existing coverage tests unchanged

---

## Phase 6: User Story 4 - Environment checked before any model request (Priority: P2)

**Goal**: manifests kept at upload; `preflight` installs once per env key with a lock; a failure stops
the job with 0 model requests.

**Independent Test**: with `FakeSandboxExecutor`, an install failure leaves every record
`environment_error`, the job `failed`, `llm_requests == 0`; two jobs with the same key install once.

### Tests for User Story 4

- [ ] T040 [P] [US4] Write `TT/test_upload_support_files.py`: on both upload paths
      (`Ai_project/core_ai/views/folder_upload.py` loose files and ZIP; the UPM proxy filter function) every
      entry of the allow-list — base name `requirements*.txt` (e.g. `requirements.txt`,
      `requirements-dev.txt`), any `.txt` under `requirements/` (e.g. `requirements/base.txt`),
      `pyproject.toml`, `setup.cfg`, `pytest.ini`, `conftest.py` — is kept with `file_type="support"`,
      `analysis_status="NOT_ANALYSED"`, and no analysis task is sent; anything outside it (`notes.txt`,
      `config.toml`, `tox.ini`, `other.cfg`, `docs/requirements.md`) is still dropped
- [ ] T041 [P] [US4] Write `TT/test_preflight.py`: no manifest and no third-party import → `skipped`,
      stage `generating`; install ok
      → env `ready`, volume recorded, stage `generating`; same key `ready` → reused, no install; same key
      `building` (fresh) → re-enqueue in 10 s; `building` older than 900 s → take over; definite `failed`
      younger than 3600 s → job fails at once with the stored detail; definite `failed` older → take over
      and install once more; temporary failure (network / time limit, **and** an output that has
      `Retrying (Retry(` together with `No matching distribution found`) → retried once after 30 s
      (`install_tries` 1 → 2), stored `failed_temporary`, never reused by the next job; definite
      `No matching distribution` without temporary markers → every record
      `environment_error / missing_dependency`; conflict or build error → `install_failed`; in both
      cases job `failed`, `llm_requests == 0`;
      the env key changes when a manifest or the Python version changes; after install
      `/deps/sitecustomize.py` is written; `reap()` removes entries unused for 7 days (and skips a
      volume Docker reports in use) and runs at most once per hour (Redis `SET NX EX 3600`, faked);
      import probe: no manifest + a file importing `requests` → the records of that file and of files
      that import it become `environment_error / missing_dependency` (detail `requests`), other
      records go on to `generating`; `ImportError: libGL.so.1` for `cv2` → `environment_error /
    import_failed` with that message (not `missing_dependency`); a `ModuleNotFoundError` for a
      different name raised inside the library → `import_failed`; probe killed after printing some
      lines → printed modules classified, the rest only a warning; probe cannot start → warning only;
      all records affected → job `failed`; no third-party import →
      probe not run
- [ ] T042 [P] [US4] Extend `TT/test_docker_executor.py`: install container has network `bridge`, no
      environment values except the two `PIP_*` and `TMPDIR=/tmp`, user 10001, `cap_drop=["ALL"]`,
      `security_opt=["no-new-privileges"]`, 1 CPU, `2g`, 256 pids, read-only root, `/tmp` tmpfs `1g`,
      mounts **only** the
      manifests volume (ro) at `/manifests` and the env volume (rw) at `/deps` (no source volume);
      test runs mount the env volume **read-only** at `/workspace/deps`, `PYTHONPATH`
      `/workspace/src:/workspace/deps`, network still `none`; the probe container has network `none`,
      source (and env, when given) read-only, no env values, 1 GB, 60 s, and runs `python -c <script>`;
      with `env_volume=None` there is no `/workspace/deps` mount and `PYTHONPATH=/workspace/src`
- [ ] T043 [P] [US4] Extend `TT/test_python_adapter.py`: `install_spec()` returns `(text, warnings)`:
      root `requirements.txt` when present (only it); else the first of `requirements/base.txt`,
      `requirements/common.txt`, `requirements/requirements.txt`, `requirements/main.txt` (so a
      cookiecutter `requirements/{base,local,production}.txt` installs `base.txt` only); else every
      `requirements*.txt` with no excluded **word** (`dev, develop, development, doc, docs, test, tests,
    testing, lint, prod, production, local, staging, ci`) after splitting the name on `-`, `_`, `.`
      (`requirements-prod.txt` left out, `requirements-latest.txt` and `requirements_contest.txt`
      kept); files left out are listed in the warnings; plus `[project].dependencies` and
      `install_requires`; `-r X` followed only
      when `X` is kept; `-e`, `-c`, `--index-url`, `--extra-index-url`, `--find-links` and other options
      dropped with one warning each; no manifest → `(None, [])`

### Implementation for User Story 4

- [X] T044 [P] [US4] Update `Ai_project/core_ai/views/folder_upload.py`: `is_support_file(path)` with
      the allow-list only (base name `requirements*.txt`; any `.txt` under a `requirements/` folder;
      `pyproject.toml`, `setup.cfg`, `pytest.ini`, `conftest.py`); keep them in `_extract_from_zip` /
      `_extract_from_files` even when the extension is ignored; in `_save_single_file` store
      `file_type="support"`, `analysis_status="NOT_ANALYSED"` and skip `analyze_code_file_task.delay`
- [X] T045 [P] [US4] Update `UPM_Project/core_upm/views/folder_upload_proxy.py`: forward a file that
      matches the same allow-list even if its extension is not in `SUPPORTED_EXTENSIONS`; nothing else is
      added
- [X] T046 [P] [US4] Update `TG/gate.py` and `TG/planner.py`: files with `file_type == "support"` are
      neither decided, planned nor listed as skipped
- [ ] T047 [P] [US4] Extend `TG/languages/base.py` + `TG/languages/python_adapter.py`:
      `install_spec(files: dict[path, bytes]) -> (str | None, list[str])` (research R11; `tomli` for
      `pyproject.toml`, `configparser` for `setup.cfg`)
- [ ] T048 [P] [US4] Create `TG/envs.py`: `new_env(...)` in `Ai_project/core_ai/models/testgen.py`;
      `EnvRepo` in-memory + Mongo (`settings.TEST_ENVS_COLLECTION`, unique `env_key`) with
      `try_claim(env_key, job_id)`, `take_over(env_key, job_id, older_than, status)` (conditional update),
      `mark_ready(env_key, volume, size_bytes)`, `mark_failed(env_key, detail, temporary: bool)`,
      `touch(env_key)` (`last_used_at`), `get(env_key)`, `reap(executor, keep_days, lock)` where `lock` is
      Redis `SET testgen:env_reaper 1 NX EX 3600` (no extra document in `test_envs`); fixture in
      `TT/conftest.py`
- [ ] T049 [US4] Extend `TG/sandbox/executor.py` and `TG/sandbox/docker_executor.py`:
      `InstallRequest(env_key, requirements_text, timeout_s)` / `InstallOutput(ok, volume, exit_code, output,
missing, temporary)`, `install(request)` with the options of research R11 (non-root, no capabilities,
      limits (1 CPU, `TESTGEN_INSTALL_MEMORY` 2 GB), `/tmp` tmpfs 1 GB, `TMPDIR=/tmp`, manifests-only mount,
      no source; after pip succeeds write `/deps/sitecustomize.py`; classify the **whole** pip output:
      temporary markers first, then definite); `ProbeRequest(src_volume, env_volume: str | None, modules)` /
      `probe_imports(request) -> dict[module, {ok} | {error_type, missing_name, msg}]` (one flushed JSON
      line per module, so partial results survive a time-out; modules with no line are "not probed"); `remove_volume(name)`
      for the reaper; `RunRequest` gains `env_volume`
      (optional) mounted read-only at `/workspace/deps` with `PYTHONPATH=/workspace/src:/workspace/deps`
- [ ] T050 [US4] Create `TG/preflight.py` `run_preflight_pass(job_id, *, jobs, records, envs, executor,
reader, adapter)` implementing the decision list of plan.md step 2 (skip, reuse, wait, take over,
      fail fast, install, temporary failure → re-enqueue once with countdown 30 s using
      `job.preflight.install_tries`, fail →
      `transition(pending → environment_error, actor preflight)` for every record with `missing_dependency`
      or `install_failed` by research R11, and job `failed`); then the **import probe**: scan the version's
      Python files for third-party top-level imports, run `probe_imports` (with `env_volume=None` when
      there is no manifest), and classify by research R11: `ModuleNotFoundError` whose `missing_name` is
      the module or its root → records that need it (directly or through project imports)
      `environment_error / missing_dependency`; any other error → `environment_error / import_failed`
      with the message; not probed (time / memory) → warning `import probe incomplete` only;
      fail the job if every record is affected; calls `envs.reap()` first and `envs.touch()` on reuse;
      on success store `job.preflight` (with `warnings`, `install_tries`, `probe`) and stage
      `generating`, `next="advance"`
- [X] T051 [US4] Update `TG/runner.py` (end of planning → stage `preflight`, `next="sandbox"`),
      `Ai_project/core_ai/celery_tasks/testgen_tasks.py` (`sandbox_pass` stage `preflight` →
      `run_preflight_pass`), and `TG/run_stage.py` (pass `job.preflight.volume` as `env_volume`)

**Checkpoint**: all four stories pass with fakes

---

## Phase 7: Polish & Cross-Cutting Concerns

- [X] T052 [P] Update `TG/bundle.py`: `records_summary.json` items add `attempts` (`n, purpose, outcome,
cause`), `changed_assertions` (from all attempts) and `explanation`; tests folder holds `ready` tests
      only; extend `TT/test_bundle.py`
- [X] T053 [P] Update the job serializer: `stage` values, `progress.repaired`, `preflight` (with
      `warnings`, `install_tries`, `probe`), `flaky.status`, `notices` (always a list, e.g.
      `flaky_check_inconclusive`), record detail `attempts[].changed_assertions`,
      `snapshot_id`; extend `TT/test_api_records.py` / `TT/test_api.py` (contracts/api.md)
- [ ] T054 [P] Extend `TT/test_boundaries.py`: no module writes `status` except through
      `records.transition()` / `accept_ready()`; `repair.py` and `flaky.py` never set `ready`; no import
      from other features; `docker` imported only by `docker_executor.py`
- [X] T055 Run the whole suite in `ai_web`:
      `docker exec -it ai_django_app python -m pytest core_ai/tests/test_generation -q` — all green, no
      real model call, no container
- [ ] T056 Rebuild the sandbox image and run quickstart.md scenarios 2, 3 and 5 on a real project
      (planted bug; uninstallable dependency; real KILL vs OOM on our Docker); record numbers; if
      `OOMKilled` is not set for a child process, switch `results.verdict()` to the fallback rule of
      research R6 and say so in the report
- [X] T057 Write `Ai_project/core_ai/tests/reports/testgen_s4_repair.md` (Arabic): what was tested,
      results (including failures as they are), real-run numbers
- [ ] T058 Commit S4 after the acceptance check passes (constitution workflow)

---

## Final S4 acceptance (2026-11-26)

- [x] Match the slice PDF for collection before a full run, bounded sandbox startup retry, and periodic expired-container cleanup.
- [x] Run the feature regression suite after the documented-example and sandbox changes: 438 passed on Windows.
- [x] Verify a generated test fails, receives a setup-only repair, and passes the acceptance gate on a real Docker executor. Scripted model responses and in-memory storage make this run repeatable.
- [x] Record the six manual scenarios, including the documented boundary on project versions 9 and 10.
- [x] Run the optional stock/order fixture with the live model in Postman. Version 11, job `job_c2661ef02933`: all four records passed on their first attempt. Repair was exercised separately in the controlled Docker run above.

## Dependencies & Execution Order

- **T000** before everything.
- **Phase 1 → Phase 2** → user stories.
- **US1 (Phase 3)** needs Phase 2. **US2 (Phase 4)** needs US1 (`repair.py` exists).
- **US3 (Phase 5)** needs Phase 2 **and US1** (it relies on the `fails_with_others` handling of T024);
  `run_stage.py` and `testgen_tasks.py` are changed by US1, US3 and US4, so these stories run one
  after the other, not in parallel.
- **US4 (Phase 6)** needs Phase 2; T049 touches `sandbox/executor.py` after T011; run it after US3
  (same `run_stage.py`).
- **Phase 7** after all stories.

Inside each story: tests first (they must fail), then implementation, then the checkpoint.

## Parallel Examples

- Phase 1: T002, T003, T004, T005 together.
- Phase 2: T007, T011–T014 together after T006.
- US1: T017, T018, T019 together; then T020 with T021.
- US2: T027–T030 together; T031 alone, then T032–T034.
- US3: T035–T038 together; then T039.
- US4: T040–T048 together; then T049 → T050 → T051.

## Implementation Strategy

1. **MVP = Phase 1 + Phase 2 + US1 + US2** (both P1). Stop and check with the owner: repair works,
   nothing cheats, every record has one honest final status.
2. Add **US3** (flaky + snapshot), check.
3. Add **US4** (preflight), check with a real uninstallable dependency.
4. Polish, report, commit.

## Task count

| Phase          | Tasks          |
| -------------- | -------------- |
| Before + Setup | 6 (T000–T005)  |
| Foundational   | 11 (T006–T016) |
| US1            | 10 (T017–T026) |
| US2            | 8 (T027–T034)  |
| US3            | 5 (T035–T039)  |
| US4            | 12 (T040–T051) |
| Polish         | 7 (T052–T058)  |
| **Total**      | **59**         |
