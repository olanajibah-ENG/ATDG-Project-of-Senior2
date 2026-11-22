"""DockerSandboxExecutor against a recording stand-in for the Docker SDK: no engine, no container.

Pins the isolation options of every run (spec FR-005, research R4) and the clean-up rules.
"""
import io
import tarfile

import pytest

from core_ai.services.test_generation.sandbox.docker_executor import RUN_ENVIRONMENT, DockerSandboxExecutor
from core_ai.services.test_generation.sandbox.executor import RunSpec


def _tar_of(name, text):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        data = text.encode()
        info = tarfile.TarInfo(name)
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


class FakeContainer:
    def __init__(self, client, kwargs, args):
        self.client, self.kwargs, self.args = client, kwargs, args
        self.started = self.removed = self.killed = False
        self.archives = []

    def put_archive(self, path, data):
        self.archives.append((path, data))
        return True

    def start(self):
        if self.client.fail_start:
            raise RuntimeError("no such image")
        self.started = True

    def wait(self, timeout=None):
        self.client.wait_timeouts.append(timeout)
        if self.client.hang:
            raise TimeoutError("read timed out")
        return {"StatusCode": self.client.exit_code}

    def kill(self):
        self.killed = True

    def logs(self, stdout=True, stderr=True):
        return b"1 passed in 0.01s"

    def get_archive(self, path):
        files = self.client.out_files
        if path not in files:
            raise FileNotFoundError(path)
        return iter([_tar_of(path.rsplit("/", 1)[-1], files[path])]), {}

    def remove(self, force=False):
        self.removed = True


class FakeVolume:
    def __init__(self, client, name):
        self.client, self.name = client, name

    def remove(self, force=False):
        self.client.removed_volumes.append(self.name)


class FakeClient:
    def __init__(self, exit_code=0, hang=False, fail_start=False, out_files=None):
        self.exit_code, self.hang, self.fail_start = exit_code, hang, fail_start
        self.out_files = out_files if out_files is not None else {"/out/junit.xml": "<testsuites/>",
                                                                  "/out/cov.json": "{}"}
        self.created, self.created_volumes, self.removed_volumes, self.wait_timeouts = [], [], [], []
        client = self

        class Containers:
            def create(self, *args, **kwargs):
                container = FakeContainer(client, kwargs, args)
                client.created.append(container)
                return container

        class Volumes:
            def create(self, name, labels=None):
                client.created_volumes.append((name, labels))
                return FakeVolume(client, name)

            def get(self, name):
                return FakeVolume(client, name)

        self.containers, self.volumes = Containers(), Volumes()

    @property
    def loaders(self):
        return [c for c in self.created if c.kwargs.get("command") == ["true"]]

    @property
    def runs(self):
        return [c for c in self.created if c.kwargs.get("command") != ["true"]]


def spec(timeout=60):
    return RunSpec(run_id="sbx_job_x_t_1_1", job_id="job_x", src_volume="sbx_job_x_src",
                   test_files={"pytest.ini": b"[pytest]\n", "generated/test_a.py": b"def test_a(): pass\n"},
                   test_paths=["tests/generated/test_a.py"], timeout_s=timeout)


def test_run_container_has_every_isolation_option():
    client = FakeClient()
    DockerSandboxExecutor(client).run(spec())
    (run,) = client.runs
    k = run.kwargs
    assert k["image"] == "autotest-sandbox:py3.10-s3"
    assert k["network_mode"] == "none"
    assert k["read_only"] is True
    assert k["tmpfs"] == {"/tmp": "rw,size=64m"}
    assert k["nano_cpus"] == 1_000_000_000
    assert k["mem_limit"] == "512m" and k["memswap_limit"] == "512m"
    assert k["pids_limit"] == 128
    assert k["cap_drop"] == ["ALL"]
    assert k["security_opt"] == ["no-new-privileges"]
    assert k["user"] == "10001:10001"
    assert k["environment"] == RUN_ENVIRONMENT == {
        "PYTHONPATH": "/workspace/src", "PYTHONDONTWRITEBYTECODE": "1", "COVERAGE_FILE": "/tmp/.coverage"}
    assert k["volumes"] == {
        "sbx_job_x_src": {"bind": "/workspace/src", "mode": "ro"},
        "sbx_job_x_t_1_1_tests": {"bind": "/workspace/tests", "mode": "ro"},
        "sbx_job_x_t_1_1_out": {"bind": "/out", "mode": "rw"},
    }
    assert k["command"][:3] == ["timeout", "--signal=KILL", "60"]
    assert "--junitxml=/out/junit.xml" in k["command"] and "--cov-branch" in k["command"]
    assert "tests/generated/test_a.py" in k["command"]


def test_no_secret_or_worker_setting_reaches_the_run():
    client = FakeClient()
    DockerSandboxExecutor(client).run(spec())
    env = client.runs[0].kwargs["environment"]
    for word in ("KEY", "SECRET", "TOKEN", "PASSWORD", "MONGO", "REDIS", "DJANGO", "CELERY"):
        assert not any(word in name for name in env)


def test_loader_fills_the_tests_volume_and_is_never_started():
    client = FakeClient()
    DockerSandboxExecutor(client).run(spec())
    (loader,) = client.loaders
    assert loader.started is False and loader.removed is True
    assert loader.kwargs["network_mode"] == "none"
    paths = [p for p, _ in loader.archives]
    assert paths == ["/workspace/tests"]
    with tarfile.open(fileobj=io.BytesIO(loader.archives[0][1])) as tar:
        assert {"pytest.ini", "generated/test_a.py"} <= set(tar.getnames())


def test_results_are_read_and_everything_is_removed():
    client = FakeClient(exit_code=1, out_files={"/out/junit.xml": "<testsuites>j</testsuites>",
                                                "/out/cov.json": '{"files": {}}'})
    out = DockerSandboxExecutor(client).run(spec())
    assert out.started and out.exit_code == 1 and not out.timed_out
    assert out.junit_xml == "<testsuites>j</testsuites>" and out.cov_json == '{"files": {}}'
    assert out.output == "1 passed in 0.01s"
    assert client.runs[0].removed is True
    assert sorted(client.removed_volumes) == ["sbx_job_x_t_1_1_out", "sbx_job_x_t_1_1_tests"]
    assert out.options["network"] == "none" and out.options["timeout_s"] == 60


def test_missing_result_files_are_none():
    out = DockerSandboxExecutor(FakeClient(out_files={})).run(spec())
    assert out.junit_xml is None and out.cov_json is None


def test_the_wait_is_bounded_and_an_overrun_kills_the_container():
    client = FakeClient(hang=True)
    out = DockerSandboxExecutor(client).run(spec(timeout=60))
    assert client.wait_timeouts == [75]
    assert out.timed_out is True and out.exit_code is None
    assert client.runs[0].killed is True and client.runs[0].removed is True


def test_a_container_that_cannot_start_is_reported_and_cleaned():
    client = FakeClient(fail_start=True)
    out = DockerSandboxExecutor(client).run(spec())
    assert out.started is False and "no such image" in out.start_error
    assert client.runs[0].removed is True
    assert sorted(client.removed_volumes) == ["sbx_job_x_t_1_1_out", "sbx_job_x_t_1_1_tests"]


def test_prepare_and_discard_the_source_volume():
    client = FakeClient()
    executor = DockerSandboxExecutor(client)
    volume = executor.prepare_source("job_x", {"demo/course.py": b"class Course: pass\n"})
    assert volume == "sbx_job_x_src"
    (loader,) = client.loaders
    assert loader.started is False and [p for p, _ in loader.archives] == ["/workspace/src"]
    executor.discard_source(volume)
    assert client.removed_volumes == ["sbx_job_x_src"]


@pytest.mark.parametrize("with_coverage", [True, False])
def test_coverage_options_follow_the_spec(with_coverage):
    client = FakeClient()
    s = spec()
    s.with_coverage = with_coverage
    DockerSandboxExecutor(client).run(s)
    assert ("--cov-branch" in client.runs[0].kwargs["command"]) is with_coverage
