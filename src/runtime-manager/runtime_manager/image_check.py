"""Trusted, read-only registry verification. Never execute application images."""

import hashlib
import json
import os
import re
import subprocess
import time
from tempfile import TemporaryFile

from runtime_manager.executors.protocol import ExecutorError

IMAGE = re.compile(r"[A-Za-z0-9][A-Za-z0-9./:_-]*@sha256:[a-f0-9]{64}")
ROLES = {"helper", "preparer", "runtime", "assembler", "image"}


def frozen_targets(operation, capabilities):
    payload = operation["payload"]
    preparing = operation["kind"] == "prepare"
    delivery = payload.get("delivery", {}) if preparing else payload["resolved_delivery"]
    profile = payload.get("profile", {}) if preparing else delivery.get("profile", {})
    profile = profile or {}
    mode = delivery.get("mode", "bundle")
    targets = [{"role": "helper", "reference": capabilities.get("helper_image", ""), "image_id": ""}]
    if preparing and mode in {"bundle", "source-image"}:
        targets.append(
            {
                "role": "preparer",
                "reference": profile.get("preparer_image", ""),
                "image_id": profile.get("preparer_image_id", ""),
            }
        )
    if mode in {"image", "source-image"} and not preparing:
        targets.append(
            {"role": "image", "reference": delivery.get("image_ref", ""), "image_id": delivery.get("image_id", "")}
        )
    elif mode == "image":
        targets.append({"role": "image", "reference": delivery.get("image", ""), "image_id": ""})
    else:
        targets.append(
            {
                "role": "runtime",
                "reference": profile.get("runtime_image", ""),
                "image_id": profile.get("runtime_image_id", ""),
            }
        )
    if preparing and mode == "source-image":
        targets.append({"role": "assembler", "reference": capabilities.get("assembler_image", ""), "image_id": ""})
    return targets


def registry_options(capabilities):
    if capabilities.get("insecure_registry") is not True:
        return {}
    from runtime_manager.oci_assembler import _repository

    _, authority = _repository(capabilities.get("image_repository", ""))
    return {"insecure_registries": [authority]}


def check_document(operation, capabilities, platform):
    targets = frozen_targets(operation, capabilities)
    options = registry_options(capabilities)
    options = {
        key: [
            authority
            for authority in values
            if any(authority == target["reference"].split("/", 1)[0] for target in targets)
        ]
        for key, values in options.items()
    }
    return {"platform": platform, "targets": targets, **options}


def registry_sources(targets, *, endpoints=(), insecure_registries=()):
    from runtime_manager.oci_assembler import _frozen_image, registry_origins

    sources = set()
    for target in targets:
        reference = target["reference"]
        if not isinstance(reference, str) or not IMAGE.fullmatch(reference):
            raise ExecutorError("image_check_document_invalid")
        repository = reference.split("@", 1)[0]
        _, authority = _frozen_image(reference)
        sources.update(
            registry_origins(reference, repository, endpoints=endpoints, insecure=authority in insecure_registries)
        )
    return sorted(sources)


def _run(args, *, timeout):
    # A small tmpfs/ephemeral-storage limit bounds the process output on disk.
    with TemporaryFile() as output, TemporaryFile() as errors:
        subprocess.run(args, stdout=output, stderr=errors, timeout=timeout, check=True)
        if output.tell() > 1024 * 1024:
            raise ExecutorError("image_check_output_limit")
        output.seek(0)
        return output.read()


def check_images(document, *, run=_run, clock=time.monotonic):
    if not isinstance(document, dict) or (
        set(document) - {"platform", "targets", "insecure_registries"} or not {"platform", "targets"} <= document.keys()
    ):
        raise ExecutorError("image_check_document_invalid")
    platform, targets = document["platform"], document["targets"]
    if (
        not isinstance(platform, str)
        or platform not in {"linux/amd64", "linux/arm64"}
        or not isinstance(targets, list)
        or not 1 <= len(targets) <= 4
    ):
        raise ExecutorError("image_check_document_invalid")
    for target in targets:
        if (
            not isinstance(target, dict)
            or set(target) != {"role", "reference", "image_id"}
            or not isinstance(target["role"], str)
            or target["role"] not in ROLES
            or not isinstance(target["reference"], str)
            or not IMAGE.fullmatch(target["reference"])
            or not isinstance(target["image_id"], str)
            or (target["image_id"] and not re.fullmatch(r"sha256:[a-f0-9]{64}", target["image_id"]))
        ):
            raise ExecutorError("image_check_document_invalid")
    from runtime_manager.oci_assembler import _frozen_image

    insecure = document.get("insecure_registries", [])
    authorities = {_frozen_image(t["reference"])[1] for t in targets}
    if not isinstance(insecure, list) or any(
        not isinstance(value, str) or value not in authorities for value in insecure
    ):
        raise ExecutorError("image_check_document_invalid")
    deadline = clock() + 60
    checked = []
    for target in targets:

        def command(*args, target=target):
            remaining = deadline - clock()
            if remaining <= 0:
                raise ExecutorError("image_check_timeout")
            try:
                flags = ["--insecure"] if _frozen_image(target["reference"])[1] in insecure else []
                return run(["crane", "--platform", platform, *flags, *args], timeout=remaining)
            except subprocess.TimeoutExpired:
                raise ExecutorError("image_check_timeout") from None
            except (subprocess.CalledProcessError, OSError):
                raise ExecutorError("image_check_unavailable") from None

        try:
            command("validate", "--remote", target["reference"])
            raw = command("config", target["reference"])
            if not isinstance(raw, bytes) or len(raw) > 1024 * 1024:
                raise ExecutorError("image_check_output_limit")
            try:
                config = json.loads(raw)
            except (ValueError, UnicodeError):
                raise ExecutorError("image_check_config_invalid") from None
            if not isinstance(config, dict) or (config.get("os"), config.get("architecture")) != tuple(
                platform.split("/")
            ):
                raise ExecutorError("image_platform_mismatch")
            identity = "sha256:" + hashlib.sha256(raw).hexdigest()
            if target["image_id"] and identity != target["image_id"]:
                raise ExecutorError("image_content_mismatch")
        except ExecutorError as exc:
            exc.image_role, exc.image_ref = target["role"], target["reference"]
            raise
        checked.append({**target, "image_id": identity})
    return {"images": checked}


def main():
    try:
        result = check_images(json.loads(os.environ["IMAGE_CHECK_PLAN"]))
    except ExecutorError as exc:
        from runtime_manager.secret_redaction import image_failure_context

        result = {"reason": str(exc), **image_failure_context(exc)}
    except (ValueError, KeyError, TypeError):
        result = {"reason": "image_check_document_invalid"}
    print("BISHENG_RUNTIME_RESULT " + json.dumps(result, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
