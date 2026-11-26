# Quickstart: validating S4

## Prerequisites

- S3 is committed (`34bbb69`) and pushed before S4 code starts.
- Rebuild the sandbox image (adds pytest-timeout and pytest-socket):
  `docker compose build testgen_sandbox_image` → `autotest-sandbox:py3.10-s4`.
- Restart `ai_web`, `celery_worker`, `testgen_sandbox_worker` after settings change.

## 1. Automated tests (no model, no container)

```powershell
docker exec -it ai_django_app python -m pytest core_ai/tests/test_generation -q
```

Expected: all S1–S3 tests still pass; new tests cover every row of the final classification table
(spec FR-016), every guard rule (FR-014), the transition table (FR-017), the flaky check, the snapshot,
preflight lock/reuse/failure, upload support files, and `RunRequest(mode="full")` producing the S3
command unchanged.

## 2. Real run — repair and suspected bug

1. Upload a small Python project with a planted bug (a function whose docstring says "returns 0 for an
   empty list" but returns `None`) and a `requirements.txt` with one small library.
2. `POST /api/analysis/tests/jobs/` with `levels: ["unit"]`.
3. Poll `GET jobs/{id}/`: stages pass through `preflight`, `generating`, `sandbox_run`, `repairing`,
   `final_run`, `flaky_check`.
4. Check: the planted-bug record ends `test_failed / suspected_code_bug` with `explanation`; no
   weakened test is `ready`; no record has more than 3 writes; `llm_requests ≤ 30`.

## 3. Real run — environment failure before any model request

Upload a project whose `requirements.txt` lists `this-package-does-not-exist==0.0.1`. Expected: job
`failed`, every record `environment_error / missing_dependency`, `llm_requests == 0`.

Upload a second project with **no** manifest whose code does `import requests`. Expected: the
import probe marks the records that need `requests` `environment_error / missing_dependency` before
any model request; records of files that do not need it are generated as usual.

## 4. Flaky and snapshot

Covered by automated tests with a scripted fake executor (a test that alternates pass/fail). After a
finished job with an all-pass final run: exactly one document in `test_coverage_snapshots` with that
`job_id`; after a job without one: none.

## 5. Manual Docker check — whole-run timeout vs out of memory

The fakes cannot prove what Docker reports; S3 got this wrong (exit 137 for both). On the real
`testgen_sandbox_worker`, with the `py3.10-s4` image, run two one-record jobs on a tiny project:

1. a test that allocates memory until it dies (`b = bytearray(2 * 1024**3)`) → expected
   `environment_error / out_of_memory`, and `docker inspect` of the container shows
   `State.OOMKilled=true` (or the fallback of research R6 applies);
2. a test whose **module level** sleeps 400 s (outside any test function, so pytest-timeout does not
   cover it) → expected `environment_error / run_timeout` after the whole-run limit.

Record the Docker version, cgroup version, exit code, `OOMKilled` value and duration of both in the
report. If `OOMKilled` is `false` in case 1, switch to the fallback rule and re-run.

## 6. Report

Write `Ai_project/core_ai/tests/reports/testgen_s4_repair.md` (Arabic): what was tested, results,
real-run numbers.
