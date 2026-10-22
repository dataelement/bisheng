"""Append fixed filesystem outputs to an immutable image without executing them."""

from __future__ import annotations

import csv
import io
import json
import os
import re
import stat
import subprocess
import tarfile
import time
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, uuid5

from runtime_manager.builder import render_build_context
from runtime_manager.executors.protocol import ExecutorError
from runtime_manager.source_facts import STATIC_ROOT_CANDIDATES

_IMAGE = re.compile(r"[A-Za-z0-9][A-Za-z0-9./:_-]*@sha256:[a-f0-9]{64}")
_REPOSITORY_PART = re.compile(r"[a-z0-9]+(?:(?:[._]|__|-+)[a-z0-9]+)*")
_TAG = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}")
_HOST = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?")
_DOCKER_HUB = {"docker.io", "index.docker.io", "registry-1.docker.io"}
_PYTHON_LINKS = {"/usr/local/bin/python", "/usr/local/bin/python3", "/usr/local/bin/python3.11"}


def _origin(value):
    try:
        if not isinstance(value, str) or any(character in value for character in "\\\r\n\t %"):
            raise ValueError()
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        port = parsed.port if parsed.port is not None else (80 if parsed.scheme == "http" else 443)
        if (
            parsed.scheme not in {"http", "https"}
            or not _HOST.fullmatch(host)
            or ".." in host
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
            or parsed.netloc.endswith(":")
            or not 1 <= port <= 65535
        ):
            raise ValueError()
        return f"{parsed.scheme}://{host.lower()}:{port}"
    except (ValueError, TypeError):
        raise ExecutorError("oci_registry_endpoint_invalid") from None


def _repository(value):
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 255
        or any(character in value for character in "@?#\\\r\n\t %")
    ):
        raise ExecutorError("oci_registry_invalid")
    parts = value.split("/")
    explicit = len(parts) > 1 and ("." in parts[0] or ":" in parts[0] or parts[0] == "localhost")
    authority, names = (parts[0], parts[1:]) if explicit else ("index.docker.io", parts)
    try:
        parsed = urlsplit("https://" + authority)
        if not parsed.hostname or parsed.path or parsed.username is not None or parsed.password is not None:
            raise ValueError()
        port = parsed.port
        if port is not None and not 1 <= port <= 65535:
            raise ValueError()
        if not _HOST.fullmatch(parsed.hostname) or ".." in parsed.hostname:
            raise ValueError()
    except ValueError:
        raise ExecutorError("oci_registry_invalid") from None
    if not names or any(not _REPOSITORY_PART.fullmatch(part) for part in names):
        raise ExecutorError("oci_registry_invalid")
    host = parsed.hostname.lower()
    if host in _DOCKER_HUB and port is None:
        authority = "index.docker.io"
        if len(names) == 1:
            names.insert(0, "library")
    else:
        authority = host + (f":{port}" if port is not None else "")
    return authority + "/" + "/".join(names), authority


def _frozen_image(value):
    if not isinstance(value, str) or not _IMAGE.fullmatch(value):
        raise ExecutorError("oci_frozen_base_invalid")
    name, digest = value.rsplit("@", 1)
    last = name.rsplit("/", 1)[-1]
    if ":" in last:
        name, tag = name.rsplit(":", 1)
        if not _TAG.fullmatch(tag):
            raise ExecutorError("oci_frozen_base_invalid")
    try:
        repository, authority = _repository(name)
    except ExecutorError:
        raise ExecutorError("oci_frozen_base_invalid") from None
    return repository + "@" + digest, authority


def registry_origins(base, repository, *, endpoints=(), insecure=False):
    """Only exact registry, required Hub auth, and installer-declared origins."""
    _canonical_target, target = _repository(repository)
    _canonical_base, source = _frozen_image(base)
    if not isinstance(endpoints, (list, tuple)) or len(endpoints) > 32:
        raise ExecutorError("oci_registry_endpoint_invalid")
    origins = {_origin(value) for value in endpoints}
    for authority in {target, source}:
        scheme = "http" if insecure and authority == target else "https"
        if authority == "index.docker.io":
            origins.add(_origin(scheme + "://registry-1.docker.io"))
            origins.add("https://auth.docker.io:443")
        else:
            origins.add(_origin(scheme + "://" + authority))
    return sorted(origins)


def write_layer(document, source, environment, destination):
    source, environment = Path(source), Path(environment)
    language = document["runtime"]
    profile = document["profile"]
    if language not in {"python3.11", "node20", "static"}:
        raise ExecutorError("oci_runtime_invalid")
    uid, gid = profile.get("uid", 10001), profile.get("gid", 10001)
    if any(type(value) is not int or value <= 0 for value in (uid, gid)):
        raise ExecutorError("oci_identity_invalid")
    if source.is_symlink() or not source.is_dir() or environment.is_symlink():
        raise ExecutorError("oci_input_link_refused")
    code = source
    prefix = "app"
    if language == "static":
        code = next(
            (source / part for part in STATIC_ROOT_CANDIDATES if (source / part / "index.html").is_file()),
            None,
        )
        if code is None or code.is_symlink():
            raise ExecutorError("oci_static_entry_missing")
        prefix = "app/www"
    templates = render_build_context(
        language,
        {"port": document["port"], "static_root": ".", "node": {"install": "none", "build": False, "lockfiles": []}},
    )
    count = total = 0
    with tarfile.open(destination, "w", format=tarfile.PAX_FORMAT) as archive:
        for root, target in [(code, prefix), *([(environment, "opt/venv")] if language == "python3.11" else [])]:
            if not root.is_dir():
                raise ExecutorError("oci_environment_missing")
            for path in sorted(root.rglob("*")):
                relative = path.relative_to(root)
                if any(part.startswith(".wh.") for part in relative.parts):
                    raise ExecutorError("oci_whiteout_refused")
                metadata = path.lstat()
                # fsGroup makes volume directories inherit SGID; the layer drops it.
                if metadata.st_mode & stat.S_ISUID or (
                    metadata.st_mode & stat.S_ISGID and not stat.S_ISDIR(metadata.st_mode)
                ):
                    raise ExecutorError("oci_privilege_bits_refused")
                count += 1
                total += metadata.st_size if stat.S_ISREG(metadata.st_mode) else 0
                if count > 200000 or total > 8 * 1024**3:
                    raise ExecutorError("oci_layer_limit")
                info = tarfile.TarInfo(target + "/" + relative.as_posix())
                info.uid, info.gid, info.mode, info.mtime = uid, gid, stat.S_IMODE(metadata.st_mode) & 0o777, 0
                if stat.S_ISLNK(metadata.st_mode):
                    link = os.readlink(path)
                    internal = not Path(link).is_absolute() and path.resolve().is_relative_to(root.resolve())
                    trusted_python = (
                        root == environment
                        and relative.parts[0] == "bin"
                        and relative.name in {"python", "python3", "python3.11"}
                        and (link in _PYTHON_LINKS or str(path.resolve()) in _PYTHON_LINKS)
                    )
                    if not (internal or trusted_python):
                        raise ExecutorError("oci_external_link_refused")
                    info.type, info.linkname = tarfile.SYMTYPE, link
                    archive.addfile(info)
                elif stat.S_ISDIR(metadata.st_mode):
                    info.type = tarfile.DIRTYPE
                    archive.addfile(info)
                elif stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1:
                    info.size = metadata.st_size
                    with path.open("rb") as content:
                        archive.addfile(info, content)
                else:
                    raise ExecutorError("oci_special_or_hardlink_refused")
        files = {"usr/local/bin/bisheng-app-entrypoint": (templates["entrypoint.sh"], 0o755)}
        if language == "static":
            files["etc/bisheng/nginx.conf.tmpl"] = (templates["nginx.conf"], 0o644)
        for name, (content, mode) in files.items():
            raw = content.encode()
            info = tarfile.TarInfo(name)
            info.uid, info.gid, info.mode, info.mtime, info.size = uid, gid, mode, 0, len(raw)
            archive.addfile(info, io.BytesIO(raw))
    return Path(destination)


def assemble_image(document, source, environment, target, *, work, run=subprocess.run, timeout=1800):
    if not isinstance(target, str) or ":" not in target.rsplit("/", 1)[-1]:
        raise ExecutorError("oci_registry_required")
    raw_repository, tag = target.rsplit(":", 1)
    repository, target_registry = _repository(raw_repository)
    if not _TAG.fullmatch(tag):
        raise ExecutorError("oci_registry_invalid")
    base = document["profile"].get("runtime_image", "")
    _canonical_base, base_registry = _frozen_image(base)
    platform = document["platform"]
    if platform not in {"linux/amd64", "linux/arm64"}:
        raise ExecutorError("oci_frozen_base_invalid")
    layer = write_layer(document, source, environment, Path(work) / "application-layer.tar")
    command = ["crane", "--platform", platform]
    insecure = document.get("insecure_registry") is True
    if insecure and base_registry == target_registry:
        command.append("--insecure")
    output = Path(work) / "assembled-image.tar"
    deadline = time.monotonic() + timeout

    def execute(arguments):
        try:
            result = run(
                arguments, check=True, capture_output=True, text=True, timeout=max(0.001, deadline - time.monotonic())
            )
            if len(result.stdout) > 1024 * 1024:
                raise ValueError()
            return result.stdout
        except (OSError, ValueError, subprocess.SubprocessError):
            raise ExecutorError("oci_registry_operation_failed") from None

    try:
        config = json.loads(execute([*command, "config", base]))
        if (config.get("os"), config.get("architecture")) != tuple(platform.split("/")):
            raise ExecutorError("oci_base_platform_mismatch")
        arguments = [
            *command,
            "mutate",
            base,
            "--append",
            str(layer),
            "--entrypoint",
            "/usr/local/bin/bisheng-app-entrypoint",
            "--user",
            f"{document['profile'].get('uid', 10001)}:{document['profile'].get('gid', 10001)}",
            "--workdir",
            "/app",
            "--env",
            "PATH=/opt/venv/bin:/app/node_modules/.bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "--tag",
            target,
        ]
        startup = document.get("startup", {}).get("command") or []
        if not isinstance(startup, list) or any(
            not isinstance(part, str) or not part or "\x00" in part for part in startup
        ):
            raise ExecutorError("oci_startup_invalid")
        # Empty CMD lets the platform entrypoint resolve the application's startup.
        encoded = io.StringIO()
        csv.writer(encoded, lineterminator="").writerow(startup)
        arguments += ["--cmd", encoded.getvalue()]
        if insecure and base_registry != target_registry:
            # crane's global --insecure affects every remote access. Keep the
            # foreign base HTTPS-only, then push the local result to this target.
            arguments += ["--output", str(output)]
            execute(arguments)
            reference = execute(["crane", "--platform", platform, "--insecure", "push", str(output), target]).strip()
        else:
            reference = execute(arguments).strip()
        try:
            canonical_result, _registry = _frozen_image(reference)
        except ExecutorError:
            raise ExecutorError("oci_push_digest_unconfirmed") from None
        if canonical_result.split("@")[0] != repository:
            raise ExecutorError("oci_push_digest_unconfirmed")
        return {
            "mode": "source-image",
            "image_ref": reference,
            "platform": platform,
            "profile": document["profile"],
            "runtime": document["runtime"],
            "startup": {},
        }
    finally:
        layer.unlink(missing_ok=True)
        output.unlink(missing_ok=True)


class KubernetesAssembler:
    def __init__(self, runtime):
        self.runtime = runtime

    def prepare(self, operation, delivery):
        runtime = self.runtime
        report = runtime.probe_report()
        if report.get("ready") is not True or report.get("paths", {}).get("source-image") is not True:
            raise ExecutorError("oci_source_image_unavailable")
        repository = runtime.document.get("image_repository", "")
        _repository(repository)
        image = runtime.document.get("assembler_image", "")
        try:
            _frozen_image(image)
        except ExecutorError:
            raise ExecutorError("oci_assembler_image_required") from None
        sources = registry_origins(
            operation["payload"]["profile"].get("runtime_image", ""),
            repository,
            endpoints=runtime.document.get("image_registry_endpoints", []),
            insecure=runtime.document.get("insecure_registry") is True,
        )
        reference = str(uuid5(NAMESPACE_URL, "bisheng-assemble:" + operation["operation_id"]))
        document = {
            "profile": operation["payload"]["profile"],
            "platform": runtime.descriptor.platform,
            "runtime": operation["payload"]["profile"]["language"],
            "port": operation["payload"].get("port", 8080),
            "startup": operation["payload"].get("delivery", {}).get("startup", {}),
            "target": repository + ":operation-" + operation["operation_id"],
            "insecure_registry": runtime.document.get("insecure_registry") is True,
        }
        plan = runtime._plan(operation, "assemble", reference=reference, image=image)
        environment = {
            "ASSEMBLY_PLAN": json.dumps(document, sort_keys=True, separators=(",", ":")),
            "DOCKER_CONFIG": "/run/registry",
        }
        if runtime.config.egress_enabled:
            from runtime_manager.egress import egress_env

            credentials = runtime.platform.egress(
                operation["operation_id"],
                "build",
                package_sources=sources,
            )
            environment.update(egress_env(runtime.config, **credentials))
        plan = replace(
            plan,
            mode="image",
            app_secret="",
            secret_env=(),
            material_secret="",
            registry_secret=runtime.document.get("registry_secret", ""),
            helper_env=environment,
            command=("python", "-I", "-m", "runtime_manager.oci_assembler"),
        )
        return runtime._phase(operation, "assemble", "assemble", document, plan=plan, result_container="assembler")


def main():
    document = json.loads(os.environ["ASSEMBLY_PLAN"])
    result = assemble_image(
        document, Path("/work/source"), Path("/work/environment"), document["target"], work=Path("/tmp")
    )
    print("BISHENG_RUNTIME_RESULT " + json.dumps(result, sort_keys=True, separators=(",", ":")), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(
            "OCI assembly failed: " + (str(exc) if isinstance(exc, ExecutorError) else type(exc).__name__), flush=True
        )
        raise SystemExit(1) from None
