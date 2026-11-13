"""F119 覆盖 AC: AC-28, AC-29, AC-30, AC-31, AC-32, AC-34."""

import hashlib
import subprocess
from dataclasses import replace

import pytest

from tests.test_k8s_templates import plan as plan
from tests.test_kubernetes_executor import runtime as runtime


def test_checker_validates_all_layers_then_exact_config_identity_and_architecture():
    from runtime_manager.image_check import check_images

    config = b'{"architecture":"amd64","os":"linux"}'
    expected = "sha256:" + hashlib.sha256(config).hexdigest()
    reference = "registry.invalid/app@sha256:" + "a" * 64
    calls = []

    def run(args, *, timeout):
        calls.append(args)
        assert 0 < timeout <= 60
        return config if "config" in args else b"PASS"

    result = check_images(
        {"platform": "linux/amd64", "targets": [{"role": "runtime", "reference": reference, "image_id": expected}]},
        run=run,
    )
    assert result["images"][0]["image_id"] == expected
    assert "--fast" not in calls[0]
    assert calls[0][-3:] == ["validate", "--remote", reference]
    assert calls[0][:3] == ["crane", "--platform", "linux/amd64"]


@pytest.mark.parametrize("mode", ["identity", "platform", "layers", "mutable"])
def test_checker_refuses_invalid_or_unreadable_fixed_images(mode):
    from runtime_manager.executors.protocol import ExecutorError
    from runtime_manager.image_check import check_images

    reference = "registry.invalid/app@sha256:" + "a" * 64
    config = (
        b'{"architecture":"arm64","os":"linux"}' if mode == "platform" else b'{"architecture":"amd64","os":"linux"}'
    )
    if mode == "mutable":
        reference = "registry.invalid/app:latest"

    def run(args, **kwargs):
        if mode == "layers":
            raise subprocess.CalledProcessError(1, args, stderr=b"credential must not escape")
        return config

    document = {
        "platform": "linux/amd64",
        "targets": [
            {"role": "runtime", "reference": reference, "image_id": "sha256:" + "b" * 64 if mode == "identity" else ""}
        ],
    }
    with pytest.raises(ExecutorError) as caught:
        check_images(document, run=run)
    assert "credential" not in str(caught.value)


def test_image_check_pod_has_no_source_or_data_mount_and_only_fixed_helper(plan):
    from runtime_manager.k8s_templates import pod_template

    current = replace(
        plan,
        purpose="image-check",
        mode="image",
        pvc_name="",
        material_secret="",
        image=plan.helper_image,
        command=("python", "-I", "-m", "runtime_manager.image_check"),
        deadline_seconds=120,
        registry_secret="registry-auth",
        env={},
        helper_env={"IMAGE_CHECK_PLAN": "{}", "DOCKER_CONFIG": "/run/registry"},
    )
    pod = pod_template(current)
    assert not pod["spec"]["initContainers"]
    assert pod["spec"]["automountServiceAccountToken"] is False
    assert len(pod["spec"]["containers"]) == 1
    assert all("persistentVolumeClaim" not in v for v in pod["spec"]["volumes"])
    checker = pod["spec"]["containers"][0]
    assert checker["image"] == plan.helper_image
    assert {v["mountPath"] for v in checker["volumeMounts"]} <= {"/tmp", "/run/registry"}
    assert pod["spec"]["activeDeadlineSeconds"] == 120
    with pytest.raises(ValueError):
        pod_template(replace(current, command=("sh", "-c", "application-script")))
    with pytest.raises(ValueError):
        pod_template(replace(current, material_secret="must-not-mount"))


def test_checks_are_idempotent_owned_and_use_neither_material_nor_production_resources(runtime):
    executor, platform, cluster, operation, events, _ = runtime
    first = executor.preflight(operation)
    count = len([e for e in events if e[0] == "create"])
    assert executor.preflight(operation) == first
    assert len([e for e in events if e[0] == "create"]) == count
    assert first["images"] and all(row["purpose"] == "image-check" for row in platform.rows.values())
    assert all(row["stop_state"] == "held" for row in platform.rows.values())
    assert executor.cleanup(operation)["complete"]
    assert not cluster.objects
    assert all(row["cleanup_state"] == "complete" for row in platform.rows.values())
    assert not any(kind in {"persistentvolumeclaims", "secrets"} for kind, _ in cluster.objects)


def test_missing_registry_layer_stops_before_prepare_download(runtime, monkeypatch):
    from runtime_manager.executors.protocol import ExecutorError

    executor, _, _, operation, _, _ = runtime
    operation["kind"] = "prepare"
    profile = operation["payload"].pop("resolved_delivery")["profile"]
    operation["payload"].update(profile=profile, delivery={"mode": "bundle"}, source_artifact_id="source")
    monkeypatch.setattr(
        executor.client, "logs", lambda *args, **kwargs: 'BISHENG_RUNTIME_RESULT {"reason":"image_check_unavailable"}'
    )
    monkeypatch.setattr(executor, "_phase", lambda *args, **kwargs: pytest.fail("no materials before image check"))
    with pytest.raises(ExecutorError, match="image_check_unavailable"):
        executor.prepare(operation)


def test_insecure_registry_option_is_limited_to_the_explicit_installation_registry():
    from runtime_manager.image_check import check_images

    secure = "secure.invalid/helper@sha256:" + "a" * 64
    private = "private.invalid:5443/app@sha256:" + "b" * 64
    targets = [
        {"role": "helper", "reference": secure, "image_id": ""},
        {"role": "runtime", "reference": private, "image_id": ""},
    ]
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        return b'{"os":"linux","architecture":"amd64"}'

    check_images(
        {"platform": "linux/amd64", "targets": targets, "insecure_registries": ["private.invalid:5443"]}, run=run
    )
    assert all(("--insecure" in args) is (args[-1] == private) for args in calls)
