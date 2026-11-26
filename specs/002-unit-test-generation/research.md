# Research: S2 — Unit Test Generation

## R1. Getting model name and token counts out of the client

**Finding**: `LLMClient.call_model` sweeps a list of free models, moves to the next one on 429 /
404 / 400 / 5xx / empty answer, caches identical prompts for 48 hours in Django's cache, and
returns the text only. When every model is busy it raises a plain `Exception`. Its temperature
defaults to 0.7 and `max_tokens` is fixed at 4000.

**Decision**: move the sweep into one inner method that returns text, model and usage.
`call_model` calls it and returns the text, exactly as before. A new `call_model_ex(system_prompt,
user_prompt, *, model=None, temperature=0.0, max_tokens=4000, force_request=False)` returns
`{"text", "model", "prompt_tokens", "completion_tokens"}` and does not use the 48-hour cache.
The final "all models busy" error becomes `LLMUnavailable`, a subclass of `Exception`, so every
existing `except Exception` keeps working.

**Why not copy the loop**: two copies of the retry rules would drift apart.

**Set aside**: reading usage from a response header, or estimating tokens locally — the provider
returns `usage` in the response body.

## R2. One door to the model

**Decision**: `core_ai/services/test_generation/llm_facade.py` is the only module in `core_testing` allowed to import
the client. `LLMFacade.complete(...)` takes the two prompt texts and the ids of the job and the
record, calls `call_model_ex` with temperature 0, writes one attempt, and returns the text. It
turns `LLMUnavailable`, a missing API key and network failures into one exception,
`ModelUnavailable`. The client function is passed into the facade, so tests pass a fake.

## R3. Reusing answers

**Finding**: the client's own cache is keyed by prompt text, lives in Django's cache for 48 hours,
and cannot say "this answer was reused" for the attempt record.

**Decision**: `core_testing` keeps its own reuse rule. Each attempt stores a `request_hash` =
SHA-256 of the prompt version and the context. Before asking the model, generation looks for an
earlier attempt with the same hash that produced an answer; if found, that answer is used again,
a new attempt is written with `reused: true` and zero tokens, and the job's request count does not
move. The client's own cache is switched off for these calls.

**Why**: it survives restarts, it is visible in the data, and a job started the next day finishes
what an earlier job could not, without paying twice.

## R4. One unit per pass

**Decision**: a generation pass handles exactly one record and then re-enqueues the task with no
delay. A pass never loops over all units.

**Why**: a model request can take minutes on the free tier (the client waits and sweeps). One unit
per pass keeps every task short, makes progress visible after each unit, lets the existing
stale-job rule work unchanged (a job with no update for 720 seconds is failed), and means a worker
restart loses at most one unit's work.

## R5. Keeping S1's behaviour and tests

**Finding**: S1's `run_pass` ends a job as `completed` / `planned`, and its tests assert that.

**Decision**: `run_pass` gets one optional argument, `then_generate=False`. With the default it
behaves exactly as in S1. The Celery task passes `True`: planning then creates the records and
leaves the job `running` / `generating` instead of finishing it. A job that requested no `unit`
level still finishes as in S1.

## R6. Where the unit's details come from

Everything is already stored by analysis; nothing is re-parsed from source.

| Context part | Source |
|--------------|--------|
| signature, parameters, return type, decorators, docstring, body | the unit's entry in `class_diagram_data` |
| class name, parent classes, constructor signature, attributes | the class entry in `class_diagram_data` |
| callee signatures | `plan.units[].callees` (S1) → each callee's entry |
| externals | new: `plan.units[].externals`, taken from the unit's `calls` edges to `ext.*`, without Python builtins |
| import statement | the file path: `pkg/game.py` → `from pkg.game import Student` |

The planner already has the graph in hand, so it stores callees and externals in the plan; a
generation pass does not rebuild the graph.

## R7. The checks, in order

1. **Extract**: the first fenced Python block of the answer; if there is none, the whole answer when
   it parses. A fence that was opened and never closed still gives its text. Nothing usable →
   `no_code`.
2. **Parse**: `ast.parse` → else `syntax_error`.
3. **Imports**: every imported top-level module must be in the standard library
   (`sys.stdlib_module_names`), be `pytest`, or be a module of the project (derived from the
   project's file paths) → else `forbidden_import`.
4. **Safety**: no import of `socket`, `urllib`, `http`, `requests`, `ftplib`, `smtplib`,
   `subprocess`, `multiprocessing`; no call to `eval`, `exec`, `compile`, `__import__`,
   `os.system`, `os.popen`, `os.remove`, `shutil.rmtree`, `time.sleep`; no `open(...)` in a write
   mode unless its path comes from `tmp_path` → else `unsafe_code`.
5. **Weak test**: at least one test function; each has an `assert` or a `pytest.raises`; each
   calls the unit under test (for a method, a call of that method name; for `__init__`, a call of
   the class) → else `weak_test`.
6. **Naming**: test functions are renamed in order to `test_<unit>__unit_<n>`. This step cannot
   fail.

The first failing check decides the reason. Checks 2 to 5 read the syntax tree only; nothing is
imported or executed.

## R8. Where a "test file" lives in this slice

**Decision**: the test text and its path are stored on the record (`test_code`, `test_path`).
Nothing is written to a disk workspace: the workspace is built from GridFS by the sandbox slice,
which will write these texts at these paths.

Path rule: `tests/generated/test_<file>_<unit>__unit.py`, where `<file>` is the file path without
extension and `<unit>` the unit name, both with `/` and `.` replaced by `_`
(`tests/generated/test_game_Student_enroll__unit.py`).

## R9. Stopping early

| Cause | Detected by | Job ends as | `error.code` |
|-------|-------------|-------------|--------------|
| every model busy, quota used up, no API key, network down | `ModelUnavailable` from the facade | `completed_with_issues` | `model_unavailable` |
| the job spent its request limit | counter on the job ≥ `TESTGEN_MAX_REQUESTS_PER_JOB` | `completed_with_issues` | `request_limit_reached` |

In both cases the record being handled stays `pending`, records already `generated` are kept, and
the job's `error` field carries the code and a readable message. `error` is therefore no longer
only for failed jobs: it is set whenever a job did not do everything it was asked.

## R10. Patterns introduced now

- `TestKindStrategy` (abstract) with `UnitStrategy`: `build_context`, `prompt_sections`, and the
  shared `build_prompt` and naming rule. Edge and integration add a subclass each.
- `LanguageAdapter` interface with `PythonAdapter` and a one-line registry, wrapping the functions
  S1 already has plus the new validation and import rules.
- `LLMFacade` as described in R2.

## R11. Answers that the model did not finish (found in the acceptance run)

**Finding**: with an answer limit of 2000 tokens, two of nine real answers stopped in the middle of
the file (completion tokens 1998). Free models spend part of the limit on their own reasoning. The
fence was never closed, so the check found no code and reported `no_code`, which is misleading.
A stored cut-off answer would also have been reused by every later job, failing forever.

**Decision**: the limit is 4000 (`TESTGEN_LLM_MAX_TOKENS`). An answer with an odd number of
fence markers is treated as cut off: its text is still extracted, a parse failure is reported as
`syntax_error` with a detail saying the answer was cut off, and such an answer is never reused —
the unit is asked again. A cut-off answer that happens to stop between two complete tests still
passes, with the tests it has.
