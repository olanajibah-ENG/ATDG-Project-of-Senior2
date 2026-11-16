# AutoTest & DocGen Manager — Feature 1 (Trusted Test Generation) Constitution

## Core Principles

### I. Feature 1 Only, Same Layout as the Other Features

This constitution governs Feature 1 (Generate Trusted Tests) and nothing else.

- Feature 1 lives inside the existing AI service, inside the `core_ai` app, laid out the same way
  as logical explanation and conflict detection. It is not a separate Django app and not a new
  microservice.
- Its logic MUST live in the package `Ai_project/core_ai/services/test_generation/`.
- Its entry points are shared with the other features, one file each:
  `core_ai/views/testgen_views.py`, `core_ai/serializers/testgen_serializer.py`,
  `core_ai/celery_tasks/testgen_tasks.py`, `core_ai/models/testgen.py`, routes in `core_ai/urls.py`,
  tests under `core_ai/tests/test_generation/`, reports under `core_ai/tests/reports/`.
- Other existing files MUST NOT change, except for the small changes a slice's plan lists by file
  (for example adding settings, adding `call_model_ex`, keeping dependency manifests at upload,
  adding queues and workers).
- The package MAY read what analysis stores and MAY call its analysis task. It MUST NOT import
  from another feature (`core_ai/services/conflict_detection`, the explanation engine), and no
  other feature may import from it. A test checks this on every run.
- Conflict detection (`core_ai/services/conflict_detection`) and its evaluation MUST keep
  producing the same results after every slice.

Rationale: three features share this service. One layout for all three keeps the code easy to
find; the boundary between them is kept by an automated test instead of by a separate app.

### II. Trusted Means Proven (NON-NEGOTIABLE)

- A test MUST NOT reach `ready` without a clean sandbox pass, with the network off, on the same
  project version it was generated for.
- `ready` MUST be set only through the acceptance gate, together with its evidence (run id,
  version number, body hash).
- Coverage MUST be taken from the final all-pass run and from no other run.
- "Trusted" means executable, isolated and stable on the analysed version. It MUST NOT be
  presented as proof that the code's logic is correct.

Rationale: the product promise is that a delivered test really runs. Anything weaker makes the
`ready` label meaningless.

### III. Bounded, Recorded LLM Use

- The LLM MUST see the Context DTO only, never the whole repository.
- A test MUST be repaired at most 3 times.
- Every LLM call MUST be recorded with its purpose, model and token counts.
- All LLM access MUST go through `LLMFacade`.
- Automated tests of this feature MUST NOT make real LLM calls.

Rationale: the free tier allows about 50 requests a day, and measurements must be repeatable.

### IV. Python + pytest First

- Only Python source is analysed and only pytest tests are generated.
- A non-Python file MUST be recorded as `skipped` with reason `unsupported_language`, and the
  batch MUST continue.
- Language-specific logic MUST sit behind `LanguageAdapter`, so that a second language is one
  adapter plus one registry line.
- A second language runtime is out of scope.

### V. One Shared Graph

- The unified `nodes` / `edges` / `meta` graph shape MUST be kept. It is the same graph the
  logical-explanation module reads.
- Graphify additions for testing (call resolution, builtins, confidence tiers, `io_kind`,
  file-qualified ids, project merge, neighbour queries, cache) MUST be implemented under
  `core_ai/services/test_generation/graphify/`.
- Branch, boundary and exception hints MUST come from the unit's own AST, not from the graph.
- Integration groups MUST use `EXTRACTED` call edges only, with depth ≤ 2 and size ≤ 4.

### VI. Small Slices, Reviewed Before Code

- Work proceeds one slice at a time, in the order S1 to S6.
- Each slice has one goal, one acceptance check and an explicit out-of-scope list.
- The spec and the plan of a slice MUST be reviewed and approved by the project owner before
  any code for that slice is written.
- Nothing outside the current slice may be implemented.
- The next slice starts only after the current slice's acceptance check passes.

### VII. Honest Statuses, Batch Continues

- Every record ends in exactly one status: `ready`, `skipped`, `generation_failed`,
  `environment_error` or `test_failed`.
- A skip MUST carry a reason code. A failure MUST carry its class.
- Install, timeout and resource problems are `environment_error`. They MUST NOT be reported as
  a logic result.
- One unit's failure MUST NOT stop the rest of the job.

## Additional Constraints

**Stack**: Django + DRF, Celery + Redis, MongoDB + GridFS, the existing `LLMClient` (OpenRouter).

**API**: routes live under `/api/analysis/tests/`. They require JWT, not `AllowAny`. Every job
belongs to the user who requested it. The request body carries `project_id`, optional
`version_number`, optional `paths` and optional `levels`; it never carries a snapshot.

**Tasks**: a Celery task MUST NOT wait on another task. The analysis gate polls and re-enqueues.

**Sandbox**: install runs with the network on and no secrets. Test runs have the network off,
a read-only filesystem and limits on CPU, memory, time and process count.

**Secrets**: keys live in `.env` only and are never passed into the sandbox.

**Out of scope for the whole feature**: webhooks, Playwright or browser tests, a quota product,
a second language runtime, whole-system end-to-end tests.

**Patterns**: Pipeline (Template Method), `TestKindStrategy`, `LanguageAdapter`, `LLMFacade`,
`SandboxExecutor` adapter, acceptance gate with a status state machine.

## Development Workflow

- Per slice: specify → clarify → plan → tasks → implement → acceptance check.
- Tests run inside the `ai_web` Docker image, because the local tree-sitter version differs.
- Every slice ships tests for its own code, and an Arabic `.md` report under
  `Ai_project/core_ai/tests/reports/` saying what was tested and what the results were.
- One commit (or a small series) per slice, made after its acceptance check passes.
- Results are reported as they are: a failing test is reported as failing, with its output.

## Governance

- This constitution takes precedence over other practice notes for Feature 1.
- An amendment needs the project owner's approval and a version bump: MAJOR for removing or
  redefining a principle, MINOR for a new principle or section, PATCH for wording.
- Every plan MUST include a constitution check, and any deviation MUST be justified in writing
  in that plan.

**Version**: 2.0.0 | **Ratified**: 2026-11-13 | **Last Amended**: 2026-11-16
