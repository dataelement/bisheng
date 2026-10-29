"""覆盖 AC: AC-13、AC-14、AC-16、AC-21、AC-23、AC-49. Installer-only bootstrap."""

import json
from uuid import uuid4

import pytest

from runtime_manager.k8s_admission import template_projection
from runtime_manager.k8s_templates import PodPlan, capability_probe_template

HELPER = "example/helper@sha256:" + "a" * 64
NS = "runtime-apps"


@pytest.fixture
def frozen(tmp_path):
    ref = str(uuid4())
    plan = PodPlan(
        namespace=NS,
        app_id="preflight-a",
        operation_id="preflight-a",
        resource_ref=ref,
        node_id="node-a",
        generation=1,
        owner_epoch=1,
        purpose="probe",
        platform="linux/amd64",
        status_policy_revision="v1",
        image=HELPER,
        helper_image=HELPER,
        command=(),
        memory_mb=128,
        cpu_millicores=100,
        deadline_seconds=60,
        mode="image",
    )
    pod = capability_probe_template(plan, network={"targets": []})
    approved = {
        "resource_ref": ref,
        "namespace": NS,
        "name": pod["metadata"]["name"],
        "kind": "Pod",
        "uid": None,
        "template": template_projection(pod),
        "allow_create": True,
        "allow_update": False,
        "allow_delete": False,
        "cleanup_only": False,
        "stop_state": "held",
        "expires_at": 1200,
    }
    path = tmp_path / "plans.json"
    document = {"schema_version": 1, "plans": {ref: approved}}
    path.write_text(json.dumps(document))
    return path, document, ref


def reader(path):
    from runtime_manager.k8s_admission import CanaryPlanReader

    return CanaryPlanReader(lambda ref: {"backend": ref}, path, namespace=NS, helper_image=HELPER, clock=lambda: 1000)


def test_canary_is_explicit_frozen_bounded_and_never_falls_back_on_invalid_plan(frozen):
    path, document, ref = frozen
    assert document["plans"][ref]["name"].startswith("preflight-")
    assert reader(path)(ref)["allow_create"]
    assert reader(path)(str(uuid4())).get("backend")
    document["plans"][ref]["expires_at"] = 999
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="canary"):
        reader(path)(ref)


@pytest.mark.parametrize("mutation", ["name", "secret", "volume", "image", "command", "operation", "uid", "lifetime"])
def test_canary_never_authorizes_application_code_credentials_or_production_data(frozen, mutation):
    path, document, ref = frozen
    plan = document["plans"][ref]
    pod = plan["template"]
    if mutation == "name":
        plan["name"] = pod["metadata"]["name"] = "app-production"
    elif mutation == "secret":
        pod["spec"]["volumes"].append({"name": "key", "secret": {"secretName": "runtime-identities"}})
    elif mutation == "volume":
        pod["spec"]["volumes"].append({"name": "prod", "persistentVolumeClaim": {"claimName": "data-production"}})
    elif mutation == "image":
        pod["spec"]["containers"][0]["image"] = "evil/image@sha256:" + "b" * 64
    elif mutation == "command":
        pod["spec"]["containers"][0]["command"] = ["python", "-c", "print('arbitrary')"]
    elif mutation == "operation":
        pod["metadata"]["annotations"]["runtime.bisheng.io/operation"] = "business-operation"
    elif mutation == "uid":
        plan["allow_update"] = True
    else:
        plan["expires_at"] = 5000
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError, match="canary"):
        reader(path)(ref)
