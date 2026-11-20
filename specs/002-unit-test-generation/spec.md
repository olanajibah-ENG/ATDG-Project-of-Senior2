# Feature Specification: S2 — Unit Test Generation (not run yet)

**Feature Branch**: `feature/core-testing`

**Created**: 2026-11-13

**Status**: Clarified — awaiting owner review

**Input**: User description: "Slice S2 of Feature 1 (Generate Trusted Tests): unit context + prompt + validate + write. For every planned unit, build a small context, ask the language model for a pytest unit test, check the answer without running it, and write the test file. Acceptance: the generated file parses; nothing is `ready` yet. Out of scope: sandbox, coverage, download, repair, edge, integration."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A unit test is written for every planned unit (Priority: P1)

After the plan of a job is built, the system goes on by itself. For each planned unit it asks the
language model for a pytest test of that one function or method, checks the answer without running
it, and keeps the test file. The user polls the same job and sees the work advance unit by unit.

**Why this priority**: this is the first slice that produces tests. Everything later (running them,
repairing them, edge and integration levels) starts from a generated, well-formed test file.

**Independent Test**: start a job on the sample project with level `unit`, wait until the job
finishes, and check that every planned unit has a test file that parses as Python, is named by the
agreed rule, imports the unit from its real location and calls it.

**Acceptance Scenarios**:

1. **Given** a job whose plan has 14 units and level `unit` requested, **When** generation
   finishes, **Then** 14 unit records exist, each either `generated` with a checked test file or
   `generation_failed` with a reason.
2. **Given** a generated test file, **When** it is inspected, **Then** it parses as Python, every
   test function in it is named `test_<unit>__unit_<n>`, it imports the unit under test from the
   project, and each test function calls the unit and makes at least one check.
3. **Given** any record in this slice, **When** its status is read, **Then** it is never `ready`:
   no test has been run yet.
4. **Given** a job that also requested `edge` and `integration`, **When** generation finishes,
   **Then** only the `unit` level was generated and the other levels' work items are still
   `pending`.
5. **Given** the model's answer for one unit is unusable, **When** the job continues, **Then**
   that unit is marked `generation_failed` and the remaining units are still generated.

---

### User Story 2 - The model sees only what it needs, and every call is recorded (Priority: P2)

For each unit the model receives a small, fixed-shape context: the unit itself, the class it
belongs to, the signatures of the local units it calls directly, and the external things it uses.
It never receives the whole project. Every call to the model is recorded with its purpose, the
model that answered and the token counts.

**Why this priority**: the free model tier allows about 50 requests a day, measurements must be
repeatable, and the project must be able to show what was sent to the model and what it cost.

**Independent Test**: generate tests for one file of a two-file project and check that the text
sent to the model contains the unit and its direct callees' signatures, does not contain the body
of any other unit, and that one attempt record exists per call with model and token counts.

**Acceptance Scenarios**:

1. **Given** a unit that calls another local unit, **When** its context is built, **Then** the
   context holds the unit's own body and the callee's signature, and not the callee's body.
2. **Given** a method, **When** its context is built, **Then** the context holds the class name,
   the constructor's signature and the parent classes.
3. **Given** any call to the model, **When** it returns or fails, **Then** an attempt record is
   stored with the unit, the level, the purpose (`generate`), the model name, the prompt and
   completion token counts, the prompt version, and the result of the checks.
4. **Given** the same unit, the same code version and the same prompt version, **When** a second
   job asks for the same test, **Then** the stored answer is reused and no new model request is
   spent.

---

### User Story 3 - See what was generated (Priority: P3)

The user can list the records of a job, filter them by status, file or level, and see for each one
its unit, level, status, reason and the path of its test file.

**Why this priority**: without it the only evidence of this slice is in the database. The front
end also needs this listing for its per-file view.

**Independent Test**: after a job finishes, list its records, filter by `level=unit` and by a file
path, and check counts against the plan.

**Acceptance Scenarios**:

1. **Given** a finished job, **When** the user lists its records, **Then** each item shows an id,
   the file, the unit id, the level, the status, the reason code and the test path, and the total
   is given.
2. **Given** filters on status, path or level, **When** the user lists records, **Then** only
   matching records are returned.
3. **Given** a `generated` record, **When** the user opens it, **Then** the test code is shown
   together with a clear statement that it has not been run yet.
4. **Given** another user's job, **When** its records are requested, **Then** the answer is 403.

---

### Edge Cases

- The model returns text with no code in it → `generation_failed`, reason `no_code`.
- The answer does not parse as Python → `generation_failed`, reason `syntax_error`.
- The test imports something that is neither the standard library, pytest, the project itself nor
  a declared dependency → `generation_failed`, reason `forbidden_import`.
- The test uses the network, starts a process, evaluates code, sleeps or writes outside a
  temporary directory → `generation_failed`, reason `unsafe_code`.
- A test function has no check, or never calls the unit under test → `generation_failed`, reason
  `weak_test`.
- Test functions are named differently from the rule → they are renamed to the rule; this is not a
  failure.
- The model is unreachable, every model refuses, or the daily request limit is used up → the job
  stops generating. Tests already generated are kept, the units not yet handled stay `pending`,
  and the job ends as `completed_with_issues` with the reason `model_unavailable`. The unit that
  was being handled is not marked as failed, because nothing is wrong with it.
- The job reaches its own request limit → the same: generation stops, the rest stays `pending`,
  and the job ends as `completed_with_issues` with the reason `request_limit_reached`.
- A new job is started later on the same code → answers already stored are reused without a new
  request, so the new job only spends requests on the units that were left `pending`.
- The file has no extension in the project (the sample was uploaded as `game`) → the unit cannot be
  imported by a test; the import path is built as if the file were named with `.py`, and the fact
  is recorded for the slice that builds the workspace.
- A job is started again for the same project version → new records are created for the new job;
  earlier jobs are not changed.
- The worker stops in the middle of generation → the job is reported as failed by the existing
  stale-job rule, and units already generated keep their records.

## Requirements *(mandatory)*

### Functional Requirements

**Flow**

- **FR-001**: After a job's plan is complete, the system MUST start generation for that job by
  itself, without a new request from the user.
- **FR-002**: In this slice the system MUST generate tests for the `unit` level only. Work items
  of the `edge` and `integration` levels MUST stay `pending`.
- **FR-003**: Generation MUST handle one unit at a time, so that the job's progress is visible
  after each unit, and so that one unit's failure cannot stop the others.
- **FR-004**: The job MUST reach a final status: `completed` when every `unit` work item is
  `generated`; `completed_with_issues` when at least one is `generation_failed`, or when generation
  stopped early and left `unit` work items `pending`. When it stopped early the job MUST carry
  the reason: `model_unavailable` or `request_limit_reached`.
- **FR-004a**: When the model cannot be reached or refuses for lack of quota, the system MUST stop
  generating for that job at once instead of trying the remaining units, MUST keep what was
  already generated, and MUST NOT mark the interrupted unit as failed.

**Context**

- **FR-005**: For each unit the system MUST build a context holding: the unit's id, how to import
  it, its signature, parameters with types, return type, decorators, docstring and body; for a
  method, the class name, the constructor's signature, and the parent classes; the signatures of
  the local units it calls directly; and the external names it uses.
- **FR-006**: The context MUST NOT contain the body of any unit other than the unit under test,
  and MUST NOT contain whole files.
- **FR-007**: The language model MUST receive nothing about the project beyond this context and
  the fixed instructions.

**Model use**

- **FR-008**: Every request to the model MUST go through one component that records, per call:
  the job, the unit, the level, the purpose, the model that answered, prompt and completion token
  counts, the prompt version, the time taken, and the outcome.
- **FR-009**: The system MUST make at most one model request per unit in this slice. There is no
  repair.
- **FR-010**: Requests MUST be deterministic as far as the model allows (no randomness asked for).
- **FR-011**: An answer already obtained for the same unit body, the same context and the same
  prompt version MUST be reused instead of spending a new request.
- **FR-012**: One job MUST NOT spend more model requests than a limit set in the service's
  configuration (default 20). Reused stored answers do not count. When the limit is reached the
  job stops generating as described in FR-004.

**Checks (nothing is run)**

- **FR-013**: The system MUST extract the test code from the model's answer and reject an answer
  with no code.
- **FR-014**: The test code MUST parse as Python.
- **FR-015**: The test code MUST import only from: the standard library, pytest, the project
  itself, and the dependencies the project declares.
- **FR-016**: The test code MUST NOT use the network, start processes, evaluate code from text,
  sleep, or write outside a temporary directory.
- **FR-017**: Every test function MUST contain at least one check and MUST call the unit under
  test.
- **FR-018**: Test functions MUST be named `test_<unit>__unit_<n>`, where `<unit>` is the unit's
  name with dots replaced by underscores. The system MUST rename them to this rule itself.
- **FR-019**: A test that fails any of FR-013 to FR-017 MUST be marked `generation_failed` with
  one reason code from: `no_code`, `syntax_error`, `forbidden_import`, `unsafe_code`, `weak_test`.

**Result**

- **FR-020**: A test that passes the checks MUST be kept as a test file whose path is
  `tests/generated/test_<file>_<unit>__unit.py`, together with the body fingerprint of the unit it
  was written for.
- **FR-021**: A test that was generated and passed the checks, but has not been run, MUST be shown
  with a status of its own, `generated`. The job's progress counters MUST count `generated`
  records separately from `pending` and from `ready`.
- **FR-021a**: Users MUST be able to read the code of a `generated` test of their own job. The
  answer MUST state plainly that the test has not been run.
- **FR-022**: No record may become `ready` in this slice.
- **FR-023**: The job's progress counters MUST be updated after each unit.

**Records**

- **FR-024**: Users MUST be able to list the records of their job, with id, file, unit id, level,
  status, reason code and test path, and the total count. The listing does not carry test code;
  the code is read one record at a time (FR-021a).
- **FR-025**: The listing MUST accept filters on status, file path and level.
- **FR-026**: The listing MUST follow the same access rules as the other test routes: a valid user
  token, and only the job's creator.

**Boundaries**

- **FR-027**: The planning behaviour of slice S1 MUST be unchanged, and its tests MUST still pass.
- **FR-028**: Automated tests of this slice MUST NOT make a real model request.

### Key Entities *(include if feature involves data)*

- **Test unit**: one planned unit of a job, with its id, file, kind and body fingerprint. It stays
  inside the job's plan, as in S1; each record carries the unit id and file it needs.
- **Test record**: one work item, a unit at a level. Holds its status, reason code, test path, the
  test code that passed the checks, the model and the prompt version that produced it.
- **Test attempt**: one request to the language model. Holds the record it served, the purpose,
  the model, token counts, time taken, the prompt version and the outcome of the checks.
- **Context**: what the model is shown for one unit. Built on demand; its fingerprint is stored
  with the attempt.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For the sample project, 100% of planned units end as `generated` with a checked test
  file, as `generation_failed` with a reason, or as `pending` under a job that names why it
  stopped. None is left without an explanation.
- **SC-002**: 100% of kept test files parse as Python and follow the naming rule.
- **SC-003**: Zero records are `ready` at the end of any job of this slice.
- **SC-004**: At most one model request is spent per unit, and a second job on unchanged code
  spends zero new requests.
- **SC-005**: 100% of model requests have an attempt record with model name and token counts.
- **SC-006**: No context sent to the model contains the body of a unit other than the unit under
  test.
- **SC-007**: Every automated test that existed before this slice still passes, and the automated
  tests of this slice run with the model blocked.

## Assumptions

- **Out of scope for this slice**: running any test, the sandbox, installing dependencies,
  coverage, the `ready` status, download, repair of a failed test, the `edge` and `integration`
  levels, cancelling a job.
- **Model**: the existing language-model client of the service is used, extended so that a call
  also returns the model name and token counts. No new provider is added.
- **Prompt version**: the instructions sent to the model carry a version label; changing the
  instructions changes the label, so stored answers from an older label are not reused.
- **Dependencies of the project**: dependency manifests are not kept at upload yet (that arrives
  with the sandbox slice), so in this slice "declared dependencies" is an empty list and a test may
  import only the standard library, pytest and the project itself.
- **Private functions** are not tested on their own (decided in S1); they appear in a context only
  as callees.
- **Stale jobs**: the existing rule that fails a job which stops moving also covers generation.
- **Reading the generated code**: a `generated` test can be read, clearly marked as not run. It is
  not downloadable as part of a trusted set; download stays reserved for `ready` tests.
- **New status in the API**: `generated` is added to the record statuses and to the progress
  counters. The agreed API document does not list it (owner's decision, 2026-11-13).
- **Daily limit of the model provider** (about 50 requests on the free tier) is not tracked by the
  service; it is noticed when the provider refuses, and handled as `model_unavailable`.
