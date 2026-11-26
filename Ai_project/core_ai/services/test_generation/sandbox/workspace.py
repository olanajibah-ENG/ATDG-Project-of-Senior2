"""What goes into a run: the version's files and the test files, as {path: bytes} and as tar archives.

Nothing but project files and tests ever goes in: no setting, no environment value, no secret.
"""
import io
import tarfile
import time

RUN_UID = 10001
# Per-test timeout (signal method keeps junit.xml) and no network; unix sockets stay for asyncio.
PYTEST_INI = (b"[pytest]\naddopts = -p no:cacheprovider --timeout=30 --timeout-method=signal "
              b"--disable-socket --allow-unix-socket\n")


def version_files(reader, job):
    """The job's version, as the plan read it: one file per path, deleted files left out.

    Every file of the version is included (not only the selected paths), because a test may import
    any module of the project.
    """
    files = {}
    for entry in reader.files_of_version(job["project_id"], job["version_number"]):
        content = reader.content_of(entry["file_id"])
        if content is None:
            continue
        path = str(entry["path"]).replace("\\", "/").lstrip("/")
        files[path] = content.encode("utf-8") if isinstance(content, str) else content
    return files


def tests_dir_path(test_path):
    """`tests/generated/x.py` (path under /workspace) → `generated/x.py` (path in the tests volume)."""
    path = str(test_path).replace("\\", "/")
    return path[len("tests/"):] if path.startswith("tests/") else path


def record_test_files(records):
    """The test files of the given records, plus the runner config, keyed by path in the tests volume."""
    from django.conf import settings
    files = {"pytest.ini": PYTEST_INI.replace(b"--timeout=30", f"--timeout={settings.TESTGEN_PER_TEST_TIMEOUT_SECONDS}".encode())}
    for record in records:
        files[tests_dir_path(record["test_path"])] = (record.get("test_code") or "").encode("utf-8")
    return files


def to_tar(files, uid=RUN_UID, mode=0o644, extra_dirs=()):
    """In-memory tar of {path: bytes}; every member owned by the run user."""
    buffer = io.BytesIO()
    now = int(time.time())
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        dirs = set(extra_dirs)
        for path in files:
            parts = path.split("/")[:-1]
            dirs.update("/".join(parts[:i]) for i in range(1, len(parts) + 1))
        for directory in sorted(d for d in dirs if d):
            info = tarfile.TarInfo(directory)
            info.type, info.mode, info.uid, info.gid, info.mtime = tarfile.DIRTYPE, 0o755, uid, uid, now
            tar.addfile(info)
        for path, content in sorted(files.items()):
            info = tarfile.TarInfo(path)
            info.size, info.mode, info.uid, info.gid, info.mtime = len(content), mode, uid, uid, now
            tar.addfile(info, io.BytesIO(content))
    return buffer.getvalue()
