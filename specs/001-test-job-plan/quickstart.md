# Quickstart: trying S1

## Before you start

1. Stop any other copy of the project that holds the same container names, then from the repo
   root run `docker compose up -d`.
2. After pulling this slice, restart the two AI containers so they load the new app and the new
   environment variable: `docker compose up -d ai_web celery_worker`.
3. Check that `.env` has `UPM_DJANGO_SECRET_KEY`. docker compose passes it to the AI service as
   `UPM_JWT_SIGNING_KEY`.

## Automated tests

From the repo root (Git Bash):

```bash
MSYS_NO_PATHCONV=1 docker compose run --rm --no-deps -T -e PYTHONIOENCODING=utf-8 --entrypoint sh ai_web -c "pip install -q pytest >/dev/null 2>&1; python -m pytest core_testing/tests core_ai/tests -q -p no:cacheprovider"
```

Expected: every test passes, including the 210 that existed before this slice.

## Postman sequence

Use `http://localhost` (nginx). Save the values in braces as Postman variables.

| # | Request | Expect |
|---|---------|--------|
| 1 | `POST /api/upm/login/` with your username and password | 200; save the access token as `{{token}}` |
| 2 | `POST /api/upm/projects/` | save the project id as `{{project_id}}` |
| 3 | `POST /api/upm/projects/{{project_id}}/folder-upload/` with the sample `game.py` | note the `version_number` |
| 4 | `GET /api/upm/projects/{{project_id}}/tree/` | copy the file's `filepath` |
| 5 | `POST /api/analysis/tests/jobs/` with body `{"project_id": "{{project_id}}"}` and header `Authorization: Bearer {{token}}` | 202; save `job_id` as `{{job_id}}` |
| 6 | `GET /api/analysis/tests/jobs/{{job_id}}/` every 2 s | `status` reaches `completed`, `stage` reaches `planned` |
| 7 | `GET /api/analysis/tests/jobs/{{job_id}}/plan/` | 14 units, an empty `skipped` list, `work_items_count` 42 |

## Negative checks

| Request | Expect |
|---------|--------|
| step 5 with no `Authorization` header | 401 `unauthorized` |
| step 6 with another user's token | 403 `forbidden` |
| step 5 with `"version_number": 999` | 400 `validation_error` |
| step 5 with `"paths": ["nope.py"]` | 400 `validation_error`, `details.paths` lists `nope.py` |
| step 5 with `"levels": ["smoke"]` | 400 `validation_error` |
| step 5 on a version that holds only non-Python files | 422 `no_python_files` |
| `GET .../jobs/job_000000000000/` | 404 `not_found` |

## Checking that no model was called

Watch the worker while a job runs: `docker compose logs -f celery_worker`. No `[LLM` line may
appear for the job. The automated suite checks the same thing without a network.
