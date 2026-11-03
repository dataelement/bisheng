"""Explicit compatibility build; its input still comes from the scoped platform API."""

from runtime_manager.builder import BASE_IMAGES, _chunk_to_text, build_args_for, render_build_context
from runtime_manager.bundle_inputs import extract_archive
from runtime_manager.container_runner import ExecutionError, redact
from runtime_manager.source_facts import source_facts


def prepared_delivery(operation, image):
    body = operation["payload"]
    return {
        "mode": "source-image",
        "image_ref": image["Id"],
        "image_id": image["Id"],
        "platform": body["platform"],
        "runtime": body["runtime"],
        "startup": body.get("delivery", {}).get("startup", {}),
    }


def prepare_image(config, platform, docker, operation, *, checkpoint, report):
    if operation["payload"].get("legacy_build_state") == "started":
        raise ExecutionError("legacy_build_stop_unconfirmed")
    if operation["payload"].get("legacy_build_state") == "finished":
        tag = f"{config.image_prefix}:operation-{operation['operation_id']}"
        return prepared_delivery(operation, docker.inspect_image(tag))
    root = config.data_root / "tasks" / operation["operation_id"]
    root.mkdir(parents=True, exist_ok=True)
    archive = root / "source.tar.gz"
    platform.download(
        operation["operation_id"],
        operation["payload"]["source_artifact_id"],
        archive,
        max_bytes=operation["payload"].get("source_limits", {}).get("compressed", 50 * 1024 * 1024),
    )
    source = root / "legacy-source"
    if not source.exists():
        limits = operation["payload"].get("source_limits", {})
        extract_archive(
            archive,
            source,
            max_bytes=limits.get("unpacked", 200 * 1024 * 1024),
            max_entries=limits.get("entries", 20000),
        )
    if not (source / "bisheng-app.yaml").exists():
        children = list(source.iterdir())
        if len(children) == 1 and children[0].is_dir():
            source = children[0]
    body = operation["payload"]
    runtime = body["runtime"]
    if body.get("offline") or config.image_pull_policy == "never":
        try:
            base = docker.inspect_image(BASE_IMAGES[runtime])
        except Exception as exc:
            if isinstance(exc, KeyError) or getattr(exc, "status_code", None) == 404:
                raise ExecutionError("legacy_base_image_missing") from exc
            raise
        if base.get("Os", "linux") + "/" + base.get("Architecture", "") != body["platform"]:
            raise ExecutionError("legacy_base_platform_mismatch")
    for name, content in render_build_context(
        runtime, {"port": body.get("port", 8080), **source_facts(runtime, source)}
    ).items():
        (source / name).write_text(content)
    checkpoint()
    tag = f"{config.image_prefix}:operation-{operation['operation_id']}"
    args = build_args_for(config, runtime)
    if not body.get("offline") and config.egress_enabled:
        from runtime_manager.egress import egress_env

        credentials = platform.egress(
            operation["operation_id"],
            "build",
            package_sources=[
                config.build_index_url,
                config.build_extra_index_url,
                config.build_npm_registry,
            ],
        )
        proxy = egress_env(config, **credentials)
        args.update({key: value for key, value in proxy.items() if key in {"HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY"}})
    report("preparing", detail={"legacy_build_state": "started"})
    failed = False
    tail = []
    # No caller Dockerfile, arbitrary build args or production volume enters this path.
    for chunk in docker.build_image(
        context_dir=str(source),
        dockerfile="Dockerfile",
        tag=tag,
        buildargs=args,
        memory_bytes=int(body.get("tier", {}).get("memory_mb", 1024)) * 1024 * 1024,
        network_mode="none" if body.get("offline") else config.build_network,
    ):
        checkpoint()
        error, message = _chunk_to_text(chunk)
        tail.append(redact(str(error or message or ""), args)[-2048:])
        tail = tail[-40:]
        failed = failed or bool(error)
    report("preparing", detail={"legacy_build_state": "finished"})
    if failed:
        raise ExecutionError("legacy_build_failed", "\n".join(tail)[-16384:])
    image = docker.inspect_image(tag)
    return prepared_delivery(operation, image)
