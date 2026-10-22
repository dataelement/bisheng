"""覆盖 AC: AC-05、AC-11、AC-12、AC-16、AC-17、AC-18、AC-19、AC-20、AC-21、AC-24、AC-27、AC-33、AC-34、AC-43、AC-44、AC-54."""

from dataclasses import replace

import pytest


@pytest.fixture
def plan():
    from runtime_manager.k8s_templates import PodPlan

    return PodPlan(
        namespace="bisheng-runtime-apps",
        app_id="app-identity",
        operation_id="operation-identity",
        resource_ref="11111111-1111-4111-8111-111111111111",
        node_id="domain-a",
        generation=3,
        owner_epoch=7,
        purpose="serve",
        platform="linux/amd64",
        status_policy_revision="v1",
        image="example/runtime@sha256:" + "a" * 64,
        helper_image="example/helper@sha256:" + "b" * 64,
        command=("python", "main.py"),
        memory_mb=512,
        cpu_millicores=250,
        pvc_name="data-app-a",
        material_secret="material-app-a",
        env={"APP_PORT": "8080"},
    )


def test_production_location_is_stable_across_versions_and_maintenance(plan):
    from runtime_manager.k8s_templates import pod_template, production_name

    expected = production_name(plan.app_id)
    assert len(expected) <= 63
    assert expected != production_name(plan.app_id + "2")
    for purpose in ("serve", "migrate", "restore", "data"):
        item = pod_template(replace(plan, purpose=purpose, deadline_seconds=None if purpose == "serve" else 60))
        assert item["metadata"]["name"] == expected
    assert pod_template(replace(plan, generation=4, operation_id="new"))["metadata"]["name"] == expected


def test_bundle_credentials_are_only_mounted_to_trusted_fetch(plan):
    from runtime_manager.k8s_templates import pod_template

    spec = pod_template(plan)["spec"]
    init = {c["name"]: c for c in spec["initContainers"]}
    assert "material-fetch" in init and "environment" in init
    assert any(v["name"] == "material-auth" for v in init["material-fetch"]["volumeMounts"])
    assert not any(v["name"] in {"material-auth", "data"} for v in init["environment"]["volumeMounts"])
    assert not any(v["name"] == "data" for v in init["material-fetch"]["volumeMounts"])
    app = next(c for c in spec["containers"] if c["name"] == "app")
    mounts = {v["name"]: v for v in app["volumeMounts"]}
    assert mounts["code"]["readOnly"] and mounts["environment"]["readOnly"]
    assert mounts["data"]["subPath"] == "business"
    assert "material-auth" not in mounts
    assert app["workingDir"] == "/workspace/app"
    assert app["command"] == ["python", "main.py"]
    assert app["resources"]["requests"] == app["resources"]["limits"]
    assert "activeDeadlineSeconds" not in spec


def test_all_execution_bodies_are_restricted_and_no_cluster_identity(plan):
    from runtime_manager.k8s_templates import STOP_FINALIZER, pod_template

    item = pod_template(plan)
    assert STOP_FINALIZER in item["metadata"]["finalizers"]
    spec = item["spec"]
    assert spec["automountServiceAccountToken"] is False
    assert spec["securityContext"]["runAsNonRoot"] is True
    assert spec["nodeSelector"]["kubernetes.io/arch"] == "amd64"
    assert not any(v.get("hostPath") or v.get("projected") for v in spec["volumes"])
    assert not any(spec.get(key) for key in ("hostNetwork", "hostIPC", "hostPID"))
    for c in spec["containers"] + spec["initContainers"]:
        assert c["securityContext"]["allowPrivilegeEscalation"] is False
        assert c["securityContext"]["readOnlyRootFilesystem"] is True
        assert c["securityContext"]["capabilities"] == {"drop": ["ALL"]}
        assert c["resources"]["limits"]["ephemeral-storage"]
    assert spec["restartPolicy"] == "Always"


@pytest.mark.parametrize("purpose", ["probe", "preview", "prepare-download", "prepare-install", "prepare-upload"])
def test_ephemeral_pods_never_mount_production_and_have_total_deadline(plan, purpose):
    from runtime_manager.k8s_templates import pod_template, production_name

    item = pod_template(replace(plan, purpose=purpose, pvc_name="", scratch_pvc="scratch-a", deadline_seconds=120))
    assert item["metadata"]["name"] != production_name(plan.app_id)
    assert item["spec"]["activeDeadlineSeconds"] == 120
    assert not any(v.get("persistentVolumeClaim", {}).get("claimName") == "data-app-a" for v in item["spec"]["volumes"])
    if purpose.startswith("prepare"):
        assert item["spec"]["restartPolicy"] == "Never"


def test_preparer_credentials_do_not_cross_untrusted_install_phase(plan):
    from runtime_manager.k8s_templates import pod_template

    base = replace(plan, pvc_name="", scratch_pvc="scratch-a", deadline_seconds=120)
    for purpose in ("prepare-download", "prepare-upload"):
        spec = pod_template(replace(base, purpose=purpose))["spec"]
        assert any(v["name"] == "material-auth" for v in spec["volumes"])
        assert len(spec["containers"]) == 1
    install = pod_template(replace(base, purpose="prepare-install"))["spec"]
    assert not any(v["name"] == "material-auth" for v in install["volumes"])
    assert not any(e["name"].startswith("BISHENG_") for e in install["containers"][0]["env"])


def test_data_offline_has_no_business_container_or_platform_credentials(plan):
    from runtime_manager.k8s_templates import pod_template

    spec = pod_template(replace(plan, purpose="data", deadline_seconds=60))["spec"]
    assert [x["name"] for x in spec["containers"]] == ["data-helper"]
    assert not any(v["name"] == "material-auth" for v in spec["volumes"])
    assert spec["restartPolicy"] == "Never"
    assert spec["activeDeadlineSeconds"] == 60


def test_full_image_has_no_code_materialization_and_can_use_image_entrypoint(plan):
    from runtime_manager.k8s_templates import pod_template

    spec = pod_template(replace(plan, mode="image", command=(), material_secret=""))["spec"]
    assert not any(x["name"] in {"environment", "material-fetch"} for x in spec["initContainers"])
    app = next(x for x in spec["containers"] if x["name"] == "app")
    assert "command" not in app
    assert not any(v["name"] in {"code", "environment"} for v in app["volumeMounts"])


def test_service_is_internal_and_selects_the_exact_resource(plan):
    from runtime_manager.k8s_templates import service_template

    obj = service_template(plan)
    assert obj["spec"]["type"] == "ClusterIP"
    assert obj["spec"]["selector"] == {"runtime.bisheng.io/resource": plan.resource_ref}
    assert obj["spec"]["ports"][0]["targetPort"] == plan.port
    assert "nodePort" not in obj["spec"]["ports"][0]
    with pytest.raises(ValueError):
        service_template(replace(plan, purpose="data", deadline_seconds=60))


def test_pvc_retention_and_secret_only_contain_explicit_fields(plan):
    from runtime_manager.k8s_templates import pvc_template, secret_template

    pvc = pvc_template(plan, name=plan.pvc_name, size_mb=1024, storage_class="")
    assert pvc["spec"]["storageClassName"] == ""
    assert "ownerReferences" not in pvc["metadata"]
    secret = secret_template(plan, name=plan.material_secret, data={"key": b"fake-workload-private-key"})
    assert "fake-workload-private-key" not in str(secret)
    assert secret["immutable"] is True
    assert "ownerReferences" not in secret["metadata"]


@pytest.mark.parametrize(
    "change",
    [
        {"image": "example/runtime:latest"},
        {"platform": "linux/386"},
        {"uid": 0},
        {"gid": 0},
        {"cpu_millicores": 0},
        {"memory_mb": -1},
        {"purpose": "exec"},
        {"namespace": "kube-system"},
        {"command": ("bad\x00command",)},
        {"port": 0},
        {"health_path": "https://other.invalid"},
        {"env": {"RTM_PLATFORM_SECRET": "x"}},
        {"env": {"LD_PRELOAD": "x"}},
        {"pvc_name": "../data"},
        {"purpose": "preview", "deadline_seconds": 100},
    ],
)
def test_invalid_or_unfrozen_plan_is_refused(plan, change):
    from runtime_manager.k8s_templates import pod_template

    with pytest.raises(ValueError):
        pod_template(replace(plan, **change))


def test_template_digest_is_stable_and_changes_with_frozen_inputs(plan):
    from runtime_manager.k8s_templates import pod_template, template_digest

    a = pod_template(plan)
    assert template_digest(a) == template_digest(pod_template(plan))
    assert template_digest(a) != template_digest(pod_template(replace(plan, command=("python", "other.py"))))


def test_business_credentials_use_only_app_scoped_secret_references(plan):
    from runtime_manager.k8s_templates import pod_template

    obj = pod_template(replace(plan, app_secret="app-credentials-a", secret_env=("BISHENG_APP_API_KEY", "HTTPS_PROXY")))
    containers = obj["spec"]["containers"]
    app = next(x for x in containers if x["name"] == "app")
    selected = [x for x in app["env"] if x["name"] in {"BISHENG_APP_API_KEY", "HTTPS_PROXY"}]
    assert len(selected) == 2
    assert all(x["valueFrom"]["secretKeyRef"]["name"] == "app-credentials-a" for x in selected)
    assert not any("value" in x for x in selected)
    for container in containers + obj["spec"]["initContainers"]:
        if container["name"] != "app":
            assert "app-credentials-a" not in str(container)


@pytest.mark.parametrize(
    "change",
    [
        {"app_secret": "", "secret_env": ("BISHENG_APP_API_KEY",)},
        {"app_secret": "../credentials", "secret_env": ("BISHENG_APP_API_KEY",)},
        {"app_secret": "app-a", "secret_env": ("RTM_PLATFORM_SECRET",)},
        {"app_secret": "app-a", "secret_env": ("APP_PORT",)},
        {"app_secret": "app-a", "secret_env": ("DUPLICATE", "DUPLICATE")},
    ],
)
def test_secret_environment_mapping_cannot_overlap_or_expose_control_fields(plan, change):
    from runtime_manager.k8s_templates import pod_template

    with pytest.raises(ValueError):
        pod_template(replace(plan, **change))


def test_trusted_helpers_ignore_packages_from_shared_working_directories(plan):
    from runtime_manager.k8s_templates import pod_template

    for purpose in ("serve", "prepare-download", "prepare-upload", "data"):
        current = replace(
            plan,
            purpose=purpose,
            pvc_name="" if purpose.startswith("prepare") else plan.pvc_name,
            scratch_pvc="scratch-a",
            deadline_seconds=None if purpose == "serve" else 60,
        )
        spec = pod_template(current)["spec"]
        for container in spec["containers"] + spec["initContainers"]:
            if container["image"] == plan.helper_image:
                assert container["command"][:3] == ["python", "-I", "-m"]


def test_material_pod_uid_comes_from_downward_api_and_never_a_caller_literal(plan):
    from runtime_manager.k8s_templates import pod_template

    for purpose in ("serve", "prepare-download", "prepare-upload"):
        current = replace(
            plan,
            purpose=purpose,
            pvc_name="" if purpose.startswith("prepare") else plan.pvc_name,
            scratch_pvc="scratch-a",
            deadline_seconds=None if purpose == "serve" else 60,
        )
        spec = pod_template(current)["spec"]
        transfer = next(
            c
            for c in spec["initContainers"] + spec["containers"]
            if any(m["name"] == "material-auth" for m in c["volumeMounts"])
        )
        env = next(e for e in transfer["env"] if e["name"] == "MATERIAL_POD_UID")
        assert env == {"name": "MATERIAL_POD_UID", "valueFrom": {"fieldRef": {"fieldPath": "metadata.uid"}}}
    with pytest.raises(ValueError):
        pod_template(replace(plan, helper_env={"MATERIAL_POD_UID": "caller-value"}))


def test_prepare_install_mounts_the_fixed_tool_paths_without_transferring_identity(plan):
    from runtime_manager.k8s_templates import pod_template

    spec = pod_template(
        replace(plan, purpose="prepare-install", pvc_name="", scratch_pvc="scratch-a", deadline_seconds=120)
    )["spec"]
    worker = spec["containers"][0]
    mounts = {m["mountPath"]: m for m in worker["volumeMounts"]}
    assert mounts["/workspace/app"]["subPath"] == "source"
    assert mounts["/original"]["subPath"] == "original" and mounts["/original"]["readOnly"] is True
    assert mounts["/materials"]["subPath"] == "materials" and mounts["/materials"]["readOnly"] is True
    assert mounts["/output"]["subPath"] == "output"
    assert "material-auth" not in {m["name"] for m in mounts.values()}


def test_file_secret_keys_support_identity_json_and_ca_certificate_without_path_segments(plan):
    from runtime_manager.k8s_templates import secret_template

    secret = secret_template(
        plan, name=plan.material_secret, data={"identity.json": b"fixture identity", "ca.crt": b"fixture CA"}
    )
    assert set(secret["data"]) == {"identity.json", "ca.crt"}
    with pytest.raises(ValueError):
        secret_template(plan, name=plan.material_secret, data={"../outside": b"no"})


def test_data_sidecar_gets_public_keys_and_uid_without_app_credentials(plan):
    import json

    from runtime_manager.k8s_templates import pod_template

    spec = pod_template(plan)["spec"]
    helper = next(c for c in spec["containers"] if c["name"] == "data-helper")
    assert helper["command"] == ["python", "-I", "-m", "runtime_manager.k8s_data_helper"]
    context = json.loads(next(e["value"] for e in helper["env"] if e["name"] == "DATA_CONTEXT"))
    assert context == {"app_id": plan.app_id, "exec_ref": plan.resource_ref}
    assert (
        next(e for e in helper["env"] if e["name"] == "DATA_POD_UID")["valueFrom"]["fieldRef"]["fieldPath"]
        == "metadata.uid"
    )
    assert any(v["name"] == "data-keys" and v["readOnly"] for v in helper["volumeMounts"])
    assert not any(
        v["name"] in {"material-auth", "data-keys"}
        for c in spec["containers"]
        if c["name"] == "app"
        for v in c["volumeMounts"]
    )
    volume = next(v for v in spec["volumes"] if v["name"] == "data-keys")
    assert volume["configMap"]["name"] == "runtime-data-public-keys"
