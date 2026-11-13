# Feature Specification: S1 — Test Job and Plan (no LLM)

**Feature Branch**: `feature/core-testing`

**Created**: 2026-11-13

**Status**: Clarified — awaiting owner review

**Input**: User description: "Slice S1 of Feature 1 (Generate Trusted Tests): job + analysis gate + Graphify + plan, with no LLM. Register core_testing and its routes under /api/analysis/tests/, JWT on the test routes, create a test job on POST (latest version if omitted), analysis gate that reuses analysis and never waits inside a task, load and merge the graph with call edges for the selected Python files, planner with units and skip reasons, GET job and GET plan. Out of scope: LLM, sandbox, repair, edge, integration."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Ask for tests and see what will be tested (Priority: P1)

A signed-in user picks a project (optionally a version, some file paths and some test levels) and
asks for tests. The system answers at once with a job id. Shortly after, the user can read the
plan: every function and method found in the selected Python files, every file or unit that was
skipped with the reason, and how many pieces of work the job contains.

**Why this priority**: every later slice (generation, sandbox, repair) consumes this plan. Without
a correct unit inventory there is nothing to generate tests for.

**Independent Test**: upload a small Python project, start a job, read the plan, and compare the
listed units and skips with the source files by hand. No test is generated and no language model
is contacted.

**Acceptance Scenarios**:

1. **Given** an analysed project version with Python files, **When** the user starts a job with
   only the project id, **Then** the job is created on the latest version, covers all files of
   that version and all three levels, and the response carries the job id, status `pending`, the
   project id and the version number.
2. **Given** a job whose planning has finished, **When** the user reads the plan, **Then** each
   function and method of the selected Python files appears exactly once, either as a unit (with
   its id, file and kind) or in the skipped list with a reason.
3. **Given** a version that contains a non-Python file, **When** the plan is read, **Then** that
   file appears in the skipped list with reason `unsupported_language` and the Python files are
   still planned.
4. **Given** a job restricted to two file paths taken from the project tree, **When** the plan is
   read, **Then** only units from those two files appear.
5. **Given** any job in this slice, **When** it finishes planning, **Then** zero language-model
   calls were made.

---

### User Story 2 - Follow the job while it works (Priority: P2)

The user polls the job every couple of seconds and sees its status, its current stage, progress
counters and one line per file with that file's status.

**Why this priority**: the interface is driven by this single call. It must exist from the first
slice so the front end can be built against it, even though later stages do not run yet.

**Independent Test**: start a job on a version whose analysis is still running, poll, and watch
the stage move from waiting for analysis to planned without the request ever hanging.

**Acceptance Scenarios**:

1. **Given** a job whose files are all analysed, **When** the user polls, **Then** the answer
   shows the status, the stage, total and done counters, counters by record status, and a list of
   files each with a status.
2. **Given** a job where one selected file has no analysis yet and the others are analysed,
   **When** the user polls, **Then** the analysed files are already planned, the waiting file
   shows as pending, and once its analysis completes its units join the plan without any new
   request from the user.
3. **Given** a selected file whose analysis fails twice, **When** the user polls, **Then** that
   file's line shows status `skipped` with reason `analysis_failed`, and the job still completes
   for the other files.
4. **Given** a skipped file, **When** the user polls, **Then** that file's line shows status
   `skipped` and its reason.

---

### User Story 3 - Only the owner can use the job (Priority: P3)

Test routes require a signed-in user. A job belongs to the user who created it.

**Why this priority**: the existing service routes are open to anyone. Test jobs spend a limited
daily model budget and expose project structure, so the caller must be known.

**Independent Test**: call each route with no token, with a valid token of the owner, and with a
valid token of another user.

**Acceptance Scenarios**:

1. **Given** no token or an invalid token, **When** any test route is called, **Then** the answer
   is 401.
2. **Given** a job created by user A, **When** user B reads the job or its plan, **Then** the
   answer is 403.

---

### Edge Cases

- The request names a version that does not exist for the project → 400 `validation_error`.
- The request names a path that is not in that version → 400 `validation_error`, listing the
  unknown paths.
- The request names a level other than `unit`, `edge`, `integration` → 400 `validation_error`.
- The selection contains no Python file at all → 422 `no_python_files`, and no job is created.
- A selected file's analysis fails → it is requested once more; after a second failure the file
  is skipped with reason `analysis_failed` and the job continues with the other files.
- Every selected Python file fails analysis → the job ends as `failed`, with an error saying that
  no file could be analysed.
- A Python file has no function or method → skipped with reason `no_units`.
- A function whose body is empty, `pass`, `...` or abstract → skipped with reason
  `empty_or_abstract`.
- A function whose stored body was truncated by analysis → skipped with reason `body_truncated`.
- Two files define a class with the same name → both sets of units are listed, with distinct ids.
- A function calls a method of another class in the same project → the call is linked to that
  local unit, not reported as external.
- The plan is requested before planning has finished → 409 `plan_not_ready`.
- An unknown job id → 404.

## Requirements *(mandatory)*

### Functional Requirements

**Access**

- **FR-001**: Every test route MUST reject a request without a valid user token with 401.
- **FR-002**: A job MUST record the user who created it, and MUST be readable only by that user;
  another user gets 403.

**Starting a job**

- **FR-003**: Users MUST be able to start a job by sending a project id, and optionally a version
  number, a list of file paths and a list of levels. The project id is the identifier the project
  service already gives the project (a UUID string), not a number.
- **FR-004**: When the version number is omitted, the system MUST use the project's latest
  version.
- **FR-005**: When the path list is omitted or empty, the system MUST select all files of the
  version. Paths are the file paths shown by the project tree.
- **FR-006**: When the level list is omitted, the system MUST use all three levels: `unit`,
  `edge`, `integration`.
- **FR-007**: The system MUST answer a valid start request immediately with 202, a job id, status
  `pending`, the project id and the resolved version number, and do the work in the background.
- **FR-008**: The system MUST reject an invalid request with 400 `validation_error` and a message
  naming the invalid field.
- **FR-009**: The system MUST reject a selection with no Python file with 422 `no_python_files`.
- **FR-010**: The request MUST NOT carry file contents or a snapshot; the system binds the job to
  stored files and their analysis by project and version.

**Analysis gate**

- **FR-011**: The system MUST reuse the existing analysis of each selected file and MUST NOT
  re-analyse a file that is already analysed.
- **FR-012**: When a selected Python file has no analysis, the job MUST request that file's
  analysis itself. The start request is still accepted; it does not fail because analysis is
  missing.
- **FR-013**: The gate works per file. While one file waits for its analysis, the job MUST go on
  with the files that are already analysed, and MUST come back to the waiting file by itself when
  its analysis completes.
- **FR-014**: Waiting MUST be done by checking again later, never by one background task blocking
  on another.
- **FR-015**: When a file's analysis fails, the job MUST request it one more time. If it fails a
  second time, or is still not complete after a bounded waiting period, that file MUST be marked
  skipped with reason `analysis_failed`, the user MUST see that this file's analysis failed, and
  the rest of the job MUST continue.
- **FR-015a**: While at least one selected file is waiting for analysis and no other file is left
  to work on, the job's stage MUST read as waiting for analysis.

**Graph**

- **FR-016**: The system MUST build one project-level graph for the selected Python files from
  their per-file graphs, keeping the unified nodes / edges / meta shape.
- **FR-017**: Every unit MUST have an id that is unique across the project and stable between
  runs on the same version. The id has the form `path::Class.method` for a method (for example
  `src/main.py::Student.enroll`) and `path::function` for a function. The same id is used inside
  the system and in every answer shown to the user.
- **FR-018**: A call to a function or method defined in the selected files MUST be linked to that
  local unit, including calls made through a typed parameter, through `self`, and to a parent
  class.
- **FR-019**: The system MUST be able to answer, for any unit, which local units it calls
  directly.

**Plan**

- **FR-020**: The system MUST list every function and method of the selected Python files as a
  unit, with its id, its file and its kind (`function` or `method`).
- **FR-021**: A constructor (`__init__`) MUST be planned as a unit of its own. A private function
  or method (a name starting with `_` that is not a double-underscore special method) MUST NOT be
  planned as a unit: it is recorded as skipped with reason `private`, and stays available as a
  neighbour of the units that call it.
- **FR-022**: The system MUST record every skipped file or unit with one reason code from:
  `unsupported_language`, `analysis_failed`, `no_units`, `empty_or_abstract`, `body_truncated`,
  `private`.
- **FR-023**: A skip MUST NOT stop the job; the remaining files and units are still planned.
- **FR-024**: Users MUST be able to read the plan of their job: the units, the skipped list and
  the number of work items.
- **FR-025**: The work-item count MUST equal the number of planned units multiplied by the number
  of requested levels.

**Job status**

- **FR-026**: Users MUST be able to read their job's status, stage, progress counters (total,
  done, and a count per record status) and a per-file list with each file's status and, when
  skipped, its reason.
- **FR-027**: A job whose planning succeeded MUST end this slice with status `completed` and stage
  `planned`, with every work item still `pending`.
- **FR-028**: A job that cannot be planned MUST end as `failed` with an error the user can read.

**Boundaries of this slice**

- **FR-029**: The system MUST make zero language-model calls in this slice.
- **FR-030**: Existing analysis, explanation and conflict-detection behaviour MUST be unchanged.

### Key Entities *(include if feature involves data)*

- **Test job**: one request for tests, and the only new stored entity of this slice. Holds the
  owner, project id, version number, selected paths, requested levels, status, stage, progress
  counters, the per-file summary, an error if any, and the plan itself.
- **Plan** (kept inside the job): the planned units (id, file, kind, a fingerprint of the body),
  the skipped files and units with their reason codes, and the work-item count.
- **Project graph**: the units of the selected files and the import, inheritance and call links
  between them. Derived from stored analysis on demand; not sent by the user and not stored as a
  new entity in this slice.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For the sample project (a university model with 6 classes), the plan accounts for
  100% of its functions and methods, each exactly once, as a unit or as a skip with a reason:
  14 units and no skips.
- **SC-002**: In the sample project, the call from the student's enrol method to the course's
  add-student method is linked to the local unit; no local call is reported as external.
- **SC-003**: A start request is answered in under 2 seconds, whatever the project size.
- **SC-004**: The plan of the sample project is readable within 10 seconds of the start request
  when its analysis already exists.
- **SC-005**: Zero language-model calls are recorded for any job in this slice.
- **SC-006**: 100% of calls to test routes without a valid token are refused, and a user can
  never read another user's job.
- **SC-007**: All automated tests that existed before this slice still pass.

## Assumptions

- **Routes**: the three routes of this slice are `POST /api/analysis/tests/jobs/`,
  `GET /api/analysis/tests/jobs/{job_id}/` and `GET /api/analysis/tests/jobs/{job_id}/plan/`,
  with the request and response fields of the agreed API document. The field names are `paths`
  and `levels`.
- **Out of scope for this slice**: any language-model call, prompt or context building, test file
  writing, sandbox, coverage, download, repair, status classes beyond `pending` and `skipped`,
  edge hints, integration groups, cancel, records listing.
- **Graph additions in this slice** are the minimum that unlock planning: local call resolution,
  project-unique ids, merging file graphs, and direct-callee lookup. Builtins, confidence tiers,
  `io_kind`, grouped queries and caching come with the slices that need them.
- **Project ownership**: in this slice the system trusts that a signed-in user may use the project
  id they send; it only enforces that a job is read by its creator. Checking project membership
  against the project service comes before the multi-user demo.
- **Upload path**: files reach the service through the existing upload flow, which already
  triggers analysis of each file. Requesting a missing analysis reuses the existing per-file
  analysis; it does not change how analysis works.
- **Difference from the API document**: the document lists a 409 `analysis_missing` error on
  start. By the owner's decision of 2026-11-13 the job requests the missing analysis instead, so
  that error is not returned.
- **Levels in this slice** only affect the work-item count; no level-specific planning (edge
  hints, integration groups) is done yet, so the count will change in slices S5 and S6.
- **Job status values** follow the agreed document: `pending`, `running`, `completed`,
  `completed_with_issues`, `failed`, `cancelled`. File status values: `pending`, `ready`,
  `partial`, `failed`, `skipped`.
- **Nested functions and lambdas** are not units.
- **Where it is built**: inside the existing analysis service, as a module of its own beside
  the other two features. It is not a new service (owner's decision, 2026-11-13).
- **Storage kept minimal**: one new stored entity (the job, with its plan inside). Separate unit
  and record stores arrive with the slice that first needs them (S2).
- **Access key**: the service checks the user token with the signing key of the project service.
  The owner approved sharing that key with this service on 2026-11-13.
- **Deliverables besides code**: an Arabic report with the test results, the existing stored
  data this slice reads, how to call the three routes, and the list of items left for S2 onward.
