# Quickstart: trying S2

## Before you start

1. Load the new code in both AI containers and wait until `ai_web` is healthy:
   `docker compose restart ai_web celery_worker` then `docker compose ps ai_web`.
2. `.env` must hold `OPENROUTER_API_KEY`. Each unit costs one request of the free tier's daily
   allowance (about 50). The sample `task.py` has 9 units.

## Automated tests (no model, no database)

```bash
MSYS_NO_PATHCONV=1 docker compose run --rm --no-deps -T -e PYTHONIOENCODING=utf-8 --entrypoint sh ai_web -c "pip install -q pytest >/dev/null 2>&1; python -m pytest core_testing/tests core_ai/tests test_graphify_implementation.py -q -p no:cacheprovider"
```

Expected: every test passes, including the 343 that existed before this slice.

## Postman sequence

All requests carry `Authorization: Bearer <access>` from `POST http://localhost/api/token/`.

| # | Request | Expect |
|---|---------|--------|
| 1 | `POST /api/analysis/tests/jobs/` with `{"project_id": "task_test", "levels": ["unit"]}` | 202 and a `job_id` |
| 2 | `GET /api/analysis/tests/jobs/{job_id}/` every few seconds | `stage` goes `generating`, `progress.done` grows by one per unit, then `status` is `completed` or `completed_with_issues` and `stage` is `generated` |
| 3 | `GET /api/analysis/tests/jobs/{job_id}/records/` | 9 items of level `unit`, each `generated` or `generation_failed` with a `reason_code` |
| 4 | `GET /api/analysis/tests/jobs/{job_id}/records/?status=generated` | only the generated ones |
| 5 | `GET /api/analysis/tests/jobs/{job_id}/records/{id}/` for a generated record | `test_code` holds a pytest file, `executed` is false |
| 6 | Start the same job again (step 1) | it finishes in seconds: every answer is reused and no new request is spent |

Read one generated test and check by eye: it imports from `task`, its test functions are named
`test_<Class>_<method>__unit_<n>`, each has an `assert`, and it calls the method it is about.

## Negative checks

| Request | Expect |
|---------|--------|
| step 3 with another user's token | 403 `forbidden` |
| step 3 with `?status=nonsense` | 400 `validation_error` |
| step 5 with an unknown record id | 404 `not_found` |

## If the model is not available

The job ends as `completed_with_issues`, `error.code` is `model_unavailable`, and the unit records
not yet handled are `pending`. Nothing is marked as failed. Try again later with a new job.

## What to watch in the worker log

`docker compose logs -f celery_worker` shows one `[LLM] Success with <model>` line per unit on the
first job, and none on the repeated job of step 6.
