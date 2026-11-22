# Research: S3 — Isolated Run, Acceptance Gate, Coverage and Bundle

Checked on the development machine (2026-11-20): Docker Engine 29.1.3 (API 1.52, Linux, cgroup v2),
8 CPUs, 8 GB for Docker. The `ai_web` image is built `FROM python:3.10-slim`, which is already on
the machine.

## R1. Who starts the run containers

**Decision**: a new Celery worker service, `testgen_sandbox_worker`, built from the same `Ai_project`
image as `celery_worker`, consuming only a new queue `test_sandbox`, with the host's Docker socket
mounted (`/var/run/docker.sock`). It talks to the engine with the Docker SDK for Python (`docker`
package). It gets the database settings it needs to read files and write results, and **no**
`OPENROUTER_API_KEY`, no `UPM_JWT_SIGNING_KEY`, no other key.

**Rationale**: the run must be a real container with `--network none` and the other limits
(Principle II, spec FR-005). Only the engine can create one, so the component that asks for it needs
the socket. Putting that power in one worker that does nothing else keeps it away from the model, the
API and the keys (FR-007). The existing `celery_worker` keeps its default queue and never sees the
socket.

**Alternatives considered**:
- Run pytest as a subprocess inside the worker, block sockets with a pytest plugin. Rejected: the
  network block is a Python-level patch the test can undo, the source is not read-only, there is no
  process or memory limit — it does not meet the constitution.
- Docker-in-Docker (a privileged `dind` service). Rejected: needs `--privileged`, which is worse than
  the socket, and is heavier.
- A separate runner host or a gVisor/Firecracker runtime. Right for production, out of reach for the
  local Compose setup; noted as the production path.

## R2. Getting files into a container that is read-only

**Decision**: per run, the worker creates three **named volumes** (as in the design document):
`<run>_src` (the version's code), `<run>_tests` (the test file + runner config) and `<run>_out`
(results). It fills `_src` and `_tests` by creating a short-lived **loader** container (same image,
not started, volumes mounted read-write) and calling `put_archive` with a tar built in memory; the
loader is then removed. The **run** container mounts `_src` and `_tests` read-only and `_out`
read-write. After the run, the worker reads `/out` with `get_archive` from the stopped run container,
then removes the container and the three volumes.

The project code (`_src`) is built once per job and reused by every record of that job (it is only
ever mounted read-only); `_tests` and `_out` are per run.

**Rationale**: `--read-only` forbids copying into the container's own filesystem, and bind mounts of
the worker's folders would point at paths that do not exist on the host (the worker is itself a
container). Named volumes are managed by the same engine and work the same on Windows and Linux.

**Alternatives considered**: a shared bind folder (`sandbox_work`) mounted in the worker and in the
run containers — rejected because the host path of a Compose volume differs per platform; building a
per-job image with the code inside — rejected, slow and fills the disk.

## R3. The run image

**Decision**: `autotest-sandbox:py3.10-s3`, built from
`core_ai/services/test_generation/sandbox/image/Dockerfile`:
`FROM python:3.10-slim`, `pip install --no-cache-dir pytest==8.3.3 pytest-cov==5.0.0`, a user
`10001:10001`, `WORKDIR /workspace`, `/out` created and owned by `10001`. Built by a Compose service
`testgen_sandbox_image` that only builds (its command exits at once), so `docker compose build`
produces it.

**Rationale**: the base image is already on the machine and is the same Python the analysers use, so
code that the analysis parsed is code that this Python runs. Pinned tool versions make runs
repeatable.

**Alternatives considered**: Python 3.13 as in the design document — later, when we have a reason;
it needs a new base image and the analysers stay on 3.10.

## R4. The exact run command

**Decision**: per record:

```text
create container from autotest-sandbox:py3.10-s3
  network_mode="none", read_only=True, tmpfs={"/tmp": "rw,size=64m"},
  nano_cpus=1e9, mem_limit="512m", memswap_limit="512m", pids_limit=128,
  cap_drop=["ALL"], security_opt=["no-new-privileges"], user="10001:10001",
  volumes: <run>_src → /workspace/src (ro), <run>_tests → /workspace/tests (ro), <run>_out → /out (rw)
  environment: PYTHONPATH=/workspace/src, PYTHONDONTWRITEBYTECODE=1, COVERAGE_FILE=/tmp/.coverage  (nothing else;
  the coverage data file must go to /tmp because the working directory is read-only — found while implementing)
command:
  timeout --signal=KILL 60 python -m pytest tests/<test path> -q -p no:cacheprovider
      --junitxml=/out/junit.xml --cov=/workspace/src --cov-branch --cov-report=json:/out/cov.json
```

The worker also waits at most 60 + 15 seconds for the container; past that it kills it (a second
guard if `timeout` itself is defeated). The final run uses the same options with all `ready` test
files and a time limit of `min(60 + 15 × n, 300)` seconds.

**Rationale**: these are the design document's options, item for item, translated to the SDK. The
environment is set explicitly so nothing of the worker's environment (database URL, Django settings)
leaks into the run (FR-006).

## R5. Reading the outcome

**Decision**: the outcome is decided from three things together:

1. the **exit code** (pytest: 0 all passed, 1 some failed, 2 interrupted/collection error, 5 no tests;
   137 = killed by `timeout`; anything else = environment);
2. `/out/junit.xml`, parsed with the standard library's `xml.etree.ElementTree` with a size cap
   (1 MB) — every `<testcase>` with its `<failure>`, `<error>` or `<skipped>` child and message;
3. the **expected test names**: the names of the `test_…` functions in the stored test code (read
   from its syntax tree, as the validator did in S2).

Decision table (first match wins):

| Condition | Status / reason |
|---|---|
| container could not be created or started | `environment_error / sandbox_unavailable` |
| exit 137, or the worker's own wait ran out | `test_failed / timeout` |
| no readable `junit.xml` | `environment_error / no_result_file` |
| an `<error>` whose message has `ModuleNotFoundError: No module named 'X'` and `X` is not a top-level package or module of the version | `environment_error / missing_dependency` (module `X`) |
| any other collection `<error>` (exit 2) | `test_failed / collection_error` |
| exit 5, or zero `<testcase>` | `test_failed / no_tests` |
| any `<failure>` or test `<error>` | `test_failed / assertion` (first failure's message) |
| any `<skipped>` | `test_failed / skipped_test` |
| exit 0, every expected test name present and passed, no extra name | **acceptance gate → `ready`** |
| anything else (names do not match, exit 0 with failures) | `environment_error / no_result_file` |

**Rationale**: the structured file gives per-test outcomes (FR-009, FR-013). Requiring both exit 0
and the expected names makes a forged result file much harder: a test would have to know and write
the right names *and* stop pytest from writing its own file (R6).

## R6. A test that tries to fake its own result

A test runs as the same user as pytest and `/out` is writable, so in principle it could write a fake
`junit.xml` and end the process before pytest overwrites it.

**Decision**: defence in depth. (1) The S2 safety lint gains `os._exit`, `sys.exit`, `os.kill`,
`signal.*` and any write whose target mentions `/out` — such a test never reaches `generated`.
(2) R5 requires exit 0 *and* the exact expected names. (3) The final run re-runs every `ready` test in
a new container; a test that only fakes its own run is caught there unless it fakes that too.

**Rationale**: generated tests are not adversarial by intent, but the gate must not be trivially
fooled. Moving the result file out of the test's reach would need running pytest under a second user,
which the read-only, no-privilege container cannot do; the checks above are enough for this slice and
are written down as a known limit.

## R7. Missing dependency vs. a wrong test

**Decision**: when collection fails with `No module named 'X'`, compare `X`'s first segment with the
top-level names of the version's Python files (`demo/course.py` → `demo`, `game.py` → `game`). In the
list → the test imported a wrong project path → `collection_error`. Not in the list and not standard
library → the project needs a library → `environment_error / missing_dependency`.

**Rationale**: S4 must repair only what the test got wrong; a missing library is not the test's fault
and must not cost repair attempts.

## R8. One record per pass, on its own queue

**Decision**: the generation phase ends (no pending `unit` record) by setting the job's stage to
`sandbox_run` and enqueuing `core_ai.testgen.sandbox_pass` on `test_sandbox` — instead of finishing
the job. Each sandbox pass runs **one** record (the next `generated` one) and re-enqueues itself.
When none is left it runs the final run (R9), writes the coverage and finishes the job. Routing:
`CELERY_TASK_ROUTES = {"core_ai.testgen.sandbox_pass": {"queue": "test_sandbox"}}`; the sandbox
worker runs with `-Q test_sandbox --concurrency 2`.

**Rationale**: the same "one short pass, re-enqueue" rule as S1 and S2 (no task waits on a task);
progress is visible after every record; the stale-job rule already fails a job whose passes stop.

## R9. The final run and coverage

**Decision**: after the last record, the worker builds one `_tests` volume with every `ready` test
file and runs them together (R4). If any test fails there, its record becomes
`test_failed / fails_with_others`, the run is repeated without it (at most as many repeats as there
were `ready` records), and the coverage is taken from the first run in which all passed (FR-016,
FR-017). `cov.json` (coverage.py JSON, format 3) is reduced to the per-file report of FR-018: paths
under `/workspace/src/` are made relative; uncovered lines that fall inside a unit the plan skipped
(`line_start`–`line_end` of that unit in the stored analysis) get the plan's reason. Each record's own
`cov.json` is reduced the same way and stored as its contribution (FR-019).

## R10. The bundle

**Decision**: built on request, in memory, with `zipfile`, never stored. Content per FR-025;
`pytest.ini` holds `[pytest]` with `pythonpath = src` and `addopts = -p no:cacheprovider`, so after
copying the project next to it as `src/`, `pytest` runs. `MANIFEST.json` lists every file with its
SHA-256. Name: `<job_id>_<project>_v<version>.zip`. A job that is not finished → `409 bundle_not_ready`.

## R11. What the automated tests use

**Decision**: a `SandboxExecutor` interface with two implementations: `DockerSandboxExecutor` (the
real one, R2–R4) and `FakeSandboxExecutor`, which returns scripted exit codes, `junit.xml` and
`cov.json` content. The run pass, the acceptance gate, the final run, the coverage report and the
bundle are all tested with the fake. One test asserts the exact options `DockerSandboxExecutor`
passes to the SDK, with the SDK client replaced by a recorder, so no container starts (FR-027). The
real engine is used only in the acceptance check (quickstart).

## R12. Settings

`TESTGEN_SANDBOX_IMAGE = "autotest-sandbox:py3.10-s3"`, `TESTGEN_SANDBOX_TIMEOUT_SECONDS = 60`,
`TESTGEN_SANDBOX_FINAL_MAX_SECONDS = 300`, `TESTGEN_SANDBOX_MEMORY = "512m"`,
`TESTGEN_SANDBOX_PIDS = 128`, `TESTGEN_SANDBOX_OUTPUT_LIMIT = 20000` (characters of printed output
kept), `TEST_RUNS_COLLECTION = "test_runs"`, and the task route of R8.
