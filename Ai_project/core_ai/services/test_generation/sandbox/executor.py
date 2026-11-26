"""The run of a test file in an isolated environment, as an interface.

`DockerSandboxExecutor` (docker_executor.py) is the real one; the tests use a scripted fake. Nothing
else in the package knows how a run is isolated: it hands over a `RunSpec` and reads a `RunOutput`.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


class RunMode:
    FULL = "full"
    COLLECT_ONLY = "collect_only"


@dataclass
class RunRequest:
    run_id: str
    job_id: str
    src_volume: str                       # from prepare_source(); mounted read-only
    test_files: dict                      # {relative path under /workspace/tests: bytes}
    test_paths: list                      # paths given to pytest, relative to /workspace
    timeout_s: int
    with_coverage: bool = True
    mode: str = RunMode.FULL
    env_volume: object = None             # S4 preflight environment, mounted read-only when given


RunSpec = RunRequest                      # S3 name, kept for existing callers


@dataclass
class InstallRequest:
    env_key: str
    requirements_text: str
    timeout_s: int


@dataclass
class InstallOutput:
    ok: bool
    volume: object = None
    exit_code: object = None
    output: str = ""
    missing: bool = False
    temporary: bool = False
    size_bytes: int = 0


@dataclass
class ProbeRequest:
    src_volume: str
    env_volume: object
    modules: list


@dataclass
class RunOutput:
    run_id: str
    started: bool                         # False: the environment could not be started
    exit_code: object = None              # int, or None when not started / killed by the worker
    timed_out: bool = False
    junit_xml: object = None              # str, or None when no file was written
    cov_json: object = None               # str, or None
    output: str = ""                      # printed output, already cut to the configured size
    start_error: object = None            # str when started is False
    duration_s: float = 0.0
    options: dict = field(default_factory=dict)   # image and limits used, for the run record
    oom_killed: bool = False              # Docker's State.OOMKilled: exit 137 is shared with a KILL timeout


class SandboxExecutor(ABC):
    def reap_expired(self):
        """Clean up expired resources when the backend allocates persistent containers."""

    @abstractmethod
    def prepare_source(self, job_id, files):
        """Make the version's files ({path: bytes}) available read-only; → a volume name."""

    @abstractmethod
    def run(self, spec):
        """Run one test set; never raises: problems come back in RunOutput."""

    @abstractmethod
    def discard_source(self, volume):
        """Remove what prepare_source made."""


_executor = None


def get_executor():
    global _executor
    if _executor is None:
        from core_ai.services.test_generation.sandbox.docker_executor import DockerSandboxExecutor

        _executor = DockerSandboxExecutor()
    return _executor


def set_executor(executor):
    """For tests (and for a different runner later). None puts the default back on next use."""
    global _executor
    _executor = executor
