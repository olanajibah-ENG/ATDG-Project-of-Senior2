"""Status vocabularies of Feature 1. Plain string constants, stored as-is in Mongo."""


class JobStatus:
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_ISSUES = "completed_with_issues"
    FAILED = "failed"
    CANCELLED = "cancelled"

    FINAL = (COMPLETED, COMPLETED_WITH_ISSUES, FAILED, CANCELLED)


class JobStage:
    QUEUED = "queued"
    WAITING_ANALYSIS = "waiting_analysis"
    PLANNING = "planning"
    PLANNED = "planned"
    GENERATING = "generating"
    GENERATED = "generated"
    SANDBOX_RUN = "sandbox_run"      # S3: records run one by one in isolated containers
    FINAL_RUN = "final_run"          # S3: every ready test together, for the official coverage
    PREFLIGHT = "preflight"          # S4: dependencies installed and imports probed, before generating
    REPAIRING = "repairing"          # S4: failed tests sent back to the model, one record per pass
    FLAKY_CHECK = "flaky_check"      # S4: the kept set re-run without the model


class FileStatus:
    PENDING = "pending"
    READY = "ready"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED = "skipped"


class SkipReason:
    UNSUPPORTED_LANGUAGE = "unsupported_language"
    ANALYSIS_FAILED = "analysis_failed"
    NO_UNITS = "no_units"
    EMPTY_OR_ABSTRACT = "empty_or_abstract"
    BODY_TRUNCATED = "body_truncated"
    PRIVATE = "private"
    SYNTAX_ERROR = "syntax_error"
    BINARY_FILE = "binary_file"
    EMPTY_FILE = "empty_file"

    ALL = (UNSUPPORTED_LANGUAGE, ANALYSIS_FAILED, NO_UNITS, EMPTY_OR_ABSTRACT, BODY_TRUNCATED, PRIVATE,
           SYNTAX_ERROR, BINARY_FILE, EMPTY_FILE)


class Level:
    UNIT = "unit"
    EDGE = "edge"
    INTEGRATION = "integration"

    ALL = (UNIT, EDGE, INTEGRATION)


class RecordStatus:
    PENDING = "pending"
    GENERATED = "generated"          # written and checked for form; NOT run
    READY = "ready"                  # only the acceptance gate may set this (sandbox slice)
    SKIPPED = "skipped"
    GENERATION_FAILED = "generation_failed"
    TEST_FAILED = "test_failed"
    ENVIRONMENT_ERROR = "environment_error"


class FailReason:
    NO_CODE = "no_code"
    SYNTAX_ERROR = "syntax_error"
    FORBIDDEN_IMPORT = "forbidden_import"
    UNSAFE_CODE = "unsafe_code"
    WEAK_TEST = "weak_test"


class StopReason:
    MODEL_UNAVAILABLE = "model_unavailable"
    REQUEST_LIMIT_REACHED = "request_limit_reached"


# Record statuses shown in progress.by_status.
RECORD_STATUSES = ("pending", "generated", "ready", "skipped", "generation_failed", "test_failed",
                   "environment_error")


class RunReason:
    """Why a run record did not become `ready` (S3)."""
    ASSERTION = "assertion"
    COLLECTION_ERROR = "collection_error"
    NO_TESTS = "no_tests"
    SKIPPED_TEST = "skipped_test"
    TIMEOUT = "timeout"
    FAILS_WITH_OTHERS = "fails_with_others"
    MISSING_DEPENDENCY = "missing_dependency"
    SANDBOX_UNAVAILABLE = "sandbox_unavailable"
    NO_RESULT_FILE = "no_result_file"
    RUN_TIMEOUT = "run_timeout"            # S4: the whole run was killed at its limit
    OUT_OF_MEMORY = "out_of_memory"        # S4: the run was killed for memory
    INSTALL_FAILED = "install_failed"      # S4: preflight could not install the dependencies
    IMPORT_FAILED = "import_failed"        # S4: installed, but importing it fails (e.g. a system library)


RUN_FAILED_REASONS = (RunReason.ASSERTION, RunReason.COLLECTION_ERROR, RunReason.NO_TESTS,
                      RunReason.SKIPPED_TEST, RunReason.TIMEOUT, RunReason.FAILS_WITH_OTHERS)
RUN_ENV_REASONS = (RunReason.MISSING_DEPENDENCY, RunReason.SANDBOX_UNAVAILABLE, RunReason.NO_RESULT_FILE,
                   RunReason.RUN_TIMEOUT, RunReason.OUT_OF_MEMORY, RunReason.INSTALL_FAILED,
                   RunReason.IMPORT_FAILED)


class RepairReason:
    """Reason codes added by S4 (never statuses: Principle VII keeps five final statuses)."""
    SUSPECTED_CODE_BUG = "suspected_code_bug"
    FLAKY = "flaky"
    REPAIR_BUDGET_EXHAUSTED = "repair_budget_exhausted"


REPAIRABLE_RUN_CAUSES = (RunReason.COLLECTION_ERROR, RunReason.NO_TESTS, RunReason.SKIPPED_TEST,
                         RunReason.TIMEOUT, RunReason.ASSERTION, RunReason.FAILS_WITH_OTHERS)
REPAIRABLE_STATIC_CAUSES = (FailReason.SYNTAX_ERROR, FailReason.FORBIDDEN_IMPORT, FailReason.WEAK_TEST)
REPAIRABLE_CAUSES = REPAIRABLE_RUN_CAUSES + REPAIRABLE_STATIC_CAUSES


class Actor:
    """Who changes a record's status; the transition table says who may do what."""
    PLAN = "plan"
    PREFLIGHT = "preflight"
    GENERATE = "generate"
    RUN = "run"
    GATE = "gate"
    REPAIR = "repair"
    FINALIZE = "finalize"
    FINAL_RUN = "final_run"
    FLAKY = "flaky"


_S = RecordStatus
# (from, to) → actors allowed to make that change. Nothing else is allowed (FR-017).
TRANSITIONS = {
    (_S.PENDING, _S.GENERATED): {Actor.GENERATE},
    (_S.PENDING, _S.GENERATION_FAILED): {Actor.GENERATE},
    (_S.PENDING, _S.SKIPPED): {Actor.PLAN},
    (_S.PENDING, _S.ENVIRONMENT_ERROR): {Actor.PREFLIGHT},
    (_S.GENERATED, _S.READY): {Actor.GATE},
    (_S.GENERATED, _S.TEST_FAILED): {Actor.RUN},
    (_S.GENERATED, _S.ENVIRONMENT_ERROR): {Actor.RUN},
    (_S.TEST_FAILED, _S.GENERATED): {Actor.REPAIR},
    (_S.GENERATION_FAILED, _S.GENERATED): {Actor.REPAIR},
    (_S.TEST_FAILED, _S.GENERATION_FAILED): {Actor.FINALIZE},
    (_S.TEST_FAILED, _S.TEST_FAILED): {Actor.REPAIR, Actor.FINALIZE},
    (_S.GENERATION_FAILED, _S.GENERATION_FAILED): {Actor.REPAIR, Actor.FINALIZE},
    (_S.READY, _S.TEST_FAILED): {Actor.FINAL_RUN, Actor.FLAKY},
}


class IllegalTransition(ValueError):
    """A status change the transition table does not allow, or whose record is not in a source state."""


def allowed(from_status, to_status, actor):
    return actor in TRANSITIONS.get((from_status, to_status), ())


def sources_of(to_status, actor):
    """Statuses a record may be in for `actor` to move it to `to_status`."""
    return {src for (src, dst), actors in TRANSITIONS.items() if dst == to_status and actor in actors}
