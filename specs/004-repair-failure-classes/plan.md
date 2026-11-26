# Implementation Plan: S4 — Repair Loop, Failure Classes, Stable Results and Environment Preflight

**Branch**: `004-repair-failure-classes` (built on `feature/testing-v1/evaluation`, S3 = `34bbb69`) |
**Date**: 2026-11-22 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/004-repair-failure-classes/spec.md`

## Summary

A test that fails for a reason the test can fix goes back to the model with its real failure.
The rule is the same for **every** repairable cause, single-test timeout included: at most 2 repairs
per record (3 writes with the first generation), stopping early when a repaired test repeats an earlier
`test_sha256` or when the per-job budget of 30 requests is used up. On an assertion the model must say
`fix_test` or `suspect_code`; a suspected code bug is reported, never hidden. Every repaired test passes
the S2 validator, new anti-cheat guards, and a sandbox run, and only the existing acceptance gate sets
`ready`. Every record ends with one status and reason from a single table, and status changes are
enforced by one transition table. After the final run, two re-runs remove flaky tests, coverage comes
from the last all-pass run, and one coverage snapshot is written. Before generation, a `preflight`
stage installs the project's dependencies once per manifest hash, so an environment problem stops the
job before any model request.

Technical approach: the job's `stage` routes work between the two existing Celery tasks —
`advance_job` (model key; generation **and repair**) and `sandbox_pass` (Docker, no key; **preflight**,
runs, final run, flaky check) — one record per pass, re-enqueue, no waiting (research R1). Per-test
timeout and network blocking come from two pytest plugins configured in the generated `pytest.ini`, so
the command line stays the S3 one (R6, R7).

## Technical Context

**Language/Version**: Python 3.10 (`ai_web` image); run image `python:3.10-slim` + pytest 8.3.3 +
pytest-cov 5.0.0 + **pytest-timeout 2.3.1 + pytest-socket 0.7.0** (tag `autotest-sandbox:py3.10-s4`).

**Primary Dependencies**: as in S3 (Django, DRF, Celery, PyMongo, Docker SDK 7.1.0), plus `tomli>=2.0`
added explicitly to `Ai_project/requirements.txt` to read `pyproject.toml`.

**Storage**: MongoDB. New collections `test_coverage_snapshots` (append-only) and `test_envs`. Fields
added to `test_jobs`, `test_records`, `test_attempts`, `code_files` (see [data-model.md](./data-model.md)).
Docker named volumes `sbx_env_<key>` for installed environments.

**Testing**: pytest inside `ai_web`, no database, **no model** (`FakeModel` with scripted answers), **no
container** (`FakeSandboxExecutor` with scripted outcomes, extended for install and flaky sequences).

**Target Platform**: Docker Compose (same services as S3; only the sandbox image is rebuilt).

**Project Type**: web service (`core_ai`).

**Performance Goals**: a 10-unit job stays within 30 model requests; preflight with a cached
environment adds < 5 s; flaky check adds 2 × final-run time.

**Constraints**: ≤ 3 writes per record; `ready` only through the acceptance gate; sandbox worker holds
no key; test runs keep network `none`; install runs with network on and no secrets; automated tests
make no model call and start no container.

**Scale/Scope**: jobs of tens of records; at most 2 sandbox runs at once (unchanged).

## Constitution Check

_GATE: Must pass before Phase 0 research. Re-check after Phase 1 design._

All seven principles: **PASS**.

- **I. Feature 1 only, same layout**
  - Logic stays under `core_ai/services/test_generation/`.
  - Outside the package: only the files in "Changes outside the package" below.
  - The two upload files are the constitution's own example ("keeping dependency manifests at upload").
  - No import from another feature (checked by `test_boundaries.py`).
- **II. Trusted means proven**
  - Repair never writes `ready`.
  - A repaired test goes: validator → guards → sandbox run → `acceptance.accept()`.
  - Flaky tests are removed before coverage; coverage comes from the last all-pass run only.
- **III. Bounded, recorded LLM use**
  - At most 2 repairs per record (3 writes); one per-job limit of 30 requests.
  - Every repair is recorded in `test_attempts` (purpose, model, tokens).
  - All calls go through `LLMFacade`; the repair prompt carries the Context DTO only.
  - Automated tests use `FakeModel`.
- **IV. Python + pytest first**
  - Manifest reading sits behind `LanguageAdapter.install_spec()` (`PythonAdapter`).
- **V. One shared graph**
  - Not touched.
- **VI. Small slices, reviewed**
  - Spec reviewed 2026-11-22 (six review points applied).
  - Plan and tasks are reviewed by the owner before any code.
- **VII. Honest statuses**
  - No new status, only new reason codes: `suspected_code_bug`, `flaky`,
    `repair_budget_exhausted`, `run_timeout`, `out_of_memory`, `install_failed`, `import_failed`.
  - Install failure, whole-run timeout and out-of-memory are `environment_error`.
  - One record's failure never stops the rest.

Sandbox rules: install with network on and no secrets; runs with network off, read-only, limits — met
by R11 and unchanged S3 options. Post-design re-check: no violation.

## Project Structure

### Documentation (this feature)

```text
specs/004-repair-failure-classes/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/api.md
├── checklists/requirements.md
└── tasks.md             # created by /speckit-tasks
```

### Source Code (repository root)

The tree shows where files sit (`+` new, `~` changed). What each one does is in the lists after it.

```text
Ai_project/core_ai/
├── services/test_generation/
│   ├── ~ statuses.py
│   ├── ~ records.py
│   ├── + repair.py
│   ├── + flaky.py
│   ├── + snapshots.py
│   ├── + preflight.py
│   ├── + envs.py
│   ├── ~ results.py
│   ├── ~ run_stage.py
│   ├── ~ generation.py
│   ├── ~ acceptance.py
│   ├── ~ runner.py, gate.py, planner.py
│   ├── ~ bundle.py
│   ├── prompts/
│   │   └── + repair.py
│   ├── strategies/
│   │   └── ~ base.py
│   ├── validation/
│   │   └── + repair_guards.py
│   ├── languages/
│   │   ├── ~ base.py
│   │   └── ~ python_adapter.py
│   └── sandbox/
│       ├── ~ executor.py
│       ├── ~ docker_executor.py
│       ├── ~ fake_executor.py
│       ├── ~ workspace.py
│       └── ~ image/Dockerfile
├── celery_tasks/~ testgen_tasks.py
├── serializers/~ testgen_serializer.py
├── models/~ testgen.py
├── views/~ folder_upload.py
└── tests/
    ├── test_generation/   (9 new test files, 8 changed — see below)
    └── reports/+ testgen_s4_repair.md
```

#### New files

- `repair.py` — the repair pass, one record per pass.
  Holds `finalize()` (the classification table), the budget check and the early stop (R1, R5).
  `finalize()` outcomes when attempts run out:
  - `syntax_error`, `forbidden_import`, `weak_test` → `generation_failed`, reason kept
    (e.g. `weak_test` stays `weak_test`);
  - `collection_error`, `no_tests` → `generation_failed`, reason kept;
  - `assertion`, `timeout`, `skipped_test`, `fails_with_others` → `test_failed`, reason kept.
    Early stop: a repaired test whose `test_sha256` matches an earlier write of the record calls
    `finalize()` at once, even if an attempt is left.
    Budget: when the limit (30) is reached or the model is down, every record still waiting for repair
    keeps its status and gets `repair_budget_exhausted` (cause kept in `reason_detail`). Records still
    `pending` at that moment keep the S2 behaviour (stay `pending`, job message "start a new job").
    There is no S2 regeneration step, so a static failure of the first write goes to this loop only.
    `missing_dependency` is never repairable (checked by `results.verdict()` before `collection_error`).
- `prompts/repair.py` — the `repair-v1` prompt and the answer format (R3).
- `validation/repair_guards.py` — the anti-cheat rules, on the AST (R4):
  - comparison rules (`fewer_tests`, `fewer_asserts`, `generic_raises`) are skipped when the original
    does not parse;
  - `unit_not_called` knows constructors (`Class(...)`) and special methods (operator / built-in use);
  - records `changed_assertions` (expected values changed by the repair) for review, not as a violation.
- `flaky.py` — compares the outcomes of 3 runs and finds flaky records (R8).
- `snapshots.py` — `CoverageSnapshotRepo`, insert-only, Mongo + in-memory, unique on `job_id` (R9).
  Written only after an all-pass final run; a job without one writes no snapshot.
- `preflight.py` — env key, manifest reading, lock, install, failure handling (R11):
  - which requirement files: root `requirements.txt`; else `requirements/base.txt` (or `common.txt`,
    `requirements.txt`, `main.txt` in that folder); else every `requirements*.txt` with no excluded
    **word** (`dev`, `docs`, `test`, `lint`, `prod`, `production`, `local`, `staging`, `ci`, …),
    matched after splitting the name on `-`, `_`, `.`; plus `pyproject.toml` / `setup.cfg`
    dependencies;
  - `-r` to a file not kept, `-e`, `-c`, index options → dropped with a warning on the job;
  - after install, writes `/deps/sitecustomize.py` so `.pth` files are processed;
  - pip output is checked for **temporary** markers first, on the whole output (`Retrying`,
    `Connection`, `ReadTimeout`, name resolution, time limit); if none, the failure is **definite**
    (no such package → `missing_dependency`, conflict / build error → `install_failed`) and cached
    1 hour; a temporary one is retried once after 30 s (`install_tries`) and never cached;
  - last step, also with no manifest: the **import probe** — a container with no network (and the
    environment, when there is one) imports every third-party module the project imports (from the
    AST), printing one result per module:
    - `ModuleNotFoundError` for that module → its records `environment_error / missing_dependency`;
    - any other import error → its records `environment_error / import_failed` with the message;
    - no result because the probe ran out of time or memory → warning only, no record marked
      (FR-037).
- `envs.py` — `EnvRepo` for the `test_envs` collection; `reap()` removes environments unused for
  7 days and their `sbx_env_*` volumes, at most once per hour (Redis `SET NX EX 3600` lock).

#### Changed files in the package

- `statuses.py` — new stages (`preflight`, `repairing`, `flaky_check`), new reason codes,
  finer skip reasons, and the `TRANSITIONS` table (R2).
- `records.py` — `transition()` with an atomic filter (status, plus `attempts_used <
TESTGEN_MAX_REPAIR_ATTEMPTS` for repair → generated); `push_attempt()`; `update_attempt()` to fill
  `run_id` and `outcome` when the run ends; `next_repairable()`.
- `results.py` — `error_type` per test; per-test timeout; `run_timeout` and `out_of_memory` told apart
  by Docker's `OOMKilled` flag (exit 137 is shared, R6); the S3 `missing_dependency` rule stays before
  `collection_error`.
- `run_stage.py` — hand-over to `repairing` whenever a repairable record exists (the repair pass
  checks the budget); `update_attempt()` after each run; `fails_with_others` repaired once only if an
  attempt is left; flaky check (a re-run with no per-test result is retried once, then the check is
  `inconclusive`); final re-run loop; snapshot in `finish()`; per-record run limit
  `min(300, max(60, 30 × tests + 30))` seconds, where `tests` counts parametrize cases when the
  decorator list is literal (FR-023).
- `generation.py` — writes `attempts[]` and `test_sha256` on every write; shared budget.
- `acceptance.py` — adds `evidence.repaired` and `evidence.attempt`; uses the transition table;
  calls `update_attempt()` with outcome `ready`.
- `runner.py` — finer skip reasons (R12); ignores `support` files; hands over to `preflight`.
- `gate.py`, `planner.py` — ignore files of type `support`.
- `bundle.py` — `records_summary.json` gets `attempts`, `explanation` and `changed_assertions`.
- `strategies/base.py` — adds `build_repair_prompt()` and `parse_repair_answer()`.
- `languages/base.py` — adds `install_spec(files)`.
- `languages/python_adapter.py` — turns `requirements*.txt`, `pyproject.toml`, `setup.cfg` into one list.
- `sandbox/executor.py` — `RunRequest` (with `mode`, `RunSpec` kept as alias), `RunMode`,
  `InstallRequest` / `InstallOutput`, `install()`, `ProbeRequest` / `probe_imports()`.
- `sandbox/docker_executor.py` — install container: network on, no env values except `PIP_*` and
  `TMPDIR=/tmp`, user 10001, `cap_drop=ALL`, `no-new-privileges`, 1 CPU, **2 GB** memory, read-only
  root, `/tmp` tmpfs 1 GB (counted inside the 2 GB); mounts **only** the manifests (ro) and the env
  volume (rw), never the project source. Probe container: test-run isolation (network `none`), source
  and env (optional) mounted read-only, 1 GB, 60 s. Test runs mount the env volume read-only at `/workspace/deps`.
  After every run it reads `State.OOMKilled` into `RunOutput.oom_killed`.
- `sandbox/fake_executor.py` — scripted install results; outcome sequences for flaky tests.
- `sandbox/workspace.py` — `PYTEST_INI` adds `--timeout=30 --timeout-method=signal --disable-socket
--allow-unix-socket` (`signal` fails only the hanging test and keeps `junit.xml`; unix sockets stay
  allowed so `asyncio` works; TCP/UDP are blocked).
- `sandbox/image/Dockerfile` — adds `pytest-timeout`, `pytest-socket`; tag `py3.10-s4`.

#### Changed entry files of `core_ai`

- `celery_tasks/testgen_tasks.py` — chooses the pass by `stage`.
  - `advance_job`: generating, repairing.
  - `sandbox_pass`: preflight, record runs, final run, flaky check.
- `serializers/testgen_serializer.py` — shows attempts, explanation, error_type, preflight, repaired.
- `models/testgen.py` — new defaults on records and attempts; `new_snapshot()`, `new_env()`.

#### Tests (`core_ai/tests/test_generation/`)

New:

- `test_transitions.py` — every allowed row; illegal ones raise; `ready` only through the gate.
- `test_repair.py` — each repairable cause, static causes, budget, model down, repeated hash,
  `fails_with_others` repaired once.
- `test_repair_prompt.py` — prompt content, 3000-character cap, answer parsing.
- `test_repair_guards.py` — one cheating test per rule, plus one clean repair; original that does
  not parse; `__init__` and special methods; `changed_assertions` recorded.
- `test_classification.py` — every row of FR-016.
- `test_flaky.py` — alternating test removed; final re-run; coverage from the last run; a re-run
  killed twice → `inconclusive`.
- `test_snapshots.py` — one per job with an all-pass final run; none without it; a second write for
  the same job is ignored; insert-only.
- `test_preflight.py` — no manifest, install ok, reuse, lock wait, stale take-over,
  recent definite failure → fail at once, old one → retry, temporary failure (including pip's
  `Retrying … No matching distribution` when the network is down) → retried once and not cached,
  dropped `-r/-e/-c` lines → warnings, dev/docs files left out, `sitecustomize.py` written,
  reaper removes old environments, import probe (no manifest + `import requests` → those records
  `missing_dependency`, others continue), failure with 0 model requests.
- `test_upload_support_files.py` — the allow-list (`requirements*.txt`, `requirements/*.txt`,
  `pyproject.toml`, `setup.cfg`, `pytest.ini`, `conftest.py`) is kept and not analysed;
  other names with the same extensions (`notes.txt`, `config.toml`, `tox.ini`, `other.cfg`)
  are still dropped, on both upload paths.

Changed (8):

- `test_results.py` — error_type, per-test timeout, exit 137 with `oom_killed=False` and no junit →
  `run_timeout`, exit 137 with `oom_killed=True` → `out_of_memory`, missing_dependency before
  collection_error.
- `test_docker_executor.py` — `RunRequest(mode="full")` gives the same command; install options
  (non-root, no caps, manifests-only mount); env mount.
- `test_acceptance.py` — `evidence.repaired`, `evidence.attempt`; `ready` through the transition table.
- `test_run_stage.py` — hand-over to repairing, run limit by test count, fwo with and without an
  attempt left, flaky loop.
- `test_planner.py` — finer skip reasons; `support` files ignored.
- `test_bundle.py` — attempts and explanation in `records_summary.json`.
- `test_api_records.py` — new record fields.
- `test_boundaries.py` — status changes only through `transition()`; `repair.py` never writes `ready`.

Existing S1–S3 tests that prepare a record by `update(status=…)` are moved to a test helper
(`TT/helpers.py: put_record(status=…)`, which creates the record with that status in the in-memory
repo). Only their setup lines change; their assertions stay the same.

**Structure Decision**: same style as S1–S3 — plain functions that receive their repos, model and
executor, so the whole loop is tested in memory with `FakeModel` and `FakeSandboxExecutor`.

### Changes to existing files outside the package

- `Ai_project/core_ai/views/folder_upload.py`
  - adds `is_support_file()`; it matches a fixed allow-list only: base name `requirements*.txt`,
    any `.txt` inside a `requirements/` folder, `pyproject.toml`, `setup.cfg`, `pytest.ini`,
    `conftest.py`;
  - keeps those `.txt` files even though `.txt` is ignored today; every other `.txt` stays ignored;
  - stores support files with `file_type="support"` and `analysis_status="NOT_ANALYSED"`;
  - does not start `analyze_code_file_task` for them.
- `UPM_Project/core_upm/views/folder_upload_proxy.py`
  - forwards a file that matches the same allow-list, even if its extension is not supported; any
    other name or extension is still dropped. Both files use the same list.
- `Ai_project/Ai_project/settings.py`
  - the settings of research R13 and the two new collection names.
- `Ai_project/requirements.txt`
  - `tomli>=2.0` (explicit, not through pytest).
- `docker-compose.yml`
  - sandbox image tag becomes `autotest-sandbox:py3.10-s4`.

### Flow of one job after S4

Each step names the task that runs it and the stage it reads.

```text
1. advance_job · planning (S1)
     end → stage = preflight → enqueue sandbox_pass

2. sandbox_pass · preflight
     no manifest              → skip
     env ready in test_envs   → reuse
     env being built (fresh)  → re-enqueue in 10 s
     env being built (> 15 min) → take over and install
     env failed, definite (< 1 hour) → fail at once with the stored detail
     env failed, definite (≥ 1 hour) → take over and install once more
     env failed, temporary            → take over and install
     no entry                 → install (network on, no secrets)
     install failed, temporary → retry once after 30 s, not cached
     install failed → all records environment_error
                    → job failed, 0 model requests, STOP
     import probe (always; no network, env mounted when there is one):
       ModuleNotFoundError for the module → its records: environment_error / missing_dependency
       other import error                → its records: environment_error / import_failed
       probe out of time / memory        → warning only
       every record affected → job failed, STOP
     ok → stage = generating → enqueue advance_job

3. advance_job · generating (S2, one unit per pass)
     every write → attempts[] + test_sha256
     budget reached → rest stay pending (S2 rule) → stage = sandbox_run
     no pending left → stage = sandbox_run → enqueue sandbox_pass

4. sandbox_pass · sandbox_run (S3, one record per pass)
     run limit = min(300, max(60, 30 × tests + 30)) s
     missing library → environment_error / missing_dependency (never repaired)
     run ends → update_attempt(run_id, outcome)
     no generated left:
       any repairable record → stage = repairing → enqueue advance_job
       none                  → stage = final_run

5. advance_job · repairing (one record per pass)
     budget used up or model down
       → every repairable record keeps its status, reason repair_budget_exhausted
       → stage = final_run → enqueue sandbox_pass
     else send repair-v1 (with the last rejection, if any), read VERDICT:
       suspect_code → test_failed / suspected_code_bug + explanation
       fix_test     → validator → guards → hash seen before?
         hash seen    → finalize() at once (even with an attempt left)
         fails        → attempt counted, rejection kept for the next request;
                        no attempts left → finalize()
         passes       → record back to generated; attempts_used + 1;
                        changed_assertions stored on the attempt
     no repairable left → stage = sandbox_run → enqueue sandbox_pass

6. sandbox_pass · final_run (S3 loop)
     a test fails with the others:
       attempt left and not repaired for this before → repairable once (back to 5)
       otherwise → test_failed / fails_with_others at once
     all pass → stage = flaky_check

7. sandbox_pass · flaky_check (2 re-runs, no model)
     re-run gives no per-test result → retry it once;
       again → flaky check inconclusive, records stay ready, job completed_with_issues
     outcome differs → ready → test_failed / flaky
     anything removed → final_run again:
       a test fails there → fails_with_others, no repair, no 2nd flaky check,
                            run again without it (bounded by the number of records)
       all pass → coverage from this run

8. finish
     all-pass final run exists → one snapshot (unique on job_id)
     no all-pass final run     → no snapshot
     → completed | completed_with_issues
```

## Complexity Tracking

No violation to justify. Known limits written down:

- The project's own `pytest.ini` is stored but not applied (our generated config wins) — applying it
  could re-enable network or remove the timeout. The project's `conftest.py` is in `/workspace/src`,
  not on the tests' path, so it is not loaded during our runs either. In the bundle, our `pytest.ini`
  can clash with the project's; the user runs `pytest -c pytest.ini` from the bundle folder.
- `--allow-unix-socket` is on so `asyncio` works; a test could still talk over a unix socket inside its
  own container, which reaches nothing outside (network `none`).
- Install runs third-party code (sdist `setup.py`) with the network on. It is contained: non-root,
  no capabilities, limits, no secrets, and no project source mounted.
- Install supports `requirements*.txt`, `[project].dependencies` and `install_requires`; build
  back-ends, extras and private indexes are not supported (→ `install_failed`).
- Repair limit: one rule for every cause, single-test timeout included — 2 repairs per record
  (3 writes), early stop on a repeated `test_sha256` or an exhausted budget (spec FR-001, FR-004).
- `OOMKilled` when the OOM killer hits a child (pytest) rather than PID 1 depends on the Docker and
  cgroup versions; it is checked by hand on our host (quickstart §5) with a fallback rule (R6).
- The import probe sees only imports written at module top level; an import inside a function or
  guarded by `try` can still end as `missing_dependency` at run time (reported, never repaired).
- Snapshots are unique per job, not per (project, version, source) as F3's table says; F3 decides
  how to pick one per version (data-model note).
