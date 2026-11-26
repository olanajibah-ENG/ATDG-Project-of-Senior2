import ast
import configparser
import hashlib
import json
import sys
import uuid
from datetime import datetime
from pathlib import PurePosixPath

from django.conf import settings

from .generation import progress_from_records
from .runner import PassResult
from .sandbox.executor import InstallRequest, ProbeRequest
from .sandbox.workspace import version_files
from .statuses import Actor, JobStage, JobStatus, RecordStatus


def required_imports(files):
    modules = {p[:-3].replace("/", ".").removesuffix(".__init__"): p for p in files if p.endswith(".py")}
    dependencies, local = {}, {}
    for module, path in modules.items():
        dependencies[path], local[path] = set(), set()
        try:
            tree = ast.parse(files[path])
        except (SyntaxError, ValueError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                prefix = node.module or ""
                if node.level:
                    package = module.split(".") if path.endswith("/__init__.py") else module.split(".")[:-1]
                    prefix = ".".join(package[:len(package) - node.level + 1] + ([prefix] if prefix else []))
                names = [prefix] + [prefix + "." + a.name for a in node.names if prefix + "." + a.name in modules]
            else:
                continue
            for name in names:
                root = name.split(".")[0]
                local_key = name if name in modules else next(
                    (m for m in modules if m == root or m.endswith("." + root)),
                    None,
                )
                if local_key is not None:
                    local[path].add(modules[local_key])
                elif root and root not in sys.stdlib_module_names and root != "pytest":
                    dependencies[path].add(root)
    changed = True
    while changed:
        changed = False
        for path, edges in local.items():
            inherited = set().union(*(dependencies[e] for e in edges))
            if inherited - dependencies[path]:
                dependencies[path].update(inherited)
                changed = True
    return dependencies


def run_preflight_pass(job_id, *, jobs, records, envs, executor, reader, adapter):
    job = jobs.get(job_id)
    files = version_files(reader, job)
    state = dict(job.get("preflight") or {})
    state.setdefault("install_tries", 0)
    try:
        text, warnings = adapter.install_spec(files)
    except (ValueError, configparser.Error) as exc:
        text, warnings = None, [str(exc)]
        state["failure"] = ("install_failed", str(exc))
    state["warnings"] = warnings
    volume = None
    outcome = "skipped"
    if text:
        manifests = {p: hashlib.sha256(v).hexdigest() for p, v in files.items()
                     if PurePosixPath(p).suffix in {".toml", ".cfg", ".txt"}}
        key = hashlib.sha256(json.dumps([settings.TESTGEN_SANDBOX_IMAGE, manifests], sort_keys=True).encode()).hexdigest()
        state["env_key"] = key
        cached = envs.get(key)
        age = (datetime.utcnow() - cached["updated_at"]).total_seconds() if cached else 0
        if cached and cached["status"] == "ready":
            outcome = "reused"
            if not envs.touch(key):
                return PassResult(done=False, countdown=10)
            volume = cached["volume"]
        elif cached and cached["status"] == "failed" and age < settings.TESTGEN_ENV_FAILED_TTL_SECONDS:
            state["failure"] = cached["failure"]
        else:
            owner = job_id + ":" + uuid.uuid4().hex
            if (cached and (cached["status"] == "reaping" or cached["status"] == "building" and age < settings.TESTGEN_ENV_LOCK_STALE_SECONDS)
                    or not envs.claim(key, owner, cached)):
                return PassResult(done=False, countdown=10)
            state["install_tries"] += 1
            result = executor.install(InstallRequest(key, text, settings.TESTGEN_INSTALL_TIMEOUT_SECONDS))
            if result.ok:
                outcome = "installed"
                volume = result.volume
                if not envs.finish(key, owner, status="ready", volume=volume, manifests=manifests,
                                   python_version="3.10", size_bytes=result.size_bytes):
                    executor.remove_volume(volume)
                    return PassResult(done=False, countdown=10)
            else:
                failure = ["missing_dependency" if result.missing else "install_failed", result.output]
                if not envs.finish(key, owner, status="failed_temporary" if result.temporary else "failed",
                                   failure=failure, detail=result.output, manifests=manifests, python_version="3.10"):
                    return PassResult(done=False, countdown=10)
                if result.temporary and state["install_tries"] < 2:
                    jobs.update(job_id, {"preflight": state})
                    return PassResult(done=False, countdown=30)
                state["failure"] = failure
    state["volume"] = volume
    deps = required_imports(files)
    modules = sorted(set().union(*deps.values()))
    probe = {}
    if modules and not state.get("failure"):
        src = None
        try:
            src = executor.prepare_source(job_id + "_probe", files)
            probe = executor.probe_imports(ProbeRequest(src, volume, modules))
        except Exception as exc:
            warnings.append(str(exc))
        finally:
            if src:
                executor.discard_source(src)
        if set(probe) != set(modules):
            warnings.append("import probe incomplete")
    missing_modules = sorted(n for n, info in probe.items() if info.get("error_type") == "ModuleNotFoundError"
                             and info.get("missing_name") == n)
    state["probe"] = dict(modules=modules, missing=missing_modules, not_probed=sorted(set(modules) - set(probe)),
                          import_failed=[{"module": n, "error": info.get("msg")} for n, info in probe.items()
                                         if info.get("error_type") and n not in missing_modules])
    state["detail"] = (state.get("failure") or [None, None])[1]
    for record in records.list(job_id, status=RecordStatus.PENDING):
        failure = state.get("failure")
        for name in sorted(deps.get(record["file"], ())):
            info = probe.get(name, {})
            if info.get("error_type"):
                missing = info["error_type"] == "ModuleNotFoundError" and info.get("missing_name") == name
                failure = ("missing_dependency" if missing else "import_failed", name if missing else info.get("msg"))
                break
        if failure:
            records.transition(record["record_id"], RecordStatus.ENVIRONMENT_ERROR, Actor.PREFLIGHT,
                               {"reason_code": failure[0], "reason_detail": failure[1]})
    failed = not records.next_pending(job_id, "unit")
    state["status"] = "failed" if failed else outcome
    error = None
    if failed:
        first = records.list(job_id, status=RecordStatus.ENVIRONMENT_ERROR)[0]
        error = {"code": first["reason_code"], "message": first["reason_detail"]}
    jobs.update(job_id, {"preflight": state, "status": JobStatus.FAILED if failed else JobStatus.RUNNING,
                         "error": error,
                         "stage": JobStage.PREFLIGHT if failed else JobStage.GENERATING,
                         "progress": progress_from_records(records.counts(job_id), job["plan"]),
                         "notices": ["preflight_warnings"] if warnings else []})
    return PassResult(done=True, handover=not failed)
