"""覆盖 AC: AC-05、AC-11、AC-12、AC-16、AC-17、AC-18、AC-19、AC-20、AC-21、AC-24、AC-27、AC-30、AC-33、AC-34、AC-43、AC-44、AC-54."""

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
        assert env == {
            "name": "MATERIAL_POD_UID",
            "valueFrom": {"fieldRef": {"apiVersion": "v1", "fieldPath": "metadata.uid"}},
        }
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
    assert next(e for e in helper["env"] if e["name"] == "DATA_POD_UID")["valueFrom"] == {
        "fieldRef": {"apiVersion": "v1", "fieldPath": "metadata.uid"}
    }
    assert any(v["name"] == "data-keys" and v["readOnly"] for v in helper["volumeMounts"])
    assert not any(
        v["name"] in {"material-auth", "data-keys"}
        for c in spec["containers"]
        if c["name"] == "app"
        for v in c["volumeMounts"]
    )
    volume = next(v for v in spec["volumes"] if v["name"] == "data-keys")
    assert volume["configMap"]["name"] == "runtime-data-public-keys"


@pytest.mark.parametrize("purpose", ["prepare-download", "prepare-install", "prepare-upload", "assemble"])
def test_preparation_starts_with_trusted_readonly_scratch_guard(plan, purpose):
    import json

    from runtime_manager.k8s_templates import pod_template

    guard = {
        "namespace": plan.namespace,
        "installation_id": "e2e-f059",
        "filesystem": "ext4",
        "capacity_bytes": 4 * 1024**3,
        "marker_required": True,
    }
    current = replace(
        plan,
        purpose=purpose,
        pvc_name="",
        scratch_pvc="scratch-a",
        deadline_seconds=120,
        volume_guard=guard,
        registry_secret="registry-a" if purpose == "assemble" else "",
        helper_env={"MATERIAL_PLAN": "scoped"},
    )
    spec = pod_template(current)["spec"]
    validator = spec["initContainers"][0]
    assert validator["name"] == "storage-guard"
    assert validator["image"] == plan.helper_image
    assert validator["command"] == ["python", "-I", "-m", "runtime_manager.k8s_helper", "storage-guard"]
    assert validator["env"] == [{"name": "VOLUME_GUARD", "value": json.dumps(guard, sort_keys=True)}]
    scratch = next(mount for mount in validator["volumeMounts"] if mount["name"] == "scratch")
    assert scratch == {"name": "scratch", "mountPath": "/volume", "readOnly": True}
    assert {mount["name"] for mount in validator["volumeMounts"]} == {"scratch", "tmp"}
    assert validator["securityContext"]["readOnlyRootFilesystem"] is True
    assert validator["securityContext"]["runAsNonRoot"] is True
    assert "valueFrom" not in str(validator) and "MATERIAL_PLAN" not in str(validator)
    assert spec["containers"][0]["name"] != "storage-guard"


@pytest.mark.parametrize("purpose", ["probe", "preview"])
def test_ephemeral_data_without_pvc_does_not_get_scratch_guard(plan, purpose):
    from runtime_manager.k8s_templates import pod_template

    spec = pod_template(replace(plan, purpose=purpose, pvc_name="", deadline_seconds=120))["spec"]
    assert not any(container["name"] == "storage-guard" for container in spec["initContainers"])


@pytest.mark.parametrize("purpose", ["serve", "probe", "preview"])
@pytest.mark.parametrize(
    "frozen",
    [("nginx", "-g", "daemon off;"), ("nginx", "-g", "daemon off;", "-q"), ("/bin/sh", "-c", "exec /custom-server")],
)
def test_static_bundle_preserves_image_entrypoint_and_frozen_arguments(plan, purpose, frozen):
    from runtime_manager.k8s_templates import pod_template

    current = replace(
        plan,
        runtime_language="static",
        purpose=purpose,
        port=8765,
        env={"PORT": "8765", "BISHENG_APP_PORT": "8765"},
        command=frozen,
        pvc_name=plan.pvc_name if purpose == "serve" else "",
        deadline_seconds=None if purpose == "serve" else 60,
    )
    app = next(container for container in pod_template(current)["spec"]["containers"] if container["name"] == "app")
    assert app["command"] == ["/opt/bisheng/entrypoint.sh"]
    assert app["args"] == list(frozen) and current.command == frozen
    assert app["ports"] == [{"name": "http", "containerPort": 8765, "protocol": "TCP"}]
    assert {item["name"]: item.get("value") for item in app["env"]}["PORT"] == "8765"
    assert app["securityContext"]["readOnlyRootFilesystem"] is True
    assert any(mount["mountPath"] == "/tmp" and not mount["readOnly"] for mount in app["volumeMounts"])


def test_full_image_with_static_profile_does_not_get_a_bundle_entrypoint(plan):
    from runtime_manager.k8s_templates import pod_template

    spec = pod_template(
        replace(plan, runtime_language="static", mode="image", command=("/custom/entry", "--flag"), material_secret="")
    )["spec"]
    app = next(container for container in spec["containers"] if container["name"] == "app")
    assert app["command"] == ["/custom/entry", "--flag"] and "args" not in app
    spec = pod_template(replace(plan, runtime_language="static", mode="image", command=(), material_secret=""))["spec"]
    app = next(container for container in spec["containers"] if container["name"] == "app")
    assert "command" not in app and "args" not in app


def test_python_bundle_has_no_image_entrypoint_to_bypass(plan):
    from runtime_manager.k8s_templates import pod_template

    app = next(
        container
        for container in pod_template(replace(plan, runtime_language="python3.11"))["spec"]["containers"]
        if container["name"] == "app"
    )
    assert app["command"] == ["python", "main.py"] and "args" not in app


@pytest.mark.parametrize("purpose", ["serve", "probe", "preview"])
@pytest.mark.parametrize(
    "frozen", [("node", "server.js"), ("npm", "start"), ("server.js",), ("--eval", "console.log('started')")]
)
def test_node_bundle_preserves_standard_image_entrypoint_semantics(plan, purpose, frozen):
    from runtime_manager.k8s_templates import pod_template

    current = replace(
        plan,
        runtime_language="node20",
        purpose=purpose,
        command=frozen,
        port=8765,
        env={"PORT": "8765"},
        pvc_name=plan.pvc_name if purpose == "serve" else "",
        deadline_seconds=None if purpose == "serve" else 60,
    )
    app = next(container for container in pod_template(current)["spec"]["containers"] if container["name"] == "app")
    assert app["command"] == ["/usr/local/bin/docker-entrypoint.sh"]
    assert app["args"] == list(frozen) and current.command == frozen
    assert app["workingDir"] == "/workspace/app"
    assert {item["name"]: item.get("value") for item in app["env"]}["PORT"] == "8765"
    assert app["command"][0].startswith("/")  # Application PATH cannot replace the image launcher.


@pytest.mark.parametrize("frozen", [(), ("/custom/launcher", "--flag")])
def test_complete_node_image_does_not_get_the_bundle_launcher(plan, frozen):
    from runtime_manager.k8s_templates import pod_template

    app = next(
        container
        for container in pod_template(
            replace(plan, runtime_language="node20", mode="image", command=frozen, material_secret="")
        )["spec"]["containers"]
        if container["name"] == "app"
    )
    assert "args" not in app
    if frozen:
        assert app["command"] == list(frozen)
    else:
        assert "command" not in app


@pytest.mark.parametrize("purpose", ["migrate", "restore"])
def test_material_maintenance_template_satisfies_the_real_identity_reader(plan, tmp_path, monkeypatch, purpose):
    """覆盖 AC: AC-33、AC-34、AC-35、AC-48、AC-49、AC-50、AC-51、AC-55."""
    import json

    from runtime_manager.k8s_helper import client_from_identity
    from runtime_manager.k8s_templates import pod_template

    spec = pod_template(replace(plan, purpose=purpose, deadline_seconds=60))["spec"]
    container = next(item for item in spec["containers"] if item["name"] == "maintenance")
    mount = next(item for item in container["volumeMounts"] if item["name"] == "material-auth")
    assert mount["mountPath"] == "/run/material" and mount["readOnly"] is True
    assert container["command"] == ["python", "-I", "-m", "runtime_manager.k8s_data_helper", "maintenance"]
    uid = "22222222-2222-4222-8222-222222222222"
    monkeypatch.delenv("MATERIAL_POD_UID", raising=False)
    # Resolve only the exact core/v1 Downward API field the real kubelet supplies.
    for entry in container["env"]:
        if entry["name"] == "MATERIAL_POD_UID":
            assert entry == {
                "name": "MATERIAL_POD_UID",
                "valueFrom": {"fieldRef": {"apiVersion": "v1", "fieldPath": "metadata.uid"}},
            }
            monkeypatch.setenv(entry["name"], uid)
    identity = tmp_path / "identity.json"
    identity.write_text(
        json.dumps(
            {
                "base_url": "https://backend.invalid",
                "delegation_id": plan.resource_ref,
                "key_id": "maintenance-key",
                "private_key": "01" * 32,
                "scope_kind": "operation",
                "expires_at": 100030,
                "phase_timeout_seconds": 60,
            }
        )
    )
    client = client_from_identity(identity, clock=lambda: 100000)
    try:
        assert client.pod_uid == uid and client.delegation_id == plan.resource_ref
        assert client.deadline == 100030  # A Pod UID does not extend the operation's authority.
    finally:
        client.close()


@pytest.mark.parametrize("purpose", ["serve", "data", "purge"])
def test_application_data_and_identity_free_purge_do_not_receive_material_uid(plan, purpose):
    """覆盖 AC: AC-33、AC-35、AC-48、AC-49、AC-50、AC-51、AC-55."""
    from runtime_manager.k8s_templates import pod_template

    current = replace(
        plan,
        purpose=purpose,
        material_secret=plan.material_secret if purpose == "serve" else "",
        deadline_seconds=None if purpose == "serve" else 60,
    )
    spec = pod_template(current)["spec"]
    for container in spec["containers"]:
        assert not any(item["name"] == "MATERIAL_POD_UID" for item in container["env"])
        assert not any(item["name"] == "material-auth" for item in container["volumeMounts"])
    if purpose in {"data", "purge"}:
        assert not any(item["name"] == "material-auth" for item in spec["volumes"])


@pytest.mark.parametrize("purpose", ["migrate", "restore"])
def test_maintenance_without_material_secret_does_not_get_material_uid(plan, purpose):
    """覆盖 AC: AC-48、AC-49、AC-50、AC-51."""
    from runtime_manager.k8s_templates import pod_template

    spec = pod_template(replace(plan, purpose=purpose, material_secret="", deadline_seconds=60))["spec"]
    container = next(item for item in spec["containers"] if item["name"] == "maintenance")
    assert not any(item["name"] == "MATERIAL_POD_UID" for item in container["env"])
    assert not any(item["name"] == "material-auth" for item in container["volumeMounts"])


@pytest.mark.parametrize("purpose", ["migrate", "restore", "purge"])
@pytest.mark.parametrize("name", ["MATERIAL_POD_UID", "DATA_POD_UID"])
def test_maintenance_pod_uid_cannot_be_replaced_by_a_caller_literal(plan, purpose, name):
    """覆盖 AC: AC-48、AC-49、AC-50、AC-51."""
    from runtime_manager.k8s_templates import pod_template

    with pytest.raises(ValueError, match="k8s_material_uid_literal_refused"):
        pod_template(
            replace(
                plan,
                purpose=purpose,
                material_secret="" if purpose == "purge" else plan.material_secret,
                deadline_seconds=60,
                helper_env={name: "caller-literal"},
            )
        )


@pytest.mark.parametrize("cpu", [25, 100, 250])
def test_offline_data_helper_and_layout_use_the_frozen_cpu_tier(plan, cpu):
    """F059 覆盖 AC: AC-33、AC-35、AC-44、AC-48、AC-55."""
    from runtime_manager.k8s_templates import pod_template

    spec = pod_template(replace(plan, purpose="data", cpu_millicores=cpu, deadline_seconds=60))["spec"]
    assert [container["name"] for container in spec["initContainers"]] == ["data-layout"]
    assert [container["name"] for container in spec["containers"]] == ["data-helper"]
    for container in spec["initContainers"] + spec["containers"]:
        assert container["resources"]["requests"] == container["resources"]["limits"]
        assert container["resources"]["limits"]["cpu"] == f"{cpu}m"
        assert container["resources"]["limits"]["memory"] == "128Mi"
        assert container["securityContext"]["runAsNonRoot"]
        assert container["securityContext"]["readOnlyRootFilesystem"]
        assert not container["securityContext"]["allowPrivilegeEscalation"]
    # Init and application containers run sequentially: the Pod CPU envelope is
    # max(init requests, running-container sum), matching the single tier claim.
    budget = max(
        int(spec["initContainers"][0]["resources"]["requests"]["cpu"][:-1]),
        sum(int(container["resources"]["requests"]["cpu"][:-1]) for container in spec["containers"]),
    )
    assert budget == cpu and spec["activeDeadlineSeconds"] == 60
    assert spec["restartPolicy"] == "Never" and spec["automountServiceAccountToken"] is False
    assert not any(volume["name"] == "material-auth" for volume in spec["volumes"])


@pytest.mark.parametrize(
    "purpose",
    [
        "serve",
        "probe",
        "preview",
        "migrate",
        "restore",
        "purge",
        "prepare-download",
        "prepare-install",
        "prepare-upload",
        "assemble",
    ],
)
def test_offline_data_cpu_tier_does_not_change_other_helper_budgets(plan, purpose):
    """F059 覆盖 AC: AC-33、AC-35、AC-44、AC-48、AC-55."""
    from runtime_manager.k8s_templates import PREPARATION, PRODUCTION, pod_template

    spec = pod_template(
        replace(
            plan,
            purpose=purpose,
            cpu_millicores=100,
            deadline_seconds=None if purpose == "serve" else 60,
            pvc_name=plan.pvc_name if purpose in PRODUCTION else "",
            scratch_pvc="scratch-a" if purpose in PREPARATION else "",
            material_secret="" if purpose == "purge" else plan.material_secret,
            schema_plan=({"op": "create_table", "table": "items", "columns": []},)
            if purpose in {"probe", "preview"}
            else (),
        )
    )["spec"]
    helpers = [
        container
        for container in spec["initContainers"] + spec["containers"]
        if container["name"]
        in {"data-layout", "schema-init", "material-fetch", "storage-guard", "maintenance", "data-helper"}
    ]
    assert helpers
    for container in helpers:
        assert container["resources"]["requests"] == container["resources"]["limits"]
        assert container["resources"]["limits"]["cpu"] == "25m"
        assert container["resources"]["limits"]["memory"] == "128Mi"
    primary = [container for container in spec["containers"] if container not in helpers]
    for container in primary:
        assert container["resources"]["requests"]["cpu"] == "100m"


@pytest.mark.parametrize("runtime", ["python3.11", "node20", "static"])
@pytest.mark.parametrize("purpose", ["serve", "probe", "preview"])
def test_bundle_path_keeps_profile_system_binaries_and_dependency_precedence(plan, runtime, purpose):
    """AC-24, AC-25, AC-27: nginx is installed in /usr/sbin by the frozen static profile."""
    from runtime_manager.k8s_templates import pod_template

    current = replace(
        plan,
        runtime_language=runtime,
        purpose=purpose,
        pvc_name=plan.pvc_name if purpose == "serve" else "",
        deadline_seconds=None if purpose == "serve" else 120,
    )
    app = next(c for c in pod_template(current)["spec"]["containers"] if c["name"] == "app")
    path = next(v["value"] for v in app["env"] if v["name"] == "PATH").split(":")
    assert path[:2] == ["/opt/venv/bin", "/workspace/app/node_modules/.bin"]
    assert {"/usr/local/sbin", "/usr/local/bin", "/usr/sbin", "/usr/bin", "/sbin", "/bin"} <= set(path)
    assert not {"", "."} & set(path)
    image = next(
        c
        for c in pod_template(replace(current, mode="image", material_secret=""))["spec"]["containers"]
        if c["name"] == "app"
    )
    assert not any(v["name"] == "PATH" for v in image["env"])
