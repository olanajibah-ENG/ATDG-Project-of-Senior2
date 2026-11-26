# Research: S4 — Repair Loop, Failure Classes, Stable Results and Environment Preflight

Every decision below is grounded in the S3 code on branch `feature/testing-v1/evaluation`
(commit `34bbb69`). Paths are relative to `Ai_project/core_ai/services/test_generation/`.

## R1. Where the repair step runs, and how the job moves between workers

- **Decision**: the job's `stage` decides what each task does. `advance_job` (default queue, holds the
  model key) runs planning, generation **and repair passes**. `sandbox_pass` (queue `test_sandbox`,
  Docker socket, no keys) runs **preflight, record runs, final run and flaky check**. A task that
  finishes its part sets the next stage and enqueues the other task; no task waits on another.
- **Flow**: `planned → preflight (sandbox) → generating (advance) → sandbox_run (sandbox) →
repairing (advance) → sandbox_run (sandbox) … → final_run → flaky_check → final_run (if needed) →
finish`. `repairing` is entered from `sandbox_run` when no `generated` record is left and at least
  one record is repairable (cause repairable, attempts left), **whether or not budget is left**. The
  repair pass itself checks the budget and, when it is used up, runs `exhaust_all()` so every waiting
  record gets `repair_budget_exhausted` (FR-010) before the job moves to `final_run`.
- **Rationale**: keeps the S3 rule (one record per pass, re-enqueue) and Principle III (keys never on
  the sandbox worker).
- **Alternatives**: a chord/chain of Celery tasks (rejected: one task waiting on another); calling the
  model from the sandbox worker (rejected: it must hold no keys).

## R2. Record status transitions (FR-017)

- **Decision**: one table `TRANSITIONS` in `statuses.py`: `{(from, to): {allowed actors}}`. The record
  repo gets `transition(record_id, to, actor, fields)` which updates with a Mongo filter
  `{"status": {"$in": sources_of(to, actor)}}` — plus `"attempts_used": {"$lt":
TESTGEN_MAX_REPAIR_ATTEMPTS}` when `actor == repair` and `to == generated` — and raises
  `IllegalTransition` when nothing matched. The limit is read from the setting, never hard-coded.
  `update_attempt(record_id, n, fields)` fills `run_id` and `outcome` of attempt `n` when its run
  ends (called by `run_stage` after `reject()` and by `acceptance.accept()`).
  `update()` keeps refusing `status` changes except through `transition()`; `accept_ready()` stays the
  only writer of `ready` and checks the same table with actor `gate`.

  | From                           | To                             | Actor                                   |
  | ------------------------------ | ------------------------------ | --------------------------------------- |
  | pending                        | generated, generation_failed   | generate                                |
  | pending                        | skipped                        | plan                                    |
  | pending                        | environment_error              | preflight                               |
  | generated                      | ready                          | gate                                    |
  | generated                      | test_failed, environment_error | run                                     |
  | test_failed, generation_failed | generated                      | repair (only while `attempts_used < 2`) |
  | test_failed                    | generation_failed              | finalize                                |
  | test_failed                    | test_failed                    | repair, finalize (reason change only)   |
  | generation_failed              | generation_failed              | repair, finalize (reason change only)   |
  | ready                          | test_failed                    | final_run (`fails_with_others`), flaky  |

- **Rationale**: the filter makes the check atomic (no read-then-write race between workers).
- **Alternatives**: a state-machine library (rejected: one more dependency for ten rows).

## R3. Repair prompt and answer format (`repair-v1`)

- **Decision**: `prompts/repair.py` with `PROMPT_VERSION = "repair-v1"`; `strategies/base.py` gains
  `build_repair_prompt(context, failure, adapter)` (Template Method, same rules block as generation).
  The user part carries: the unit context JSON, the full failing test, per-test `name / error_type /
message`, printed output cut to 3000 characters, the cause code, and the generation rules.
  For static failures the "failure" block is the validator's `reason_code` + `reason_detail`, and the
  failing test is the attempt's `answer_text` (S2 does not store invalid code on the record).
- **Answer format**: first line `VERDICT: fix_test` or `VERDICT: suspect_code`.
  - `fix_test`: second line `REASON: <one line>`, then one fenced ```python block.
  - `suspect_code`: lines `LOCATION: <file:line or branch>`, `EXPECTED: <behaviour from docstring or
signature>`, `EXPLANATION: <one or two lines>`; no code block.
  - `suspect_code` is accepted only for an `assertion` cause and only when the three fields are
    non-empty; otherwise the answer is a failed attempt. Any cause other than `assertion` accepts only
    `fix_test`.
- **Rationale**: a fenced block is what the S2 extractor already parses; putting code inside JSON
  breaks often on free models.
- **Alternatives**: JSON answer (rejected: escaping errors); two calls (classify then fix) (rejected:
  doubles requests).

## R4. Anti-cheat guards (FR-014)

- **Decision**: `validation/repair_guards.py`, `check(original_code, repaired_code, unit_name)` on the
  two ASTs, run after the S2 validator. Rules, each with its own violation code:
  `unit_not_called`, `skip_marker` (`pytest.skip`, `skipif`, `xfail`, `unittest.skip`),
  `swallowed_failure` (`try` whose `except` catches `Exception`/`BaseException`/bare and has no
  `raise`/`assert`/`pytest.fail`), `mocks_unit` (`mock.patch`/`monkeypatch.setattr` whose target string
  or attribute ends with the unit name), `generic_raises` (`pytest.raises(Exception|BaseException)`
  not present in the original), `fewer_tests`, `fewer_asserts`. A violation is stored on the attempt as
  `validation.reason_code = "guard:<rule>"` and counts as an attempt.
- **Original does not parse** (`syntax_error` cause): the comparison rules `fewer_tests`,
  `fewer_asserts` and `generic_raises` are skipped; the absolute rules still apply.
- **What counts as calling the unit** (`unit_not_called`):
  - plain function / method: a call whose name or attribute is the unit name;
  - `Class.__init__` (and `__new__`): a call of `Class(...)`;
  - special methods by use: `__eq__/__ne__/__lt__/__le__/__gt__/__ge__` → the comparison operator;
    `__add__`, `__sub__`, `__mul__`, … → the binary operator; `__len__` → `len()`; `__str__` →
    `str()` / f-string; `__repr__` → `repr()`; `__iter__` → `for` / `iter()` / `list()`;
    `__contains__` → `in`; `__getitem__` / `__setitem__` → subscript; `__call__` → calling an
    instance; `__enter__` / `__exit__` → `with`; `__hash__` → `hash()`; `__bool__` → `bool()` / `if`;
  - any other special method: satisfied when the class is instantiated in the test.
- **Changed expected values**: not a violation (the test may be the one that is wrong), but the
  expected values that a repair changed are stored as `changed_assertions` on the attempt and copied to
  `records_summary.json` for human review. Matching, so that a small edit is not misreported:
  1. test functions are paired **by name** first (names are normalised by the S2 rename to
     `test_<unit>__<level>_<n>`), then the unpaired ones **by order**;
  2. inside a pair, asserts (and `pytest.approx` / `pytest.raises` arguments) are paired by order;
  3. a pair whose expected side (`ast.unparse` of the right-hand side) differs →
     `{kind: "changed", test, index, before, after}`; an assert only in the repair →
     `{kind: "added", test, after}`; only in the original → `{kind: "removed", test, before}`;
     a whole test only on one side → one `added` / `removed` item for the test.
     When the original does not parse, `changed_assertions` is empty.
- **Rejected candidate fed back**: the next repair request's failure block starts with
  "Your previous fix was rejected: <rule> — <one line>" and includes that rejected code (cut to
  3000 characters), so the model does not repeat the same trick; the original run failure follows.
- **Rationale**: pure AST checks, testable without a model.

## R5. Final classification (FR-016) and budget

- **Decision**: one function `repair.finalize(record, cause, why)` applies the table. Runtime causes
  `collection_error` and `no_tests` → `generation_failed`; static causes keep `generation_failed`
  with their reason; `assertion`, `timeout`, `skipped_test`, `fails_with_others` → `test_failed`.
- **Budget**: one per-job limit, `TESTGEN_MAX_REQUESTS_PER_JOB` raised 20 → 30, counted in the existing
  `job.llm_requests` (generation and repair). Reused answers (same `request_hash`) cost nothing.
  When the limit is reached or `ModelUnavailable` is raised, every still-repairable record gets reason
  `repair_budget_exhausted` (original cause kept in `reason_detail`) and keeps its status
  (`test_failed` stays `test_failed`; a static `generation_failed` stays `generation_failed`).
- **Budget during generation**: unchanged S2 behaviour. If the limit is reached while records are
  still `pending`, generation stops with `request_limit_reached`, those records stay `pending` and the
  job carries the S2 message "start a new job to continue". Records already `generated` still go to the
  sandbox; no repair can start (budget 0); the job ends `completed_with_issues`.
- **No S2 regeneration**: S2 has no regeneration step (a failed validation is final in S2). In S4 a
  static failure of the first write goes to the repair loop only, so the two never overlap.
- **no_code**: not repaired; stays `generation_failed / no_code`.
- **unsafe_code**: not repaired (a test that tried something dangerous is not sent back to be
  "fixed"); stays `generation_failed / unsafe_code`.
- **Early stop (FR-008)**: `test_sha256` of every write is kept in `record.attempts[]`. A repaired test
  whose hash is already there calls `finalize()` **at once** with the last cause, even if an attempt is
  left; no further request is made for that record.
- **fails_with_others (FR-011)**: repaired once only if `attempts_used < 2`; otherwise `finalize()` at
  once (`test_failed / fails_with_others`). A record repaired for `fails_with_others` that fails with the
  others again is finalized, never looped.
- **missing_dependency (FR-003)**: the S3 verdict rule stays first: `No module named X` where the root
  of `X` is neither a project top-level name nor stdlib → `environment_error / missing_dependency`.
  It is checked before `collection_error`, so it is never sent to repair. After preflight it can still
  happen when a manifest is incomplete; it is reported, not repaired.

## R6. Per-test timeout, network message, whole-run kill

- **Decision**: sandbox image adds `pytest-timeout==2.3.1` and `pytest-socket==0.7.0`. The flags go
  into the generated `pytest.ini` (`sandbox/workspace.py: PYTEST_INI`):
  `addopts = -p no:cacheprovider --timeout=30 --timeout-method=signal --disable-socket --allow-unix-socket`,
  so `run_argv()`
  — the command line — is unchanged (FR-025). `--allow-unix-socket` keeps `asyncio` working (its event
  loop uses a unix socket pair); TCP/UDP stay blocked. Image tag becomes `autotest-sandbox:py3.10-s4`.
- **Whole-run limit (FR-023)**: the `timeout_s` passed in the `RunRequest` becomes
  `min(300, max(60, 30 × tests + 30))`, where `tests` is the number of expected test **cases** of the
  record: each test function counts 1, or the length of a literal list/tuple in its
  `@pytest.mark.parametrize` (product over stacked decorators); a non-literal argument counts 1 (the cap
  of 300 still protects). The final run keeps its S3 cap of 300. So three hanging tests
  (≈ 90 s) end as per-test timeouts inside a 120 s run, not as `run_timeout`.
- **Classification in `results.verdict()`**:
  - a failed case whose message starts with `Failed: Timeout` → `test_failed / timeout` (repairable);
  - **S3 check (verified in code)**: the argv is `timeout --signal=KILL N python -m pytest …`, so a
    whole-run timeout exits **137**, the same code as an OOM kill; `RunOutput.timed_out` is set only by
    the worker's own `wait()` guard. S3's `TIMEOUT_EXIT_CODES = (124, 137)` therefore cannot tell them
    apart. S4 fix: after `wait()` the executor reads `container.attrs["State"]["OOMKilled"]` into a new
    `RunOutput.oom_killed`;
  - `oom_killed` → `environment_error / out_of_memory` (new);
  - caveat: the OOM killer usually kills pytest (a child), not PID 1 (`timeout`). Whether Docker then
    sets `OOMKilled` depends on the Docker version and cgroup v1/v2; on cgroup v2 Docker reads the
    container's `memory.events oom_kill` counter, which covers children. This must be confirmed on our
    Docker 29 / cgroup v2 host with the manual scenario in quickstart.md before relying on it; if it is
    not set for a child, the fallback is `exit 137` + `duration < timeout_s - 2` → `out_of_memory`;
  - otherwise `timed_out` or exit `124`/`137` → `environment_error / run_timeout` (new);
  - `--timeout-method=signal` is set explicitly in `PYTEST_INI`: the `thread` method kills the whole
    pytest process and loses `junit.xml`; `signal` fails only the hanging test;
  - `SocketBlockedError` in a case message keeps `assertion` but the message is clear for the prompt.
- **error_type (FR-018)**: `parse_junit()` adds `error_type` per case: the `type` attribute when
  pytest writes it, else the exception name from the last `E   Name:` line of the case text, else
  `Timeout` for a per-test timeout.
- **Rationale**: S3's `timeout --signal=KILL` kills the whole run and loses junit; per-test timeout keeps
  junit and names the hanging test.

## R7. `RunRequest` (FR-025)

- **Decision**: in `sandbox/executor.py`, rename the existing parameter object `RunSpec` to
  `RunRequest` and add `mode: str = RunMode.FULL` (`RunMode` has only `FULL` in S4). `RunSpec` stays
  as an alias so S3 call sites and tests keep working. `DockerSandboxExecutor.run()` rejects any other
  mode. The existing `test_docker_executor.py` assertions on the command must pass unchanged.

## R8. Flaky check (FR-020, FR-021)

- **Decision**: after the final run passes, stage `flaky_check`; two more runs of the same kept set
  (same `RunRequest`, `with_coverage=False`), one per `sandbox_pass`. Outcomes are compared per test
  name across the three runs; a record with any differing test → transition `ready → test_failed`
  (actor `flaky`, reason `flaky`), not repairable. If any record was removed, stage `final_run` again;
  a test failing there → `fails_with_others` with no repair and no second flaky check, and the S3 loop
  repeats without it (bounded by the number of records). Coverage comes from the last all-pass run.
- **Re-run without per-test results** (`run_timeout`, `out_of_memory`, `sandbox_unavailable`,
  `no_result_file`): the same re-run is retried once. If it fails the same way again, nothing can be
  compared: `job.flaky = {status: "inconclusive", reason}`, records stay `ready` (they passed the
  final run), coverage stays from that final run, and the job ends `completed_with_issues` with the
  notice `flaky_check_inconclusive`.

## R9. Coverage snapshot (FR-022)

- **Decision**: new collection `test_coverage_snapshots` (`snapshots.py`, Mongo + in-memory repo),
  insert-only API, unique index on `job_id`. Written once in `run_stage.finish()`:
  `{snapshot_id, project_id, version_number, job_id, source: "manual", partial: false, line_pct,
branch_pct, files: [{file, line_pct, branch_pct, statements, covered, branches, branches_covered}],
final_run_id, created_at}`. A job without an all-pass final run writes **no** snapshot (null points
  would pollute the F3 history). The unique index on `job_id` makes a repeated `finish()` a no-op
  (duplicate key caught and ignored).

## R10. Keeping manifests at upload (FR-026)

- **Finding**: manifests are dropped today in two places: `UPM_Project/core_upm/views/folder_upload_proxy.py`
  (`SUPPORTED_EXTENSIONS` has no `.txt/.toml/.cfg/.ini`) and `Ai_project/core_ai/views/folder_upload.py`
  (`IGNORED_EXTENSIONS` has `.txt`; `.toml/.cfg/.ini` pass but are analysed as code).
- **Decision**: one helper `is_support_file(path)` (names `requirements*.txt`, `pyproject.toml`,
  `setup.cfg`, `pytest.ini`, `conftest.py`). The UPM proxy forwards these names; `folder_upload.py`
  keeps them, stores them with `file_type = "support"` and `analysis_status = "NOT_ANALYSED"` and does
  **not** enqueue `analyze_code_file_task`. The test-generation gate and planner ignore `support` files
  entirely (they are neither planned nor listed as skipped). They still reach `/workspace/src` through
  `version_files()`. Kept names: base name `requirements*.txt`, **or** any `*.txt` inside a folder named
  `requirements/` (e.g. `requirements/base.txt`, so `-r requirements/base.txt` can be followed), and
  `pyproject.toml`, `setup.cfg`, `pytest.ini`, `conftest.py`. The project's own `pytest.ini` is kept but not applied in this slice (our generated
  config is used). The project's `conftest.py` sits in `/workspace/src`, which is not an ancestor of the
  test files (`/workspace/tests/…`), so pytest does not load it during our runs either. In the bundle,
  our `pytest.ini` may clash with a project `pytest.ini`; the bundle README line says to run with
  `pytest -c pytest.ini` from the bundle folder (known limit).
- **Constitution I**: these two upload files are the "keeping dependency manifests at upload" change the
  constitution explicitly allows.

## R11. Preflight install and environment cache (FR-027, FR-028, FR-036)

- **Env key**: `sha256(python_version + sorted(path + sha256(content)) of requirements*.txt,
pyproject.toml, setup.cfg)`. No manifest → nothing to install, but the import probe below still runs.
- **Requirements list**: `requirements*.txt` used as files; dependencies from `[project].dependencies`
  of `pyproject.toml` (read with `tomli`, added explicitly to `Ai_project/requirements.txt` as
  `tomli>=2.0` instead of relying on pytest pulling it in) and
  `[options] install_requires` of `setup.cfg` (`configparser`) are written to one generated
  `requirements.generated.txt`. The project itself is not installed (its code is on `PYTHONPATH`).
- **Install**: `SandboxExecutor.install(InstallRequest)` → `DockerSandboxExecutor` runs the sandbox image
  with **network `bridge`**, no environment values except `PIP_NO_CACHE_DIR=1` and
  `PIP_DISABLE_PIP_VERSION_CHECK=1`, user 10001 (non-root), `cap_drop=ALL`, `no-new-privileges`,
  1 CPU, **2 GB** memory (the 1 GB `/tmp` tmpfs counts against the same cgroup, so 1 GB would let a
  large sdist build OOM-kill pip), 256 processes, 300 s, read-only root, `/tmp` tmpfs, command
  `pip install --target /deps -r /manifests/requirements.txt`, into a named volume `sbx_env_<key[:16]>`.
  Mounts: the env volume (rw) at `/deps` and a volume with **the manifests only** (ro) at `/manifests`;
  the project's source is never mounted, so an sdist `setup.py` that runs at install time cannot read
  or change the code, and the container holds no secret.
- **Test runs**: the env volume is mounted read-only at `/workspace/deps`, and `PYTHONPATH` becomes
  `/workspace/src:/workspace/deps` (container options, not the command). Network stays `none`.
- **Lock (FR-036)**: new collection `test_envs` with unique `env_key`. Preflight does
  `insert_one({env_key, status: "building", owner_job, started_at})`:
  - inserted → this job installs, then sets `ready` (with volume) or `failed` (with pip tail);
  - duplicate → read it: `ready` → reuse; `building` → re-enqueue `sandbox_pass` with countdown 10 s;
    `building` older than 15 min → take over with a conditional update; `failed` less than
    `TESTGEN_ENV_FAILED_TTL_SECONDS` (3600) old → this job fails at once with the stored detail;
    `failed` older than that → take over with a conditional update and install once more.
    A `building` environment is never mounted.
- **Failure**: every `pending` record → `environment_error` (actor `preflight`); the job → `failed`,
  `llm_requests` stays 0. Reason from the pip output: `No matching distribution` / `Could not find a
version` (and not temporary) → `missing_dependency`; anything else (conflict, build error, a temporary
  failure after its one retry) → `install_failed`.
- **Which manifest lines are installed (FR-027)**:
  - requirement files, first rule that matches:
    1. root `requirements.txt` → only that file;
    2. a `requirements/` folder → the first that exists of `requirements/base.txt`,
       `requirements/common.txt`, `requirements/requirements.txt`, `requirements/main.txt` (only that
       file — a cookiecutter `local.txt` / `production.txt` is never merged);
    3. otherwise every kept `requirements*.txt` whose name has **no word** from the exclusion set
       `dev, develop, development, doc, docs, test, tests, testing, lint, prod, production, local,
staging, ci`. Names are lower-cased, the `.txt` removed, then split on `-`, `_` and `.`, and the
       **words** are compared (so `requirements-latest.txt` or `requirements_contest.txt` are kept,
       `requirements-prod.txt` is not);
       plus `[project].dependencies` and `install_requires`. Pins are merged as written; a real conflict
       is a definite `install_failed`. Files left out are listed in `job.preflight.warnings`;
  - `-r X` is followed only when `X` is a kept file; otherwise the line is dropped;
  - `-e …`, `-c …`, `--index-url`, `--extra-index-url`, `--find-links`, other options → dropped
    (the project itself is already on `PYTHONPATH`; private indexes are out of scope);
  - every dropped line is stored in `job.preflight.warnings` and shown on the job.
- **`.pth` files**: `pip install --target` does not process `.pth` files and `PYTHONPATH` does not
  either, so old namespace packages (e.g. `google-*`) may not import. After a successful install the
  container writes `/deps/sitecustomize.py` with `import site; site.addsitedir("/workspace/deps")`;
  Python imports `sitecustomize` at start-up from `PYTHONPATH`, which processes the `.pth` files.
- **Definite vs temporary failure (FR-028)**: the **temporary** markers are checked **first, on the
  whole pip output** (not only its tail): `Retrying (Retry(`, `Connection`, `ConnectTimeout`,
  `ReadTimeout`, `Temporary failure in name resolution`, `Name or service not known`, or the install time
  limit. If any is present the failure is temporary, whatever else the output says (pip prints
  `No matching distribution found` after failed retries when the network is down). Only without them:
  definite = `No matching distribution`, `ResolutionImpossible`, `conflicting dependencies`,
  `Could not find a version`; any other pip error is also treated as definite. A definite failure is
  stored `failed` and reused for `TESTGEN_ENV_FAILED_TTL_SECONDS`. A temporary failure is stored
  `failed_temporary`, never reused: the same job retries once after 30 s (re-enqueue;
  `job.preflight.install_tries` counts 1 → 2), then fails with `install_failed`; the next job takes the
  entry over at once.
- **Install scratch space**: `/tmp` is a tmpfs of **1 GB** with `TMPDIR=/tmp` (sdist builds), inside the
  2 GB memory limit; the env volume has no quota of its own (Docker local volumes), its size is recorded
  after install.
- **Clean-up of `sbx_env_*`**: `test_envs` keeps `last_used_at` (set on every reuse). At the start of
  each preflight pass, `envs.reap()` removes `ready` and `failed` entries not used for
  `TESTGEN_ENV_KEEP_DAYS` (7) and their volumes; a volume Docker reports as in use is skipped and tried
  next time. At most one reap per hour, guarded by Redis `SET testgen:env_reaper 1 NX EX 3600` (Redis is
  already there for Celery); nothing extra is stored in `test_envs`.
- **Import probe (closes the "no or incomplete manifest" gap)**: last step of every preflight, also
  when there is no manifest. `preflight` scans the AST of the version's Python files (already analysed)
  for top-level imports whose root is neither a project top-level name nor stdlib
  (`sys.stdlib_module_names`). If there are none, the probe is skipped. Otherwise
  `executor.probe_imports(ProbeRequest(src_volume, env_volume | None, modules))` (`env_volume` is
  `None` when there is no manifest; then `PYTHONPATH` is `/workspace/src` only) runs the sandbox image
  with **network `none`**, the test-run isolation, 1 GB, **60 s**, and the command
  `python -c <fixed script>` that imports the modules one by one and prints **one JSON line per module
  as it goes** (flushed), so the results already printed survive a time-out:
  `{"module": m, "ok": true}` or `{"module": m, "error_type": …, "missing_name": e.name, "msg": …}`.
  Classification:
  - `ModuleNotFoundError` whose `name` is the module or its root → **missing** → records
    `environment_error / missing_dependency` (detail = module);
  - any other error (`ImportError` for a missing system library such as `libGL`, `OSError`, a
    `ModuleNotFoundError` for a _different_ name inside the library, any exception at import) →
    records `environment_error / import_failed` (detail = `<ErrorType>: <msg>`, cut to 300 chars);
  - modules with no line because the probe hit its time or memory limit (heavy libraries such as
    `torch`) → **not marked**; one warning `import probe incomplete: <modules>` on the job;
  - probe container cannot start → warning only.
    The records concerned are those whose file imports the module — directly or through project modules
    that import it (closure over the project's own import edges); the other records go on to
    generation. If **every** record is marked the job fails as above. `probe_imports` is a separate
    executor method, not a `RunRequest` mode, so FR-025 holds. Cost: one short container per job; no
    model request. New reason code `import_failed` (in `RUN_ENV_REASONS`).

## R12. Finer skip reasons (FR-019)

- **Decision**: where `runner.py` sets `analysis_failed`, it inspects the stored content once:
  empty or whitespace → `empty_file`; NUL bytes or > 30 % non-printable characters → `binary_file`;
  `ast.parse` fails → `syntax_error`; otherwise keep `analysis_failed`. New `SkipReason` constants.

## R13. Settings

| Setting                                                      | Value                        |
| ------------------------------------------------------------ | ---------------------------- |
| `TESTGEN_MAX_REQUESTS_PER_JOB`                               | 30 (was 20)                  |
| `TESTGEN_MAX_REPAIR_ATTEMPTS`                                | 2                            |
| `TESTGEN_REPAIR_OUTPUT_CHARS`                                | 3000                         |
| `TESTGEN_PER_TEST_TIMEOUT_SECONDS`                           | 30                           |
| `TESTGEN_FLAKY_RERUNS`                                       | 2                            |
| `TESTGEN_SANDBOX_IMAGE`                                      | `autotest-sandbox:py3.10-s4` |
| `TESTGEN_INSTALL_TIMEOUT_SECONDS`                            | 300                          |
| `TESTGEN_INSTALL_MEMORY`                                     | `2g`                         |
| `TESTGEN_ENV_LOCK_STALE_SECONDS`                             | 900                          |
| `TESTGEN_ENV_FAILED_TTL_SECONDS`                             | 3600                         |
| `TESTGEN_ENV_KEEP_DAYS`                                      | 7                            |
| `TESTGEN_PROBE_TIMEOUT_SECONDS`                              | 60                           |
| `TESTGEN_PROBE_MEMORY`                                       | `1g`                         |
| `TESTGEN_INSTALL_TMPFS`                                      | `1g`                         |
| `TEST_COVERAGE_SNAPSHOTS_COLLECTION`, `TEST_ENVS_COLLECTION` | collection names             |
