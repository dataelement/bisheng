"""Runs inside an isolated preparer image, never in the manager host process."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib
from urllib.parse import unquote, urlsplit

SOURCE = Path("/workspace/app")
OUTPUT = Path("/output")
MATERIALS = Path("/materials")
WHEELS = OUTPUT / "wheels"


def run(*args, cwd=SOURCE, env=None):
    subprocess.run(list(args), cwd=cwd, env=env, check=True)


def hash_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def copy_materials():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    WHEELS.mkdir(exist_ok=True)
    for root in [Path("/opt/bisheng/wheelhouse"), MATERIALS]:
        if not root.exists():
            continue
        for wheel in root.rglob("*.whl"):
            target = WHEELS / wheel.name
            if target.exists() and hash_file(target) != hash_file(wheel):
                raise RuntimeError("wheel_filename_content_conflict")
            shutil.copyfile(wheel, target)
    # Offline npm caches are immutable materials, not a global npmrc or login state.
    for root in [
        MATERIALS,
        *([x for x in MATERIALS.iterdir() if x.is_dir()] if MATERIALS.exists() else []),
    ]:
        cached = root / "npm"
        if cached.exists():
            shutil.copytree(cached, OUTPUT / "npm", dirs_exist_ok=True, symlinks=True)


def node_projects():
    return [
        path
        for path in [SOURCE, SOURCE / "frontend"]
        if (path / "package.json").is_file()
    ]


def requirements():
    declared = os.environ.get("BISHENG_DEPENDENCY_LOCK", "")
    if declared:
        path = (SOURCE / declared).resolve()
        if not path.is_relative_to(SOURCE):
            raise RuntimeError("dependency_lock_path_escape")
        if not path.is_file():
            raise RuntimeError("declared_dependency_lock_missing")
        return path
    if (SOURCE / "uv.lock").is_file():
        out = OUTPUT / "uv-requirements.txt"
        run(
            "uv",
            "export",
            "--frozen",
            "--no-dev",
            "--no-emit-project",
            "--format",
            "requirements-txt",
            "--output-file",
            str(out),
        )
        return out
    return SOURCE / "requirements.txt"


def requirement_lines(path, seen=None, *, constraint=False):
    """Resolve includes without allowing pip options, URL metadata or escaped source files."""
    try:
        from pip._vendor.packaging.requirements import Requirement
    except ModuleNotFoundError:
        from packaging.requirements import Requirement

    seen = set() if seen is None else seen
    path = Path(path).resolve()
    if path in seen or len(seen) > 64:
        raise RuntimeError("requirement_include_cycle_or_limit")
    seen.add(path)
    text = path.read_text().replace("\\\n", " ")
    output = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        line = re.split(r"\s+#", line, maxsplit=1)[0].strip()
        directive = re.fullmatch(
            r"(-r|--requirement|-c|--constraint)(?:=|\s+)(.+)", line
        )
        if directive:
            parts = shlex.split(directive.group(2))
            if len(parts) != 1:
                raise RuntimeError("requirement_include_invalid")
            child = (path.parent / parts[0]).resolve()
            if not child.is_relative_to(SOURCE.resolve()):
                raise RuntimeError("requirement_include_escape")
            nested = requirement_lines(
                child,
                seen.copy(),
                constraint=constraint or directive.group(1) in {"-c", "--constraint"},
            )
            output.extend(nested)
            continue
        if line in {".", "-e .", "--editable ."}:
            if constraint:
                raise RuntimeError("local_constraint_refused")
            continue
        clean = re.sub(r"\s+--hash=sha256:[0-9a-fA-F]{64}", "", line)
        try:
            parsed = Requirement(clean)
        except Exception as exc:
            raise RuntimeError("requirement_option_or_source_refused") from exc
        if parsed.url:
            raise RuntimeError("direct_dependency_url_refused_supply_offline_wheel")
        output.append((line, constraint))
    return output


def safe_requirements(path, output):
    lines = requirement_lines(path)
    constraints = OUTPUT / (Path(output).name + ".constraints")
    constraints.write_text(
        "\n".join(line for line, constraint in lines if constraint) + "\n"
    )
    result = [line for line, constraint in lines if not constraint]
    if any(constraint for _, constraint in lines):
        result += ["-c " + str(constraints)]
    Path(output).write_text("\n".join(result) + "\n")
    return Path(output)


def validate_node_sources(project):
    document = json.loads((project / "package.json").read_text())
    candidates = []
    for key in ["dependencies", "devDependencies", "optionalDependencies"]:
        candidates.extend(document.get(key, {}).values())
    lock = project / "package-lock.json"
    if lock.is_file():
        candidates.extend(
            item.get("resolved", "")
            for item in json.loads(lock.read_text()).get("packages", {}).values()
        )
    for value in candidates:
        if not isinstance(value, str):
            raise RuntimeError("node_dependency_invalid")
        if value.startswith(
            ("git", "ssh:", "file:", "link:", "github:", "gitlab:", "bitbucket:")
        ) or re.match(r"^[^@ :/]+/[^ :/]+$", value):
            raise RuntimeError("node_non_registry_dependency_refused")
        if "://" in value:
            url = urlsplit(value)
            if url.scheme not in {"http", "https"} or url.username or url.password:
                raise RuntimeError("node_dependency_url_refused")


def download(language):
    copy_materials()
    if language == "python3.11":
        req = requirements()
        if req.is_file():
            # Only wheels are resolved online: no untrusted sdist hooks receive registry credentials.
            target = safe_requirements(req, OUTPUT / "download.in")
            run(
                "python",
                "-m",
                "pip",
                "download",
                "--only-binary=:all:",
                "--dest",
                str(WHEELS),
                "--find-links",
                str(WHEELS),
                "-r",
                str(target),
            )
        project = SOURCE / "pyproject.toml"
        if project.is_file():
            metadata = tomllib.loads(project.read_text())
            build = metadata.get("build-system", {}).get("requires", [])
            dependencies = metadata.get("project", {}).get("dependencies", [])
            if build or dependencies:
                from pip._vendor.packaging.requirements import Requirement

                if any(Requirement(item).url for item in [*build, *dependencies]):
                    raise RuntimeError(
                        "direct_dependency_url_refused_supply_offline_wheel"
                    )
                run(
                    "python",
                    "-m",
                    "pip",
                    "download",
                    "--only-binary=:all:",
                    "--dest",
                    str(WHEELS),
                    "--find-links",
                    str(WHEELS),
                    *build,
                    *dependencies,
                )
    for project in node_projects():
        validate_node_sources(project)
        code = "root" if project == SOURCE else "frontend"
        root = OUTPUT / "npm" / code
        root.mkdir(parents=True, exist_ok=True)
        if not (project / "package-lock.json").exists():
            run(
                "npm",
                "install",
                "--package-lock-only",
                "--ignore-scripts",
                "--cache",
                str(root / "cache"),
                cwd=project,
            )
        run(
            "npm", "ci", "--ignore-scripts", "--cache", str(root / "cache"), cwd=project
        )
        shutil.copyfile(project / "package-lock.json", root / "package-lock.json")


def lock_python():
    req = requirements()
    inputs = []
    if req.is_file():
        inputs = safe_requirements(req, OUTPUT / "install.in").read_text().splitlines()
    project = SOURCE / "pyproject.toml"
    has_project = project.exists() and "project" in tomllib.loads(project.read_text())
    local = any(line.strip().startswith(("-e ", ".", "file:")) for line in inputs)
    if has_project or local or (SOURCE / "setup.py").exists():
        before = set(WHEELS.glob("*.whl"))
        run(
            "python",
            "-m",
            "pip",
            "wheel",
            "--no-index",
            "--find-links",
            str(WHEELS),
            "--wheel-dir",
            str(WHEELS),
            "--no-deps",
            str(SOURCE),
        )
        built = list(set(WHEELS.glob("*.whl")) - before)
        if len(built) != 1:
            raise RuntimeError("project_wheel_ambiguous")
        inputs = [
            line
            for line in inputs
            if not line.strip().startswith(("-e ", ".", "file:"))
        ] + [str(built[0])]
    effective = OUTPUT / "requirements.in"
    effective.write_text("\n".join(inputs) + "\n")
    report = OUTPUT / "resolution.json"
    run(
        "python",
        "-m",
        "pip",
        "install",
        "--dry-run",
        "--ignore-installed",
        "--no-index",
        "--find-links",
        str(WHEELS),
        "--report",
        str(report),
        "-r",
        str(effective),
    )
    frozen = []
    for entry in json.loads(report.read_text()).get("install", []):
        source = urlsplit(entry["download_info"]["url"])
        file = Path(unquote(source.path)).resolve()
        if (
            source.scheme != "file"
            or not file.is_relative_to(WHEELS.resolve())
            or file.suffix != ".whl"
        ):
            raise RuntimeError("non_wheel_resolution_refused")
        frozen.append(
            f"{entry['metadata']['name']}=={entry['metadata']['version']} --hash=sha256:{hash_file(file)}"
        )
    (OUTPUT / "runtime.lock").write_text("\n".join(sorted(frozen)) + "\n")


def lock(language):
    copy_materials()
    original = Path("/original")
    baseline = {
        file.relative_to(original).as_posix(): hash_file(file)
        for file in original.rglob("*")
        if file.is_file()
        and not file.is_symlink()
        and "node_modules" not in file.relative_to(original).parts
    }
    os.environ.update(
        {
            "PIP_NO_INDEX": "1",
            "PIP_FIND_LINKS": str(WHEELS),
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PIP_NO_CACHE_DIR": "1",
            "npm_config_offline": "true",
            "npm_config_nodedir": "/usr/local",
        }
    )
    # Explicit offline source archives may be compiled, with their build dependencies supplied as wheels.
    if language == "python3.11":
        for source in MATERIALS.rglob("*.tar.gz"):
            run(
                "python",
                "-m",
                "pip",
                "wheel",
                "--no-index",
                "--find-links",
                str(WHEELS),
                "--wheel-dir",
                str(WHEELS),
                "--no-deps",
                str(source),
            )
        lock_python()
    else:
        (OUTPUT / "runtime.lock").write_text("")
    for project in node_projects():
        validate_node_sources(project)
        code = "root" if project == SOURCE else "frontend"
        root = OUTPUT / "npm" / code
        root.mkdir(parents=True, exist_ok=True)
        if (
            not (project / "package-lock.json").exists()
            and (root / "package-lock.json").exists()
        ):
            shutil.copyfile(root / "package-lock.json", project / "package-lock.json")
        if not (project / "package-lock.json").exists():
            package = json.loads((project / "package.json").read_text())
            if any(
                package.get(key)
                for key in ["dependencies", "devDependencies", "optionalDependencies"]
            ):
                raise RuntimeError("offline_package_lock_missing")
            run(
                "npm",
                "install",
                "--package-lock-only",
                "--offline",
                "--ignore-scripts",
                "--cache",
                str(root / "cache"),
                cwd=project,
            )
        run("npm", "ci", "--offline", "--cache", str(root / "cache"), cwd=project)
        shutil.copyfile(project / "package-lock.json", root / "package-lock.json")
        if (root / "node_modules").exists():
            shutil.rmtree(root / "node_modules")
        if (project / "node_modules").exists():
            shutil.copytree(
                project / "node_modules", root / "node_modules", symlinks=True
            )
        else:
            (root / "node_modules").mkdir()
        shutil.rmtree(root / "cache" / "_logs", ignore_errors=True)
    after = {
        file.relative_to(SOURCE).as_posix(): hash_file(file)
        for file in SOURCE.rglob("*")
        if file.is_file()
        and not file.is_symlink()
        and "node_modules" not in file.relative_to(SOURCE).parts
    }
    for name, digest in after.items():
        if baseline.get(name) != digest:
            target = OUTPUT / "install-overlay" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(SOURCE / name, target)
    (OUTPUT / "install-deleted.json").write_text(
        json.dumps(sorted(set(baseline) - set(after)))
    )
    manifest = {"format": 1, "files": {}}
    for file in sorted(OUTPUT.rglob("*")):
        if file.is_file() and not file.is_symlink():
            manifest["files"][file.relative_to(OUTPUT).as_posix()] = {
                "sha256": hash_file(file),
                "size": file.stat().st_size,
            }
    (OUTPUT / "materials.json").write_text(json.dumps(manifest, sort_keys=True))


def build(_language):
    os.environ.update(
        {
            "npm_config_offline": "true",
            "PIP_NO_INDEX": "1",
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        }
    )
    for project in node_projects():
        validate_node_sources(project)
        code = "root" if project == SOURCE else "frontend"
        saved = MATERIALS / "npm" / code
        if (saved / "package-lock.json").exists():
            shutil.copyfile(saved / "package-lock.json", project / "package-lock.json")
        if (project / "node_modules").exists():
            shutil.rmtree(project / "node_modules")
        if (saved / "node_modules").exists():
            shutil.copytree(
                saved / "node_modules", project / "node_modules", symlinks=True
            )
        scripts = json.loads((project / "package.json").read_text()).get("scripts", {})
        if scripts.get("build"):
            run("npm", "run", "build", cwd=project)


if __name__ == "__main__":
    functions = {"download": download, "lock": lock, "build": build}
    functions[sys.argv[1]](sys.argv[2])
