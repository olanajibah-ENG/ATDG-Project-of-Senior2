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

    ALL = (UNSUPPORTED_LANGUAGE, ANALYSIS_FAILED, NO_UNITS, EMPTY_OR_ABSTRACT, BODY_TRUNCATED, PRIVATE)


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


RUN_FAILED_REASONS = (RunReason.ASSERTION, RunReason.COLLECTION_ERROR, RunReason.NO_TESTS,
                      RunReason.SKIPPED_TEST, RunReason.TIMEOUT, RunReason.FAILS_WITH_OTHERS)
RUN_ENV_REASONS = (RunReason.MISSING_DEPENDENCY, RunReason.SANDBOX_UNAVAILABLE, RunReason.NO_RESULT_FILE)
