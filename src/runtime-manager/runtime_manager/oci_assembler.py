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
from uuid import NAMESPACE_URL, uuid5

from runtime_manager.builder import render_build_context
from runtime_manager.executors.protocol import ExecutorError

_IMAGE = re.compile(r"[A-Za-z0-9][A-Za-z0-9./:_-]*@sha256:[a-f0-9]{64}")
_REPOSITORY = re.compile(r"[A-Za-z0-9][A-Za-z0-9.:-]*/[a-z0-9][a-z0-9/_.-]*")
_PYTHON_LINKS = {"/usr/local/bin/python", "/usr/local/bin/python3", "/usr/local/bin/python3.11"}


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
            (source / part for part in (".", "dist", "build", "public") if (source / part / "index.html").is_file()),
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
                if metadata.st_mode & (stat.S_ISUID | stat.S_ISGID):
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
    repository = target.rsplit(":", 1)[0]
    if not _REPOSITORY.fullmatch(repository):
        raise ExecutorError("oci_registry_invalid")
    base = document["profile"].get("runtime_image", "")
    platform = document["platform"]
    if not _IMAGE.fullmatch(base) or platform not in {"linux/amd64", "linux/arm64"}:
        raise ExecutorError("oci_frozen_base_invalid")
    layer = write_layer(document, source, environment, Path(work) / "application-layer.tar")
    command = ["crane", "--platform", platform]
    if document.get("insecure_registry"):
        command.append("--insecure")
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
            "PATH=/opt/venv/bin:/app/node_modules/.bin:/usr/local/bin:/usr/bin:/bin",
            "--tag",
            target,
        ]
        startup = document.get("startup", {}).get("command") or []
        if startup:
            if not isinstance(startup, list) or any(
                not isinstance(part, str) or not part or "\x00" in part for part in startup
            ):
                raise ExecutorError("oci_startup_invalid")
            encoded = io.StringIO()
            csv.writer(encoded, lineterminator="").writerow(startup)
            arguments += ["--cmd", encoded.getvalue()]
        reference = execute(arguments).strip()
        if not _IMAGE.fullmatch(reference) or reference.split("@")[0] != repository:
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


class KubernetesAssembler:
    def __init__(self, runtime):
        self.runtime = runtime

    def prepare(self, operation, delivery):
        runtime = self.runtime
        repository = runtime.document.get("image_repository", "")
        if not _REPOSITORY.fullmatch(repository):
            raise ExecutorError("oci_registry_required")
        image = runtime.document.get("assembler_image", "")
        if not _IMAGE.fullmatch(image):
            raise ExecutorError("oci_assembler_image_required")
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
                package_sources=[repository.split("/")[0], document["profile"]["runtime_image"].split("/")[0]],
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
