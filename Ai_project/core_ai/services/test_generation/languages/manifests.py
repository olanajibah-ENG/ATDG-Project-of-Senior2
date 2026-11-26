import configparser
import posixpath
import re
from pathlib import PurePosixPath


from packaging.requirements import InvalidRequirement, Requirement


def install_spec(files):
    # ZIP uploads often carry one enclosing project directory.
    roots = {p.partition("/")[0] for p in files}
    if len(roots) == 1 and "requirements" not in roots and all("/" in p for p in files):
        files = {p.partition("/")[2]: content for p, content in files.items()}
    excluded = set("dev develop development doc docs test tests testing lint prod production local staging ci".split())
    paths = sorted(p for p in files if p.endswith(".txt") and (
        PurePosixPath(p).name.startswith("requirements") or "requirements" in PurePosixPath(p).parts[:-1]))
    defaults = ["requirements.txt"] + ["requirements/" + n + ".txt" for n in ("base", "common", "requirements", "main")]
    first = next((p for p in defaults if p in paths), None)
    selected = [first] if first else [p for p in paths if not excluded.intersection(re.split("[-_.]", PurePosixPath(p).name))]
    warnings, dependencies, visited = [], [], set()

    def read(path):
        value = files[path]
        return value.decode("utf-8-sig") if isinstance(value, bytes) else value

    def add(line):
        line = line.partition("#")[0].strip()
        if not line:
            return
        try:
            req = Requirement(line)
        except InvalidRequirement:
            warnings.append("ignored requirement: " + line)
            return
        if req.url:
            warnings.append("ignored direct URL: " + req.name)
        elif line not in dependencies:
            dependencies.append(line)

    def visit(path):
        if path in visited:
            return
        visited.add(path)
        for line in read(path).splitlines():
            include = re.fullmatch(r"-r\s*(\S+)", line.strip())
            if include:
                target = posixpath.normpath(posixpath.join(posixpath.dirname(path), include[1]))
                if target in paths and not excluded.intersection(re.split("[-_.]", PurePosixPath(target).name)):
                    visit(target)
                else:
                    warnings.append("ignored include: " + target)
            else:
                add(line)

    for path in selected:
        visit(path)
    warnings.extend("ignored manifest: " + p for p in paths if p not in visited)
    if "pyproject.toml" in files:
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib
        deps = tomllib.loads(read("pyproject.toml")).get("project", {}).get("dependencies", [])
        if not isinstance(deps, list) or any(not isinstance(req, str) for req in deps):
            raise ValueError("project.dependencies must be a list of strings")
        for req in deps:
            add(req)
    if "setup.cfg" in files:
        config = configparser.ConfigParser(interpolation=None)
        config.read_string(read("setup.cfg"))
        for req in config.get("options", "install_requires", fallback="").splitlines():
            add(req)
    return "\n".join(dependencies) or None, warnings
