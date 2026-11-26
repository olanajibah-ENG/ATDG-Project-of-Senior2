"""The real sandbox: one fresh container per run, started through the Docker engine (research R1–R4).

This is the ONLY module of the service that talks to the container engine (checked by
test_boundaries.py), and it only runs in testgen_sandbox_worker, which holds no keys.

Files reach the read-only run container through named volumes, filled by a short-lived *loader*
container that is created but never started:

    <job>_src    the version's files     mounted read-only at /workspace/src   (once per job)
    <run>_tests  test files + pytest.ini mounted read-only at /workspace/tests (per run)
    <run>_out    results                 mounted read-write at /out            (per run)
"""
import io
import json
import uuid
import logging
import tarfile
import time

from django.conf import settings

from core_ai.services.test_generation.languages.base import adapter_for
from core_ai.services.test_generation.sandbox import workspace
from core_ai.services.test_generation.sandbox.executor import RunMode, RunOutput, SandboxExecutor

logger = logging.getLogger(__name__)

RUN_USER = "10001:10001"
# Exactly what the run sees of its environment: nothing of the worker's (no database URL, no key).
RUN_ENVIRONMENT = {
    "PYTHONPATH": "/workspace/src",
    "PYTHONDONTWRITEBYTECODE": "1",
    "COVERAGE_FILE": "/tmp/.coverage",     # the working directory is read-only
}
WAIT_MARGIN_S = 15
LABELS = {"autotest.sandbox": "1"}
EXPIRY_LABEL = "autotest.sandbox.expires"


def _container_labels(timeout_s):
    # Leave time for the worker to read artifacts after Docker stops the process.
    return dict(LABELS, **{EXPIRY_LABEL: str(int(time.time()) + timeout_s + 600)})


def _limits():
    return {
        "image": settings.TESTGEN_SANDBOX_IMAGE,
        "network": "none",
        "cpus": 1,
        "memory": settings.TESTGEN_SANDBOX_MEMORY,
        "pids": settings.TESTGEN_SANDBOX_PIDS,
        "read_only": True,
        "tmpfs_tmp": "64m",
        "user": RUN_USER,
    }


def run_container_options(spec, src_volume, tests_volume, out_volume):
    """Everything the run container is created with. Kept in one place so a test can pin it."""
    adapter = adapter_for("python", "x.py")
    environment = dict(RUN_ENVIRONMENT)
    volumes = {
        src_volume: {"bind": "/workspace/src", "mode": "ro"},
        tests_volume: {"bind": "/workspace/tests", "mode": "ro"},
        out_volume: {"bind": "/out", "mode": "rw"},
    }
    env_volume = getattr(spec, "env_volume", None)
    if env_volume:
        volumes[env_volume] = {"bind": "/workspace/deps", "mode": "ro"}
        environment["PYTHONPATH"] = "/workspace/src:/workspace/deps"
    collect = spec.mode == RunMode.COLLECT_ONLY
    command = adapter.run_argv(spec.test_paths, spec.timeout_s, spec.with_coverage and not collect)
    if collect:
        command.append("--collect-only")
    return dict(
        image=settings.TESTGEN_SANDBOX_IMAGE,
        command=command,
        name=spec.run_id,
        working_dir="/workspace",
        network_mode="none",
        read_only=True,
        tmpfs={"/tmp": "rw,size=64m"},
        nano_cpus=1_000_000_000,
        mem_limit=settings.TESTGEN_SANDBOX_MEMORY,
        memswap_limit=settings.TESTGEN_SANDBOX_MEMORY,
        pids_limit=settings.TESTGEN_SANDBOX_PIDS,
        cap_drop=["ALL"],
        security_opt=["no-new-privileges"],
        user=RUN_USER,
        environment=environment,
        volumes=volumes,
        labels=dict(_container_labels(spec.timeout_s), job=spec.job_id),
        detach=True,
    )


def _read_file(container, path):
    """Text of one file of a stopped container, or None."""
    try:
        stream, _ = container.get_archive(path)
        data = b"".join(stream)
        with tarfile.open(fileobj=io.BytesIO(data)) as tar:
            member = tar.next()
            handle = tar.extractfile(member) if member is not None else None
            return handle.read().decode("utf-8", "replace") if handle else None
    except Exception:
        return None


class DockerSandboxExecutor(SandboxExecutor):
    def __init__(self, client=None):
        self._client = client
        self._next_sweep = 0

    @property
    def client(self):
        if self._client is None:
            import docker   # only the sandbox worker has the socket
            self._client = docker.from_env()
        return self._client

    def reap_expired(self):
        if time.monotonic() < self._next_sweep:
            return
        self._next_sweep = time.monotonic() + 60
        try:
            containers = self.client.containers.list(all=True, filters={
                "label": ["autotest.sandbox=1", EXPIRY_LABEL]})
            for container in containers:
                expiry = container.labels.get(EXPIRY_LABEL, "")
                if expiry.isdecimal() and int(expiry) < time.time():
                    try:
                        container.remove(force=True)
                    except Exception as exc:
                        logger.warning("Could not remove expired sandbox %s: %s", container.id, exc)
        except Exception as exc:
            logger.warning("Could not list expired sandboxes: %s", exc)

    # ── volumes ─────────────────────────────────────────────────────────────
    def _new_volume(self, name, job_id):
        self.client.volumes.create(name=name, labels=dict(LABELS, job=job_id))
        return name

    def _remove_volume(self, name):
        try:
            self.client.volumes.get(name).remove(force=True)
        except Exception as exc:
            logger.warning("[SANDBOX] could not remove volume %s: %s", name, exc)

    def _fill(self, mounts, archives):
        """mounts: {volume: path}. archives: {path: tar bytes}. The loader is never started."""
        loader = self.client.containers.create(
            settings.TESTGEN_SANDBOX_IMAGE, command=["true"], network_mode="none", user="0:0",
            volumes={volume: {"bind": path, "mode": "rw"} for volume, path in mounts.items()},
            labels=_container_labels(300),
        )
        try:
            for path, data in archives.items():
                loader.put_archive(path, data)
        finally:
            loader.remove(force=True)

    # ── interface ───────────────────────────────────────────────────────────
    def prepare_source(self, job_id, files):
        volume = self._new_volume(f"sbx_{job_id}_src", job_id)
        self._fill({volume: "/workspace/src"}, {"/workspace/src": workspace.to_tar(files)})
        return volume

    def discard_source(self, volume):
        if volume:
            self._remove_volume(volume)

    def remove_volume(self, name):
        self.client.volumes.get(name).remove()

    def _environment_command(self, command, volumes, timeout, *, install=False):
        memory = settings.TESTGEN_INSTALL_MEMORY if install else settings.TESTGEN_PROBE_MEMORY
        options = dict(network_mode="bridge" if install else "none", read_only=True, user=RUN_USER,
                       cap_drop=["ALL"], security_opt=["no-new-privileges"], nano_cpus=1_000_000_000,
                       mem_limit=memory, memswap_limit=memory, pids_limit=256, labels=_container_labels(timeout),
                       tmpfs={"/tmp": "rw,size=" + (settings.TESTGEN_INSTALL_TMPFS if install else "64m")},
                       environment={"PIP_DISABLE_PIP_VERSION_CHECK": "1", "PIP_NO_CACHE_DIR": "1",
                                    "TMPDIR": "/tmp"} if install else {}, volumes=volumes, detach=True)
        container = self.client.containers.create(settings.TESTGEN_SANDBOX_IMAGE, command=command, **options)
        try:
            container.start()
            try:
                status = container.wait(timeout=timeout)["StatusCode"]
            except Exception:
                container.kill()
                status = 124
            return status, container.logs().decode("utf8", "replace")
        finally:
            container.remove(force=True)

    def install(self, request):
        from .executor import InstallOutput

        prefix = "sbx_env_" + uuid.uuid4().hex
        manifest, volume = prefix + "_manifest", prefix + "_deps"
        keep = False
        try:
            self._new_volume(manifest, request.env_key)
            self._new_volume(volume, request.env_key)
            self._fill({manifest: "/manifests"}, {"/manifests": workspace.to_tar(
                {"requirements.txt": request.requirements_text.encode()})})
            command = ["sh", "-ec", "python -m pip install --target /deps -r /manifests/requirements.txt && "
                       "printf '%s\\n' 'import site; site.addsitedir(\"/workspace/deps\")' > /deps/sitecustomize.py && "
                       "du -sb /deps"]
            status, output = self._environment_command(command, {manifest: {"bind": "/manifests", "mode": "ro"},
                volume: {"bind": "/deps", "mode": "rw"}}, request.timeout_s, install=True)
            keep = status == 0
            temporary = status == 124 or any(marker in output.lower() for marker in
                ("retrying (retry(", "timed out", "temporary failure", "connection reset", "network is unreachable"))
            missing = not temporary and "no matching distribution" in output.lower()
            size = int(output.splitlines()[-1].split()[0]) if keep else 0
            return InstallOutput(keep, volume if keep else None, status, output[-4000:], missing, temporary, size)
        except Exception as exc:
            return InstallOutput(False, output=str(exc), temporary=True)
        finally:
            self._remove_volume(manifest)
            if not keep:
                self._remove_volume(volume)

    def probe_imports(self, request):
        script = """import sys, json, importlib, site
site.addsitedir('/workspace/deps')
sys.path.insert(0, '/workspace/src')
for module in json.loads(sys.argv[1]):
    try:
        importlib.import_module(module)
        result = {'ok': True}
    except Exception as exc:
        result = {'error_type': type(exc).__name__, 'missing_name': getattr(exc, 'name', None), 'msg': str(exc)}
    print('probe:' + json.dumps([module, result]), flush=True)
"""
        volumes = {request.src_volume: {"bind": "/workspace/src", "mode": "ro"}}
        if request.env_volume:
            volumes[request.env_volume] = {"bind": "/workspace/deps", "mode": "ro"}
        _, output = self._environment_command(["python", "-I", "-c", script, json.dumps(request.modules)],
                                              volumes, settings.TESTGEN_PROBE_TIMEOUT_SECONDS)
        found = {}
        for line in output.splitlines():
            if line.startswith("probe:"):
                try:
                    module, result = json.loads(line[6:])
                    if module in request.modules and isinstance(result, dict):
                        found[module] = result
                except (TypeError, ValueError):
                    continue
        return found

    def run(self, spec):
        if spec.mode not in (RunMode.FULL, RunMode.COLLECT_ONLY):
            raise ValueError(f"run mode {spec.mode!r} is not supported in this slice")
        tests_volume, out_volume = f"{spec.run_id}_tests", f"{spec.run_id}_out"
        container, made = None, []
        started_at = time.monotonic()
        try:
            for name in (tests_volume, out_volume):
                made.append(self._new_volume(name, spec.job_id))
            # the loader also initialises <run>_out from the image, so /out belongs to the run user
            self._fill({tests_volume: "/workspace/tests", out_volume: "/out"},
                       {"/workspace/tests": workspace.to_tar(spec.test_files)})
            container = self.client.containers.create(
                **run_container_options(spec, spec.src_volume, tests_volume, out_volume))
            container.start()
        except Exception as exc:
            logger.error("[SANDBOX] run %s could not start: %s", spec.run_id, exc)
            self._clean(container, made)
            return RunOutput(run_id=spec.run_id, started=False, start_error=f"{type(exc).__name__}: {exc}",
                             options=_limits())

        timed_out, exit_code = False, None
        try:
            status = container.wait(timeout=spec.timeout_s + WAIT_MARGIN_S)
            exit_code = int(status.get("StatusCode")) if isinstance(status, dict) else None
        except Exception:
            timed_out = True                               # the worker's own guard (research R4)
            try:
                container.kill()
            except Exception:
                pass
        try:
            output = container.logs(stdout=True, stderr=True).decode("utf-8", "replace")
        except Exception:
            output = ""
        junit = _read_file(container, "/out/junit.xml")
        cov = _read_file(container, "/out/cov.json") if spec.with_coverage and spec.mode == RunMode.FULL else None
        oom_killed = False
        try:
            container.reload()
            oom_killed = bool(((container.attrs or {}).get("State") or {}).get("OOMKilled"))
        except Exception:
            pass
        duration = round(time.monotonic() - started_at, 3)
        self._clean(container, made)
        logger.info("[SANDBOX] run %s exit=%s timed_out=%s oom=%s %.2fs", spec.run_id, exit_code, timed_out,
                    oom_killed, duration)
        return RunOutput(run_id=spec.run_id, started=True, exit_code=exit_code, timed_out=timed_out,
                         junit_xml=junit, cov_json=cov, output=output, duration_s=duration,
                         options=dict(_limits(), timeout_s=spec.timeout_s), oom_killed=oom_killed)

    def _clean(self, container, volumes):
        if container is not None:
            try:
                container.remove(force=True)
            except Exception as exc:
                logger.warning("[SANDBOX] could not remove container: %s", exc)
        for name in volumes:
            self._remove_volume(name)
