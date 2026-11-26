# Feature Specification: S4 — Repair Loop, Failure Classes, Stable Results and Environment Preflight

**Feature Branch**: `004-repair-failure-classes`

**Created**: 2026-11-22

**Status**: Draft

**Input**: User description: "Slice S4 of Feature 1 (Generate Trusted Tests): Repair + failure classes. A generated test that fails for a reason the test itself can fix is sent back to the language model with the real failure, at most 2 repair attempts per record (3 writes in total with the first generation), and every record ends with one honest final status and a reason. Nothing reaches `ready` except through the existing acceptance gate after a clean sandbox run. Builds on S1–S3. Includes: repair loop (US1), honest classification and anti-cheat guards with `suspected_code_bug` as a reason code and not a status (US2), flaky re-run, final run and coverage snapshot, per-test timeout, network-clear errors, `RunRequest` with modes `full` and `collect_only` (US3), dependency manifests kept at upload and a `preflight` stage before generation (US4). No new routes, fields added only. Out of scope: edge and integration levels (S5, S6), strategy registry (S5), subset run mode (S6), idempotency key and cancel (S6), coverage-gap round, quota product, webhooks, Playwright."

## User Scenarios & Testing _(mandatory)_

### User Story 1 - A failing test that the test itself can fix is repaired (Priority: P1)

After the isolated run (S3), some records fail for reasons the test itself can fix: a bad import in
the test, no test collected, a skipped test, one test that hangs, an assertion that is wrong, a test
that passes alone but fails with the others. Instead of stopping at `test_failed`, the job sends the
test back to the language model together with the real failure (which test, which message, the
captured output), asks for a corrected version, checks it, runs it again, and lets it become `ready`
only through the same acceptance gate as before. Each record gets at most 2 repair attempts (3
writes in total, counting the first generation). The same loop repairs static failures found before
running (`syntax_error`, `forbidden_import`, `weak_test`), with the validator's reason in place of
the test tool's output.

**Why this priority**: most first-time failures of generated tests are small and fixable. Without a
repair step the user receives fewer trusted tests and has to fix the rest by hand.

**Independent Test**: with a stand-in model and a stand-in runner, create a job with one record per
repairable cause; check that each is sent back once with its real failure, that a corrected version
is run again, and that the record ends `ready` or ends with its last cause once its attempts run out.

**Acceptance Scenarios**:

1. **Given** a record that failed with `collection_error`, **When** the repair step runs, **Then**
   the record enters stage `repairing`, the model receives the unit context, the full failing test,
   the per-test name and message, the printed output cut to about 3000 characters and the failure
   cause, and the corrected test is validated and run again.
2. **Given** a repaired test that passes its run, **When** the acceptance gate judges it, **Then**
   the record becomes `ready` with evidence showing it was repaired and which attempt produced it.
3. **Given** a record whose second repair still fails, **When** attempts run out, **Then** the record
   ends with the last cause as its final reason and is not repaired again.
4. **Given** a record that failed validation before running with `weak_test`, **When** the repair
   step runs, **Then** the model receives the validator's reason instead of test output, and the
   attempt shares the same budget as run failures.
5. **Given** a record that failed with `no_code` (the model gave no usable code), **When** the repair
   step considers it, **Then** it is not repaired; it follows the normal regeneration path.
6. **Given** a record that failed with an environment error of any kind, **When** the repair step
   considers it, **Then** it is not repaired.
7. **Given** a repaired test with the same fingerprint as a previous attempt of the same record,
   **When** it is detected, **Then** repair stops early for that record and no further model request
   is made for it.
8. **Given** a repaired test that fails validation, **When** it is checked, **Then** it counts as an
   attempt.
9. **Given** the model request limit of the job is reached, or the model is unavailable or its quota
   is used up, **When** repairable records remain, **Then** they keep their status (`test_failed` or
   `generation_failed`) with reason `repair_budget_exhausted`, the job ends `completed_with_issues`,
   and all `ready` results are kept.
10. **Given** a test that passed alone but failed in the final run with the others
    (`fails_with_others`), **When** it is repaired and run alone, **Then** it is included in the final
    run again; if it fails with the others a second time it stays `test_failed` and is not looped.
11. **Given** a test that hung in a single test function, **When** it is repaired, **Then** the
    timeout cause is subject to the same per-record limit as any other cause (at most 2 repair
    attempts, 3 writes in total with the first generation), and repair stops at once if the same
    test fingerprint (`test_sha256`) comes back or the job's request budget runs out.

---

### User Story 2 - Honest classification and no cheating (Priority: P1)

When a test fails an assertion, the failure may be the test's fault or the code's fault. The model
must say which: either `fix_test` (a corrected test with a one-line reason) or `suspect_code` (the
test is right, the code is wrong, with the line or branch and the expected behaviour taken from the
docstring or the signature). A suspected code bug is never hidden by changing the test: the record
stays `test_failed` with reason `suspected_code_bug` and the explanation, the test is left as it is,
and it is not in the package as `ready`. Every repaired test is also checked by automatic guards that
reject ways of "passing" without testing anything. Every record ends with one honest final status and
a reason from a single, written classification.

**Why this priority**: a repair loop that can turn any failing test green by weakening it would
destroy the meaning of `ready` (Principle II). The user must also be told when the code itself looks
wrong.

**Independent Test**: on a sample project with a planted bug, run a job with a stand-in model and
check that the record ends `test_failed` with `suspected_code_bug` and an explanation instead of a
weakened test; then feed the guards one cheating test per rule and check that each is rejected.

**Acceptance Scenarios**:

1. **Given** an assertion failure, **When** the model answers `suspect_code` with the line or branch
   and the expected behaviour, **Then** the record is `test_failed` with reason `suspected_code_bug`
   and that explanation, its test is unchanged, and it is not delivered as `ready`.
2. **Given** an assertion failure, **When** the model answers `fix_test`, **Then** the corrected test
   goes through validation, the guards and a new run like any other repair.
3. **Given** a repaired test that no longer calls the unit under test, **When** the guards run,
   **Then** the attempt fails.
4. **Given** a repaired test that adds `skip`, `xfail` or `skipif`, **When** the guards run, **Then**
   the attempt fails.
5. **Given** a repaired test that wraps the failing call in a block that swallows the failure,
   **When** the guards run, **Then** the attempt fails.
6. **Given** a repaired test that mocks or patches the unit under test, **When** the guards run,
   **Then** the attempt fails.
7. **Given** a repaired test that expects the generic base exception and the original did not,
   **When** the guards run, **Then** the attempt fails.
8. **Given** a repaired test with fewer test functions or fewer asserts than before, **When** the
   guards run, **Then** the attempt fails; the weak-test check of S2 still applies.
9. **Given** any final failure, **When** it is recorded, **Then** it follows the table of FR-016.

10. **Given** any failed test in a run, **When** its result is stored, **Then** it carries the test
    name, the error type (for example `AssertionError`, `ImportError`, `Timeout`) and the message.
11. **Given** a file that cannot be analysed, **When** the plan skips it, **Then** the skip reason is
    the finest known: `syntax_error`, `binary_file` or `empty_file`, instead of the generic
    `analysis_failed` or `no_units`.
12. **Given** any attempt to change a record's status in a way the table of allowed transitions does
    not list, **When** it is made, **Then** it is refused with an error; `ready` stays reachable only
    through the acceptance gate.

---

### User Story 3 - Stable results: flaky check, final run, coverage snapshot (Priority: P2)

After the final run, the kept tests are run two more times without any model call. A test whose
outcome differs between runs is not trusted: its record becomes `test_failed` with reason `flaky` and
is not repaired. If any record was removed, the rest are run once more and the official coverage
comes from that last all-pass run only. When the last final run finishes, one coverage snapshot is
saved so that coverage history can be built later. The sandbox also limits each single test in time
and gives a clear message when a test tries to use the network.

**Why this priority**: a test that sometimes passes is not "trusted", and coverage must come from a
stable run. The snapshot is cheap now and unblocks coverage history later.

**Independent Test**: run a job containing one deliberately flaky test with a stand-in runner; check
that its record is `test_failed` with `flaky`, that coverage comes from a run without it, and that
exactly one snapshot exists for the job.

**Acceptance Scenarios**:

1. **Given** a job after its final run, **When** the flaky check runs, **Then** the kept set is run
   twice more with no model request, and the job shows stage `flaky_check` while it does.
2. **Given** a test whose outcome differs between those runs, **When** the check ends, **Then** its
   record is `test_failed` with reason `flaky` and it is not repaired.
3. **Given** a record was removed by the check, **When** the check ends, **Then** one last final run
   of the remaining tests is made and coverage is taken from that run only.
4. **Given** the last final run has finished, **When** the job completes, **Then** exactly one
   coverage snapshot is appended, with project, version, job, source `manual`, line and branch
   percentages and per-file details; existing snapshots are never changed.
5. **Given** a test that runs longer than the per-test time limit, **When** it runs, **Then** only
   that test is stopped and reported as a timeout, not the whole run; the whole-run kill remains as a
   safety limit and is reported as an environment error.
6. **Given** a test that tries to open a network connection, **When** it runs, **Then** the failure
   message says clearly that the network is disabled.
7. **Given** the existing way to run a record or the final set, **When** it is called through the new
   run request with mode `full`, **Then** the command that is run is unchanged.

---

### User Story 4 - Environment checked before any model request (Priority: P2)

A project that imports a third-party library cannot be tested in an empty environment. Today this is
found only after model requests were spent. At upload, the project's dependency manifests and test
configuration are kept as support files that are not analysed. Between planning and generation, a
`preflight` stage installs the project's dependencies (network on, no secrets) into an environment
that is reused when the manifests and Python version are the same. If the install fails, all records
become `environment_error` and the job fails before the first model request.

**Why this priority**: required by requirement RE-FR-45 (Very High). Without it, repair would burn
requests on a problem no test change can fix.

**Independent Test**: upload a project whose manifest lists a library that cannot be installed;
check that no model request was made, all records are `environment_error`, and the job is `failed`.

**Acceptance Scenarios**:

1. **Given** an upload containing `requirements*.txt`, `pyproject.toml`, `setup.cfg`, `pytest.ini` or
   `conftest.py`, **When** it is stored, **Then** these files are kept as support files and are not
   analysed or planned.
2. **Given** a planned job, **When** it moves on, **Then** it passes through stage `preflight` before
   `generating`.
3. **Given** a manifest whose install fails, **When** preflight ends, **Then** every record is
   `environment_error` with reason `install_failed` or `missing_dependency`, the job is `failed`, and
   no model request was made.
4. **Given** two jobs with identical manifests and Python version, **When** the second reaches
   preflight, **Then** it reuses the stored environment without installing again.
5. **Given** a project with no manifest, **When** it reaches preflight, **Then** preflight passes
   with nothing to install, unless the import probe finds a missing module (scenario 7).
6. **Given** the preflight install, **When** it runs, **Then** the network is on and no secret is
   present; test runs afterwards still have no network.
7. **Given** a project with no manifest (or an incomplete one) whose code imports `requests`,
   **When** preflight ends, **Then** the import probe finds `requests` missing, the records whose file
   needs it are `environment_error / missing_dependency` with detail `requests` before any model
   request, and the other records go on to generation. A module that is installed but fails to import
   for another reason (for example a missing system library) gives `environment_error / import_failed`
   with the error message, and a probe that runs out of time only adds a warning.

---

### Edge Cases

- A record is repaired successfully but the same test fingerprint appears again: repair stops early.
- The job's request limit is reached while several records still wait for repair: each stays
  `test_failed` with `repair_budget_exhausted`; none is partially repaired.
- A repaired test passes alone but fails in the final run: it is `fails_with_others`, repaired once,
  and never looped.
- A test is flaky and also repairable by cause: `flaky` wins and it is not repaired.
- A suspected code bug whose explanation is empty or has no line or expected behaviour: the answer
  is not accepted as `suspect_code`; it counts as a failed attempt.
- Model unavailable half-way: records already `ready` keep their evidence and appear in the package.
- A manifest is present but the install is slow or times out: it is an environment error, not a test
  failure.
- Two jobs for the same project and version start at the same time: only one install is made.

## Requirements _(mandatory)_

### Functional Requirements

**Repair loop**

- **FR-001**: After a sandbox run, a record that failed for one of these causes MUST be repairable:
  `collection_error`, `no_tests`, `skipped_test`, `timeout` of one test function, `assertion`,
  `fails_with_others`. All of them share the per-record limit of FR-004 and the early stop of FR-008.
- **FR-002**: Static failures found before running (`syntax_error`, `forbidden_import`, `weak_test`)
  MUST be repaired in the same loop and share the same budget; the repair request MUST carry the
  validator's reason instead of the test tool's output. `no_code` and `unsafe_code` MUST NOT be
  repaired. There is no
  separate regeneration step: a static failure of the first write goes to this loop only.
- **FR-003**: Environment errors of any kind, and failures after the budget is spent, MUST NOT be
  repaired. A run that fails because the project imports a module that is neither part of the project
  nor the standard library MUST be `environment_error / missing_dependency` (not `collection_error`)
  and MUST NOT be repaired.
- **FR-004**: Each record MUST get at most 2 repair attempts (3 writes in total, counting the first
  generation). A repaired candidate that fails validation or the guards MUST count as an attempt.
- **FR-005**: A repair request MUST contain: the generation context, the full failing test, the
  per-test name and message, the printed output cut to about 3000 characters, the failure cause, and
  the same generation rules as the first request. Its template MUST be versioned as `repair-v1`.
- **FR-006**: A repaired test MUST pass validation and safety lint, then a sandbox run, and become
  `ready` only through the existing acceptance gate; otherwise the record ends `test_failed` (or its
  final class per FR-016) with the last cause.
- **FR-007**: The model call of a repair MUST run on the normal worker and the sandbox run MUST stay
  on the sandbox worker, which holds no keys. The job moves between them by being enqueued again; no
  task MUST wait for another task.
- **FR-008**: When a repaired test has the same fingerprint (`test_sha256`) as one of the record's
  earlier writes, repair MUST stop at once for that record: it goes straight to final classification
  (FR-016) with its last cause, even if attempts are left, and no further request is made for it.
- **FR-009**: Every repair request MUST be recorded as an attempt with purpose `repair`, together with
  model and token counts.
- **FR-010**: Generation and repair requests MUST count toward one per-job model request limit set by
  a setting (30). When the limit is reached, or the model is unavailable or its quota is used up:
  - records still waiting for repair MUST keep their status (`test_failed` stays `test_failed`,
    a static `generation_failed` stays `generation_failed`) and get reason `repair_budget_exhausted`,
    with the original cause kept in the reason detail;
  - records not yet generated keep the S2 behaviour (they stay `pending`, the job carries the stop
    reason and the message "start a new job to continue");
  - records already `generated` are still run; results already `ready` MUST be kept;
  - the job MUST end `completed_with_issues`.
- **FR-011**: A `fails_with_others` record MUST be repaired once, run alone, and then included in the
  final run, **only if it still has a repair attempt left** (FR-004). If it has none, it MUST stay
  `test_failed / fails_with_others` at once. If it fails with the others again after its repair it MUST
  stay `test_failed` and MUST NOT be repaired again.

**Classification and guards**

- **FR-012**: On an assertion failure, the model MUST answer `fix_test` (a corrected test plus a
  one-line reason) or `suspect_code` (the test is right; the line or branch of the code and the
  expected behaviour from the docstring or signature). A `suspect_code` answer MUST leave the record
  `test_failed` with reason `suspected_code_bug` and the explanation, the test MUST NOT be changed,
  and the record MUST NOT be delivered as `ready`.
- **FR-013**: `suspected_code_bug` MUST be a reason code, not a status. The five final statuses of
  Principle VII (`ready`, `skipped`, `generation_failed`, `environment_error`, `test_failed`) MUST stay
  the only ones.
- **FR-014**: Every repaired test MUST pass automatic guards; a violation is a failed attempt. The
  guards: the unit under test is still called (a constructor counts as called when its class is called,
  a special method when its operator or built-in is used); no `skip`, `xfail` or `skipif`; no
  `try`/`except` that swallows the failure; no mocking or patching of the unit under test; no generic
  base-exception expectation unless the original had it; the number of test functions and of asserts
  does not drop; the S2 weak-test check still applies. Rules that compare with the original test apply
  only when the original can be parsed. The reason of a rejected candidate MUST be given to the model in
  the next repair request. Expected values that a repair changes MUST be recorded for review (they are
  not a violation, because sometimes the test is the one that is wrong).
- **FR-015**: A record MUST NOT be left with a repair outcome other than: `ready` via the gate, or a
  final status and reason from FR-016.
- **FR-016**: Final classification MUST follow this table:

  | Situation after the budget is spent                                        | Status              | Reason                       |
  | -------------------------------------------------------------------------- | ------------------- | ---------------------------- |
  | Syntax, import or collection failure (pytest exit 5 included)              | `generation_failed` | the last cause               |
  | Static check still fails (`syntax_error`, `forbidden_import`, `weak_test`) | `generation_failed` | that cause, e.g. `weak_test` |
  | Assertion failure                                                          | `test_failed`       | `assertion`                  |
  | Single-test timeout                                                        | `test_failed`       | `timeout`                    |
  | A test is still skipped                                                    | `test_failed`       | `skipped_test`               |
  | Still fails only with the others                                           | `test_failed`       | `fails_with_others`          |
  | Model says the code is wrong                                               | `test_failed`       | `suspected_code_bug`         |
  | Outcome differs between repeated runs                                      | `test_failed`       | `flaky`                      |
  | Repair requests ran out (run failure)                                      | `test_failed`       | `repair_budget_exhausted`    |
  | Repair requests ran out (static failure)                                   | `generation_failed` | `repair_budget_exhausted`    |
  | Project imports a library that is not installed                            | `environment_error` | `missing_dependency`         |
  | Library installed but fails to import (e.g. missing system library)        | `environment_error` | `import_failed`              |
  | Whole-run kill, out of memory (137), install failed, sandbox unavailable   | `environment_error` | the specific cause           |

- **FR-017**: Allowed record status transitions MUST be defined in one table and enforced; any other
  transition MUST raise an error. The table MUST contain exactly these changes (besides the S1–S3 ones:
  `pending → generated | generation_failed | skipped`, `generated → test_failed | environment_error`):
  - `test_failed → generated` and `generation_failed → generated`: repair step only, and only while
    attempts used are fewer than the maximum;
  - `test_failed → generation_failed`: final classification of `collection_error` / `no_tests`;
  - `test_failed → test_failed` and `generation_failed → generation_failed`: reason change only
    (`suspected_code_bug`, `repair_budget_exhausted`, final cause);
  - `ready → test_failed`: final run (`fails_with_others`) and flaky check (`flaky`) only;
  - `pending → environment_error`: preflight only;
  - `generated → ready`: acceptance gate only.
- **FR-018**: Every failed test in a run MUST be stored with its name, its error type and its message
  (RE-FR-46).
- **FR-019**: Files that cannot be analysed MUST be skipped with the finest known reason —
  `syntax_error`, `binary_file` or `empty_file` (RE-FR-43) — instead of the generic `analysis_failed`
  or `no_units` where the cause is known.

**Stable results**

- **FR-020**: After the final run, the kept set MUST be run 2 more times with no model call. A test
  whose outcome differs between runs MUST make its record `test_failed` with reason `flaky`; it MUST
  NOT be repaired. A re-run that gives no per-test result (whole-run kill, out of memory, sandbox
  unavailable) MUST be retried once; if it fails the same way again, the check is recorded on the job
  as inconclusive, the records stay `ready` (they passed the final run), and the job ends
  `completed_with_issues` with that notice.
- **FR-021**: If any record was removed by the flaky check, one more final run of the rest MUST be
  made. If a test fails in that run, its record MUST become `test_failed / fails_with_others` without
  repair and without a second flaky check, and the final run MUST be repeated without it (the S3 loop,
  bounded by the number of records) until one run passes completely or no test is left. The job's
  official coverage MUST come from that last all-pass run only.
- **FR-022**: After the last all-pass final run, one coverage snapshot MUST be appended to a new,
  append-only store with: project, version number, job, source `manual`, line percentage, branch
  percentage and per-file details. A job without an all-pass final run (no `ready` test) MUST NOT write
  a snapshot. The store MUST hold at most one snapshot per job (unique on the job), so a repeated task
  cannot write twice. Snapshots MUST NOT be updated or deleted by this feature.
- **FR-023**: The run environment MUST limit each single test in time (default 30 seconds), so that
  one hanging test does not kill the whole run. The whole-run limit MUST grow with the number of tests
  so that hanging tests alone cannot reach it: `30 × tests + 30` seconds, at least 60 and at most 300.
  Reaching the whole-run limit MUST be reported as an environment error.
- **FR-024**: The run environment MUST make network use fail with a clear "network disabled" message.
- **FR-025**: Every sandbox run (single record, final run, flaky re-runs) MUST be requested through
  one `RunRequest` object (job, version number, workspace reference, test paths, mode) instead of
  loose arguments. Use `collect_only` before executing a generated or repaired record. Only a full run can supply acceptance evidence. For `full` the command MUST be
  exactly the same as the S3 command, and the existing S3 tests of the executor MUST pass unchanged.

**Environment preflight**

- **FR-026**: At upload, `requirements*.txt` (and any `.txt` inside a `requirements/` folder),
  `pyproject.toml`, `setup.cfg`, `pytest.ini` and `conftest.py` MUST be kept as support files; they
  MUST NOT be analysed or planned. No other name is kept by this rule.
- **FR-027**: A stage `preflight` MUST run between `planned` and `generating`. It MUST install the
  project's dependencies with the network on and no secrets, and MUST store the resulting environment
  keyed by a hash of the manifests plus the Python version, and reuse it when the hash matches.
  Manifest lines that cannot be installed from the kept files alone (`-r` to a file that was not kept,
  `-e`, `-c`, index options) MUST be left out with a warning on the job, not fail the install.
  Development and documentation requirement files MUST NOT be merged into the install when a main
  requirements file exists. Without one, environment-specific files (production, local, staging, CI,
  development, docs, tests, lint) MUST NOT be merged either; names are compared word by word, not as
  substrings.
- **FR-028**: If preflight fails, every record MUST become `environment_error` with reason
  `install_failed` or `missing_dependency`, and the job MUST fail before any model request. Only a
  definite failure (a package that does not exist, conflicting versions) MAY be cached for later jobs;
  a temporary failure (network, time limit) MUST be retried once and MUST NOT be cached.
- **FR-029**: Test runs after preflight MUST keep the isolation of S3 (no network, read-only source,
  limits, non-root, no secrets).
- **FR-037**: Preflight MUST end, with or without a manifest, by checking without network that every
  third-party module the project imports can be imported in the prepared environment. Only a
  "module not found" error for that module itself means `missing_dependency`; records whose file needs
  such a module (directly or through project modules) MUST become `environment_error /
missing_dependency` with the module name before any model request. Any other import error MUST give
  `environment_error / import_failed` with the error message for those records. A probe that runs out
  of time or memory MUST NOT mark any record; it only adds a warning to the job. The other records
  continue; if every record is affected, the job fails.
- **FR-036**: When two or more jobs reach preflight at the same time with the same environment key
  (hash of manifests plus Python version), the install MUST be coordinated by a lock so that it runs
  once; the other jobs MUST wait by being enqueued again (not by blocking a task) and then reuse the
  stored environment. A half-finished environment MUST never be reused.

**Outputs (no new routes; fields added only)**

- **FR-030**: The job MUST add stages `preflight`, `repairing`, `flaky_check` and a progress count
  `repaired`.
- **FR-031**: A record MUST add `attempts[]` (number, purpose `generate` or `repair`, run identifier,
  outcome, cause, test fingerprint, changed expected values), `evidence.repaired`, `evidence.attempt`,
  and the reason codes `suspected_code_bug`, `flaky` and `repair_budget_exhausted`. The run identifier
  and outcome of an attempt MUST be filled in when its run ends.
- **FR-032**: The package's `records_summary.json` MUST list every record with its final status,
  reason, explanation (when there is one), attempts and changed expected values. Records ending
  `suspected_code_bug`, `flaky` or any other failure MUST appear there only. The tests folder of the
  package MUST contain the tests of `ready` records only.

**Boundaries**

- **FR-033**: Automated tests of this slice MUST NOT make real model calls; each failure class MUST
  be shown by a deliberate test case with a stand-in model and a stand-in sandbox.
- **FR-034**: The slice MUST keep the feature's import boundary and MUST keep all existing tests
  green.
- **FR-035**: Nothing outside this slice MUST be implemented (see Assumptions).

### Key Entities _(include if feature involves data)_

- **Attempt**: one write of a test for a record: number, purpose (`generate` or `repair`), the run it
  led to, outcome, cause, test fingerprint, model and token counts.
- **Repair request**: the unit context, the failing test, per-test failures, cut output, cause and
  rules sent to the model; template version `repair-v1`.
- **Failure class**: the final status and reason a record ends with, from the single classification
  table.
- **Guard violation**: the rule a repaired test broke; makes the attempt fail.
- **Support file**: a dependency manifest or test configuration kept at upload and not analysed.
- **Environment (preflight)**: an installed set of dependencies keyed by the hash of manifests and
  Python version, reused between jobs.
- **Coverage snapshot**: an append-only point of coverage for a project version and job.
- **Status transition table**: the list of allowed record status changes.

## Success Criteria _(mandatory)_

### Measurable Outcomes

- **SC-001**: Each failure class of FR-016 is demonstrated by one deliberate test case, and 100% of
  them end with the status and reason the table gives.
- **SC-002**: No record reaches `ready` without a clean sandbox run and the acceptance gate; across
  all test cases, 0 repaired tests become `ready` after a guard violation.
- **SC-003**: No record has more than 3 writes (first generation plus 2 repairs).
- **SC-004**: On a sample project with a planted bug, a real run ends with `suspected_code_bug` and an
  explanation, and no cheating test is delivered.
- **SC-005**: A deliberately flaky test is excluded from `ready` and from the official coverage in
  100% of runs of the test case.
- **SC-006**: Exactly one coverage snapshot exists for each finished job that has an all-pass final
  run, and none for a job without one.
- **SC-007**: A project with an uninstallable dependency makes 0 model requests and ends `failed`
  with every record `environment_error`.
- **SC-009**: A project with no manifest that imports a library not in the environment spends 0 model
  requests on the records that need it (they end `environment_error / missing_dependency`), while its
  other records are generated as usual; a probe time-out marks no record.
- **SC-008**: All tests of S1–S3 stay green, and no automated test makes a real model call.

## Assumptions

- Maximum repair attempts: 2 per record (3 writes in total), matching the "at most 3" of Principle III.
- Decision: one per-job model request limit covers both generation and repair. The existing setting
  `TESTGEN_MAX_REQUESTS_PER_JOB` is raised from 20 to 30; there is no separate repair limit. When it is
  reached, generation of new units and repair both stop and FR-010 applies.
- Per-test time limit default is 30 seconds; the whole-run time limit stays as in S3.
- Python and pytest only; a second language is out of scope (Principle IV).
- S3 (sandbox, acceptance gate, final run, coverage, package) is available in the code this slice builds
  on, and its spec is committed before S4 code starts.
- The snapshot's `source` is always `manual` in this slice; other sources belong to later features.
- The sandbox worker periodically removes expired labelled containers and backs off before retrying unavailable runs.
- **Out of scope**: edge and integration levels (S5, S6); strategy registry (S5); subset run mode (S6); idempotency key and cancel (S6); coverage-gap round; quota product;
  webhooks; Playwright. Nothing outside this slice is implemented.
