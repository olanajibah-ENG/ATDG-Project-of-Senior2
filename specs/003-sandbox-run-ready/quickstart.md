# Quickstart: trying S3

## Before you start

- Docker Desktop running; the stack up with the new services:
  `docker compose build testgen_sandbox_image testgen_sandbox_worker` then `docker compose up -d`.
- `docker image ls autotest-sandbox` shows `py3.10-s3`.
- `docker compose logs testgen_sandbox_worker` shows the worker ready on queue `test_sandbox`.
- After restarting `ai_web`, also restart `upm_api_gateway` (otherwise 502).

## Automated tests (no container, no model)

```text
docker compose run --rm --no-deps -T --entrypoint sh ai_web -c \
  "pip install -q pytest; python -m pytest core_ai/tests test_graphify_implementation.py -q"
```

Expected: everything passes, including the new S3 tests, which use `FakeSandboxExecutor`; one test
checks the exact container options without starting a container.

## Postman sequence (real containers)

1. `POST /api/upm/login/` → token.
2. `POST /api/analysis/tests/jobs/` with `{"project_id": "<demo3>", "paths": ["demo/course.py"], "levels": ["unit"]}` → `202`, `job_id`.
3. `GET jobs/{job_id}/` until `status` is `completed` or `completed_with_issues`. Watch `stage` go
   `generating → generated → sandbox_run → final_run`, and `by_status.ready` grow.
4. `GET jobs/{job_id}/records/?status=ready` → the ready records.
5. `GET jobs/{job_id}/records/{record_id}/` → `executed: true`, `run.tests`, `evidence`,
   `coverage_contribution`.
6. `GET jobs/{job_id}/coverage/` → per-file line and branch figures.
7. `GET jobs/{job_id}/bundle/` → save the ZIP. Unzip, copy the version's code next to it as `src/`,
   run `pytest` → all pass.

## Isolation checks (acceptance)

Run with records whose stored test code is replaced by a test made for the check (a helper script in
the quickstart of the acceptance report does this on a copy of a job):

| Test does | Expected record |
|---|---|
| `socket.create_connection(("example.com", 80))` | `test_failed / assertion` (network unreachable) |
| `while True: pass` | `test_failed / timeout`, after about 60 s |
| `open("/workspace/src/demo/course.py", "w")` | `test_failed / assertion` (read-only file system); stored file unchanged |
| `assert course.capacity == "2"` | `test_failed / assertion`, message `assert 2 == '2'` |
| imports a module the project does not have, from project code | `environment_error / missing_dependency` |

## Negative API checks

- `GET coverage/` and `GET bundle/` while the job runs → `409`.
- The same routes with another user's token → `403`; without a token → `401`.

## What to watch in the sandbox worker log

`[SANDBOX] run sbx_… started`, `exit=0 tests=3 passed=3 → ready`,
`exit=1 → test_failed/assertion`, `final run: 4 tests, all passed, coverage 92.3%`.
