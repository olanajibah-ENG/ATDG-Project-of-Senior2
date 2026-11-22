# Feature Specification: S3 — Isolated Run, Acceptance Gate, Coverage and Bundle

**Feature Branch**: `feature/core-testing`

**Created**: 2026-11-20

**Status**: Reviewed 2026-11-20 — six points made explicit (FR-003, FR-018, FR-022, FR-023, FR-026, time limits, concurrency)

**Input**: User description: "Slice S3 of Feature 1 (Generate Trusted Tests): sandbox run + acceptance gate + ready + coverage + ZIP bundle. After generation, every `generated` record is run with pytest against the code of the same project version inside a fresh, isolated container per record (network off, read-only source, CPU/memory/process/time limits, non-root, no capabilities). Results are read from junit XML; a record becomes `ready` only through the acceptance gate when all its tests pass, with evidence (run id, version number, body hash); otherwise `test_failed` (assertion, collection_error, no_tests, timeout) or `environment_error` (missing_dependency, sandbox_unavailable). After all records, one final clean run of all `ready` tests together gives the official coverage (line + branch) and a per-file report; each record also keeps its own coverage contribution. New routes: GET coverage and GET bundle (ZIP with MANIFEST, merged junit of ready tests, coverage report, plan, records summary, pytest.ini, tests/generated/unit). A dedicated sandbox worker on its own queue is the only component that talks to Docker; it holds no secrets. No dependency installation in this slice (project code needing a third-party library yields environment_error). Out of scope: repair (S4), edge/integration, dependency install, quarantine, frontend."

## Clarifications

### Session 2026-11-20 (review before planning)

- Q: Does the run read the right file for every path after incremental uploads, without old or duplicate files? → A: Yes. It reads the same file list the plan uses: one file per path, the newest stored one when a path has several, deleted paths left out, never a file of a later version (FR-003).
- Q: Which HTTP status do the coverage and bundle routes give before the job is finished? → A: `409`, with error codes `coverage_not_ready` and `bundle_not_ready`, in the error shape all test routes use (FR-022, FR-023).
- Q: What is the maximum time of the final run? → A: `60 + 15 × ready records` seconds, capped at 300 seconds (Assumptions).
- Q: How many runs may happen at the same time? → A: Runs of one job are sequential; at most 2 runs at once across all jobs (Assumptions).
- Q: Where do tests that are not `ready` go in the package? → A: Nowhere: they appear only in `records_summary.json` with status and reason; `tests/quarantine/` arrives with S4 (FR-026).
- Q: How is an uncovered line explained by the plan represented in the coverage report? → A: In each file's `missing_annotations`, an object `{"<line>": "<unit> — skipped: <reason code>"}`; files not measured at all are listed in `not_measured` as `{"file", "reason"}` (FR-018).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Every generated test is really run, and only passing ones become `ready` (Priority: P1)

After generation, the job goes on by itself. Each test that was written and checked in S2 is run
against the real code of the same project version, in a fresh isolated environment of its own, with
no network. If every test in the file passes, the record becomes `ready` and keeps the evidence of
that run. If not, the record keeps the real reason it did not pass. The user polls the same job and
sees records move from `generated` to `ready` or to a failure status.

**Why this priority**: this is the product promise. Until a test has been run against the real
code, it is only a candidate. A `ready` label without a real run would be meaningless (Principle II).

**Independent Test**: start a job on a small sample project, wait until it finishes, and check that
each `generated` record ended as `ready` (with run evidence) or as `test_failed` /
`environment_error` (with a reason), and that a test written to fail on purpose did not become
`ready`.

**Acceptance Scenarios**:

1. **Given** a job whose generation produced 5 `generated` unit records, **When** the run stage
   finishes, **Then** each of the 5 records is `ready`, `test_failed` or `environment_error`, and
   none is left `generated`.
2. **Given** a record whose tests all pass against the code, **When** its run finishes, **Then** it
   is `ready` and carries evidence: the run identifier, the project version number, the body hash of
   the unit, the fingerprint of the test file, how many tests ran and passed, and how long it took.
3. **Given** a record with one failing assertion (for example a test that expects `"2"` where the
   code holds `2`), **When** its run finishes, **Then** it is `test_failed` with reason `assertion`
   and the failure message of the first failing test, and it is not `ready`.
4. **Given** records that were `generation_failed` or are still `pending` (edge, integration),
   **When** the run stage runs, **Then** they are not run and their status does not change.
5. **Given** a record that becomes `ready`, **When** anything other than the acceptance gate tries to
   set `ready`, **Then** it cannot: `ready` is written in one place only, and always with evidence.

---

### User Story 2 - The run is isolated and bounded (Priority: P1)

A generated test is untrusted code. It runs where it cannot reach the network, cannot change the
project's code, cannot run forever, cannot use unbounded memory or processes, and cannot gain
privileges. The component that starts these environments holds no secrets and is not reachable by
the generated code.

**Why this priority**: it is both a safety requirement and part of what "trusted" means: a test that
silently calls a real service must fail, not pass.

**Independent Test**: run three deliberately bad tests — one that opens a network connection, one
that loops forever, one that writes into the project's source — and check that each ends
`test_failed` with the matching reason and that the source on disk is unchanged.

**Acceptance Scenarios**:

1. **Given** a test that opens a network connection, **When** it runs, **Then** the connection fails
   inside the run and the record does not become `ready`.
2. **Given** a test that never ends, **When** the time limit (60 seconds) is reached, **Then** the
   run is stopped and the record is `test_failed` with reason `timeout`.
3. **Given** a test that tries to modify a project file, **When** it runs, **Then** the write fails,
   the stored project file is unchanged, and the record does not become `ready`.
4. **Given** any run, **When** it starts, **Then** it uses a fresh environment with no network,
   read-only project code, limits on CPU (1), memory (512 MB, no swap), process count (128) and time
   (60 s), a non-root user and no extra privileges; nothing from one run is visible to the next.
5. **Given** the run environment, **When** it is inspected, **Then** it holds no API keys, tokens or
   other secrets.

---

### User Story 3 - The real reason for every failure (Priority: P2)

When a record does not become `ready`, the user (and later the repair step, S4) needs the precise,
machine-read reason: which test failed and with which message, or why nothing could run.

**Why this priority**: S4 repairs a test by sending the real failure back to the model. A guessed or
free-text reason would make that impossible and would hide whether the test or the environment is
at fault.

**Independent Test**: run one record of each failure kind and check the status, the reason code and
the per-test outcomes stored on the record.

**Acceptance Scenarios**:

1. **Given** a run, **When** it finishes, **Then** the outcome of every test function in the file
   (passed, failed, error, skipped) and the message of each failure are read from the structured
   result file, not from the printed output, and stored on the record.
2. **Given** a test that imports a name that does not exist in the project, **When** it runs,
   **Then** the record is `test_failed` with reason `collection_error`.
3. **Given** project code that imports a third-party library not available in the run environment,
   **When** the test runs, **Then** the record is `environment_error` with reason
   `missing_dependency` and the name of the missing module.
4. **Given** a test file in which no test is collected, **When** it runs, **Then** the record is
   `test_failed` with reason `no_tests`.
5. **Given** the run environment cannot be started at all, **When** a record is due to run, **Then**
   it is `environment_error` with reason `sandbox_unavailable`, and the job still finishes with the
   other records.
6. **Given** a test that is skipped when run, **When** its record is judged, **Then** the record does
   not become `ready` (a skipped test proves nothing).

---

### User Story 4 - Coverage from the final all-pass run (Priority: P2)

When all records have run, every `ready` test of the job is run once more, all together, in one
clean environment. That run gives the official coverage of the job: lines and branches, per file
and in total, with the lines left uncovered and, where known, why. Each `ready` record also keeps
what its own run covered.

**Why this priority**: the user wants to know how much of the code the trusted tests exercise.
Principle II requires that coverage come from the final all-pass run and from no other.

**Independent Test**: on a job with several `ready` records, read the coverage of the job and check
that it comes from one final run that contains only `ready` tests, and that its per-file numbers
match that run.

**Acceptance Scenarios**:

1. **Given** a job whose run stage left 4 `ready` records, **When** the final run finishes, **Then**
   the job's coverage reports line and branch percentages per file and in total, and the uncovered
   lines of each file.
2. **Given** an uncovered part of the code that the plan left out on purpose (a private method,
   for example), **When** the coverage report is read, **Then** that uncovered line is annotated with
   the plan's reason.
3. **Given** the final run, **When** a test that passed alone fails when run with the others,
   **Then** that record loses `ready` and becomes `test_failed` with reason `fails_with_others`, the
   final run is repeated without it, and the coverage comes from the repeated all-pass run.
4. **Given** a job with no `ready` record, **When** its coverage is read, **Then** it says there is
   no coverage and why, and no number is invented.
5. **Given** a `ready` record, **When** it is read, **Then** it shows the lines and branches covered
   by its own run.

---

### User Story 5 - Download the trusted tests as one package (Priority: P3)

When the job is finished, the user downloads one archive that holds the `ready` tests in their
folders, a merged result file of those tests, the coverage report, the plan, a summary of every
record with its final status and reason, a small runner configuration so the package runs with one
command, and a manifest with a fingerprint of every file.

**Why this priority**: it is the deliverable the user takes back into their own project. It depends
on Stories 1 and 4.

**Independent Test**: download the package of a finished job, unpack it next to the project's code,
run the test command once, and check that every test in it passes and that the manifest matches the
files.

**Acceptance Scenarios**:

1. **Given** a finished job, **When** its package is downloaded, **Then** it contains only `ready`
   tests, the merged results of those tests (no failures), the coverage report, the plan, the
   records summary, the runner configuration and the manifest.
2. **Given** a record that is `test_failed` or `environment_error`, **When** the package is built,
   **Then** its test is not in the package and the records summary gives its status and reason.
3. **Given** a job that is still running, **When** its package is requested, **Then** the answer
   says the package is not ready yet and nothing is built.
4. **Given** a job of another user, **When** its package or coverage is requested, **Then** access is
   refused, as for the other routes of the job.

---

### Edge Cases

- A job in which generation produced no `generated` record: the run stage is skipped, coverage says
  there is none, and the package holds only the plan, the summary and the manifest.
- Two jobs run at the same time: their runs never share an environment or a working folder.
- The project version has a file that is not Python (a JSON file, for example): it is part of the
  code made available to the tests but is not measured by coverage.
- A test prints a very large amount of output: the stored output is cut to a bounded size; the
  outcome still comes from the structured result file.
- A test leaves files in the temporary area: the area is bounded (64 MB) and is discarded after the
  run.
- The structured result file is missing or cannot be read after a run: the record is
  `environment_error` with reason `no_result_file`, never `ready`.
- The job's version has changed in the meantime (a newer version was uploaded): the run uses the
  version the job was created for, never the newer one.
- A record's unit was deleted or changed in a later version: its `ready` status and evidence still
  refer to the version, run and body hash they were proven on.
- The worker that runs tests is down: the job stops moving; the existing stale-job rule reports it
  as failed instead of leaving it waiting forever.

## Requirements *(mandatory)*

### Functional Requirements

**Run stage**

- **FR-001**: After generation finishes, the job MUST move on by itself to a run stage, visible in
  the job's stage, without a new request from the user.
- **FR-002**: The run stage MUST run every record whose status is `generated`, and only those.
- **FR-003**: Each record MUST be run against the code of the exact project version the job was
  created for, read from the same file list the plan used: exactly one file per path — when an
  incremental upload left more than one stored file for a path, the newest one (highest version
  number) is used — and every path marked deleted in that version is left out. A file of a later
  version is never used, even if it was uploaded while the job runs.
- **FR-004**: Each record MUST run in its own fresh environment; nothing written by one run may be
  visible to another run or to another job.
- **FR-005**: Every run environment MUST have: no network; the project code read-only; a writable
  area only for temporary files (bounded, 64 MB) and for the results; limits of 1 CPU, 512 MB memory
  with no swap, 128 processes and 60 seconds; a non-root user; no added privileges.
- **FR-006**: The run environment MUST NOT hold any secret (API keys, tokens, passwords).
- **FR-007**: Only one dedicated component MAY start run environments. It MUST hold no secrets, MUST
  NOT call the language model, and MUST start only the approved run image with the options of
  FR-005.
- **FR-008**: Runs MUST NOT install any library in this slice. The environment holds the language
  runtime and the test and coverage tools only.

**Results and the acceptance gate**

- **FR-009**: The outcome of a run MUST be read from the structured result file the test tool
  writes, giving the outcome and message of every test function. Printed output MAY be kept for the
  user, cut to a bounded size, but MUST NOT decide the outcome.
- **FR-010**: A record MUST become `ready` only through the acceptance gate, and only when at least
  one test was collected and every collected test passed (none failed, errored or was skipped).
- **FR-011**: When the acceptance gate sets `ready`, it MUST store the evidence with it: run
  identifier, project version number, the unit's body hash, the fingerprint of the test file, tests
  run and passed, and duration. No other code path may set `ready`.
- **FR-012**: A record that does not pass MUST receive exactly one final status and reason:

  | Situation | Status | Reason |
  |---|---|---|
  | A test failed an assertion | `test_failed` | `assertion` |
  | The test file could not be collected (bad import of a project name, syntax at run time) | `test_failed` | `collection_error` |
  | No test was collected | `test_failed` | `no_tests` |
  | A test was skipped | `test_failed` | `skipped_test` |
  | The time limit was reached | `test_failed` | `timeout` |
  | Passed alone, failed in the final run with the others | `test_failed` | `fails_with_others` |
  | The project code needs a library that is not available | `environment_error` | `missing_dependency` |
  | The run environment could not be started | `environment_error` | `sandbox_unavailable` |
  | The run ended without a readable result file | `environment_error` | `no_result_file` |

- **FR-013**: For a failed record, the record MUST store the outcome of each test function and the
  message of each failure, so that the repair step (S4) can use the real failure.
- **FR-014**: A failure of one record MUST NOT stop the others; the job MUST finish every record.

**Coverage**

- **FR-015**: After every record has run, all `ready` tests of the job MUST be run once more,
  together, in one clean environment with the same isolation, measuring line and branch coverage.
- **FR-016**: If a test fails in that final run, its record MUST become `test_failed` with reason
  `fails_with_others`, and the final run MUST be repeated without it, until a run passes completely
  or no `ready` test is left.
- **FR-017**: The job's official coverage MUST come from the final run in which every test passed,
  and from no other run.
- **FR-018**: The coverage report MUST give, per measured file and in total: statements, covered
  statements, line percentage, branches, covered branches, branch percentage, and the uncovered
  lines (`missing_lines`, a list of line numbers). An uncovered line that belongs to a unit the plan
  skipped MUST carry the plan's reason in the file's `missing_annotations`: an object whose keys are
  line numbers (as text) and whose values are one line of text naming the unit and the plan's reason
  code, e.g. `{"81": "models.Order._audit_log — skipped: private"}`. A file of the version that is not
  measured at all (not Python) MUST be listed in the report's `not_measured`, a list of
  `{"file", "reason"}` objects, e.g. `{"file": "config.json", "reason": "unsupported_language"}`.
- **FR-019**: Each `ready` record MUST also keep the lines and branches covered by its own run
  (its contribution), labelled as such and never presented as the job's coverage.

**Status and routes**

- **FR-020**: The job's status MUST show the run stage while it runs, and the counts of records per
  status (including `ready`, `test_failed`, `environment_error`) as they change. At the end the job
  is `completed` when every run record is `ready`, otherwise `completed_with_issues`.
- **FR-021**: A record's detail MUST show whether it was run, its run result (per-test outcomes,
  failure messages, duration, bounded output), its evidence when `ready`, and its coverage
  contribution.
- **FR-022**: A new route MUST return the job's coverage report. Before the job has finished, it
  answers **409** with error code `coverage_not_ready`, in the error shape every test route already
  uses: `{"error": {"code", "message", "details"}}`.
- **FR-023**: A new route MUST return the job's package as one archive. Before the job has finished,
  it answers **409** with error code `bundle_not_ready`, in the same error shape. ("Finished" means
  the job's status is `completed`, `completed_with_issues` or `failed`.)
- **FR-024**: The new routes MUST apply the same access rules as the existing job routes: a signed-in
  user, and a job read only by its creator.

**Package**

- **FR-025**: The package MUST contain: a manifest (job, project, version, and a fingerprint of every
  file), the merged results of the `ready` tests, the coverage report, the plan, a summary of every
  record with its final status and reason, a runner configuration that makes the package run with
  one command next to the project's code, and the `ready` test files under `tests/generated/unit/`.
- **FR-026**: The package MUST NOT contain the test of any record that is not `ready` — a
  `test_failed` or `environment_error` test is in no folder of the package and appears only in
  `records_summary.json`, with its status and reason. There is no `tests/quarantine/` folder in this
  slice (it arrives with repair, S4). The package MUST NOT contain the project's source code or any
  secret.

**Boundaries**

- **FR-027**: The automated tests of this slice MUST NOT start real run environments and MUST NOT
  call the language model; a stand-in runner is used.
- **FR-028**: The slice MUST keep the feature's import boundary: it reads stored analysis and files,
  and imports nothing from other features (conflict detection, the explanation engine).

### Key Entities *(include if feature involves data)*

- **Run**: one execution of one record's test file (or of the final all-`ready` set): identifier,
  job, record (none for the final run), version number, start and end time, exit outcome, per-test
  outcomes, bounded printed output, coverage data of that run.
- **Run result (on a record)**: whether the record was run, its per-test outcomes and failure
  messages, the final status and reason.
- **Evidence (on a `ready` record)**: run identifier, version number, body hash, test file
  fingerprint, tests run and passed, duration. Written only by the acceptance gate.
- **Coverage report (on a job)**: the final all-pass run it came from, per-file and total line and
  branch figures, uncovered lines with plan reasons where known, files not measured and why.
- **Coverage contribution (on a `ready` record)**: lines and branches covered by that record's own
  run.
- **Package**: an archive built from the job's `ready` tests, results, coverage, plan, records
  summary, runner configuration and manifest.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On the sample project, 100% of the records that end `ready` have a stored run in which
  all their tests passed on the job's version, and 0 records are `ready` without one.
- **SC-002**: A test written to fail on purpose never becomes `ready` (0 out of 10 attempts).
- **SC-003**: A test that tries to reach the network, one that never ends and one that writes into
  the project's code all end `test_failed`, and the stored project code is byte-for-byte unchanged.
- **SC-004**: Every record that does not become `ready` has a reason from the agreed list; 0 records
  end with an unknown or empty reason.
- **SC-005**: The job's coverage figures equal those of one final run in which every test passed, and
  that run contains exactly the job's `ready` tests.
- **SC-006**: A downloaded package, unpacked next to the version's code, runs with one command and
  all its tests pass on the first try.
- **SC-007**: For a job of 5 unit records, the run stage (all records plus the final run) finishes in
  under 3 minutes on the development machine.
- **SC-008**: Every test of the service that passed before this slice still passes after it
  (conflict detection and its evaluation give the same results).

## Assumptions

- **Isolation**: each run uses a fresh, short-lived container started from one fixed run image, with
  the options of FR-005. The component that starts containers is a dedicated worker on its own queue
  with access to the container engine and no secrets. In the local Docker Compose setup this access
  is acceptable; a production deployment would use a separate runner host.
- **Run image**: the language runtime plus pytest and pytest-cov, pinned, with a non-root user. It is
  built from a file kept in the repository.
- **One run per record, then one final run**: a record is judged on its own run; the final run of
  all `ready` tests both measures coverage and checks that the tests also pass together. There is no
  separate repetition for flakiness in this slice.
- **No dependency installation** (as agreed for S2): tests may import the standard library, pytest
  and the project. Project code that needs a third-party library yields `environment_error /
  missing_dependency`. Installing a project's declared dependencies is a later slice.
- **Levels**: only `unit` records exist as `generated` after S2, so only they are run. `edge` and
  `integration` stay `pending`.
- **Repair**: a `test_failed` record stays `test_failed` in this slice. Sending the failure back to
  the model, at most 3 times, is S4, as is the quarantine folder of the package.
- **Coverage scope**: only Python files of the version are measured; other files are listed as not
  measured with reason `unsupported_language`.
- **Time limits**: 60 seconds per record run. The final run's limit is `60 + 15 × (number of ready
  records)` seconds, capped at **300 seconds**. The worker itself waits at most the limit + 15 seconds
  before it stops the container.
- **Concurrency**: runs of one job are sequential (one record per pass). At most **2** runs happen at
  the same time across all jobs (the run worker handles two tasks at once).
- **Stale jobs**: the existing rule that fails a job which stops moving also covers the run stage.
- **The design reference**: the run options, statuses, coverage report and package layout follow the
  owner's design document "AutoTest_Feature1_Generate_Trusted_Tests_AR" (S3 section), adapted to this
  service's versions (no code is sent in the job request).
