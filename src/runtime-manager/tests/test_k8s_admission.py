"""覆盖 AC: AC-03、AC-13、AC-14、AC-15、AC-16、AC-21、AC-23、AC-30、AC-31、AC-32、AC-49."""

import copy

import pytest

from runtime_manager.k8s_templates import POLICY_ANNOTATION, RESOURCE_LABEL

NAMESPACE = "bisheng-runtime-apps"
MANAGER = "system:serviceaccount:bisheng-system:runtime-manager"
UID = "22222222-2222-4222-8222-222222222222"


@pytest.fixture
def template():
    from runtime_manager.k8s_templates import PodPlan, pod_template

    return pod_template(
        PodPlan(
            namespace=NAMESPACE,
            app_id="app-a",
            operation_id="operation-a",
            resource_ref="resource-a",
            node_id="node-a",
            generation=1,
            owner_epoch=1,
            purpose="serve",
            platform="linux/amd64",
            status_policy_revision="v1",
            image="example/runtime@sha256:" + "a" * 64,
            helper_image="example/helper@sha256:" + "b" * 64,
            command=("python", "main.py"),
            memory_mb=512,
            cpu_millicores=250,
            pvc_name="data-a",
            material_secret="material-a",
        )
    )


@pytest.fixture
def plan(template):
    from runtime_manager.k8s_admission import template_projection

    return {
        "resource_ref": "resource-a",
        "namespace": NAMESPACE,
        "name": template["metadata"]["name"],
        "kind": "Pod",
        "template": template_projection(template),
        "uid": UID,
        "allow_create": True,
        "allow_update": True,
        "allow_delete": True,
        "stop_state": "held",
        "cleanup_only": False,
    }


def request(obj, *, operation="CREATE", subresource="", username=MANAGER, groups=(), old=None, options=None):
    return {
        "apiVersion": "admission.k8s.io/v1",
        "kind": "AdmissionReview",
        "request": {
            "uid": "request-uid",
            "operation": operation,
            "namespace": NAMESPACE,
            "name": obj["metadata"]["name"],
            "resource": {"group": "", "version": "v1", "resource": "pods"},
            "subResource": subresource,
            "userInfo": {"username": username, "groups": list(groups)},
            "object": obj,
            "oldObject": old,
            "options": options or {},
        },
    }


def policy(reader):
    from runtime_manager.k8s_admission import AdmissionPolicy

    return AdmissionPolicy(
        namespace=NAMESPACE, manager_username=MANAGER, status_policy_revision="v1", plan_reader=reader
    )


def allowed(verifier, review):
    result = verifier.review(review)
    assert result["response"]["uid"] == review["request"]["uid"]
    assert "patch" not in result["response"]
    return result["response"]["allowed"]


def test_create_requires_a_committed_backend_plan(template, plan):
    calls = []
    verifier = policy(lambda ref: calls.append(ref) or plan)
    assert allowed(verifier, request(template))
    assert calls == ["resource-a"]
    assert not allowed(policy(lambda _: None), request(template))

    def unavailable(_):
        raise RuntimeError("sensitive-backend-detail")

    result = policy(unavailable).review(request(template))
    assert not result["response"]["allowed"]
    assert "sensitive-backend-detail" not in str(result)


def test_scope_and_request_identity_cannot_be_supplied_in_labels(template, plan):
    assert not allowed(policy(lambda _: plan), request(template, username="system:serviceaccount:other:attacker"))
    obj = copy.deepcopy(template)
    obj["metadata"]["namespace"] = "foreign"
    assert not allowed(policy(lambda _: plan), request(obj))
    obj = copy.deepcopy(template)
    obj["metadata"]["labels"][RESOURCE_LABEL] = "other"
    assert not allowed(policy(lambda _: plan), request(obj))


@pytest.mark.parametrize(
    "change",
    [
        "image",
        "command",
        "root",
        "privileged",
        "hostNetwork",
        "token",
        "hostPath",
        "extra-container",
        "extra-secret",
        "other-pvc",
        "no-limit",
        "foreign-label",
        "policy",
        "nodeName",
    ],
)
def test_template_mutations_are_denied(template, plan, change):
    obj = copy.deepcopy(template)
    app = obj["spec"]["containers"][0]
    if change == "image":
        app["image"] = "attacker/image:latest"
    elif change == "command":
        app["command"] = ["other"]
    elif change == "root":
        app["securityContext"]["runAsUser"] = 0
    elif change == "privileged":
        app["securityContext"]["privileged"] = True
    elif change == "hostNetwork":
        obj["spec"]["hostNetwork"] = True
    elif change == "token":
        obj["spec"]["automountServiceAccountToken"] = True
    elif change == "hostPath":
        obj["spec"]["volumes"].append({"name": "host", "hostPath": {"path": "/"}})
    elif change == "extra-container":
        obj["spec"]["containers"].append(copy.deepcopy(app))
    elif change == "extra-secret":
        obj["spec"]["volumes"].append({"name": "other", "secret": {"secretName": "other"}})
    elif change == "other-pvc":
        next(x for x in obj["spec"]["volumes"] if x["name"] == "data")["persistentVolumeClaim"]["claimName"] = "other"
    elif change == "no-limit":
        app["resources"].pop("limits")
    elif change == "foreign-label":
        obj["metadata"]["labels"]["network-role"] = "manager"
    elif change == "policy":
        obj["metadata"]["annotations"][POLICY_ANNOTATION] = "wrong"
    elif change == "nodeName":
        obj["spec"]["nodeName"] = "worker-a"
    assert not allowed(policy(lambda _: plan), request(obj))


def test_even_an_unsafe_approved_spec_cannot_disable_baseline(template, plan):
    template["spec"]["hostNetwork"] = True
    plan["template"] = template
    assert not allowed(policy(lambda _: plan), request(template))


def test_api_server_defaults_are_normalized_but_unknown_fields_are_refused(template, plan):
    obj = copy.deepcopy(template)
    obj["spec"].update(
        serviceAccountName="default",
        schedulerName="default-scheduler",
        priority=0,
        preemptionPolicy="PreemptLowerPriority",
    )
    for c in obj["spec"]["containers"] + obj["spec"]["initContainers"]:
        c.update(terminationMessagePath="/dev/termination-log", terminationMessagePolicy="File")
    assert allowed(policy(lambda _: plan), request(obj))
    obj["spec"]["serviceAccountName"] = "privileged"
    assert not allowed(policy(lambda _: plan), request(obj))


def terminal(template):
    obj = copy.deepcopy(template)
    obj["metadata"].update(uid=UID, resourceVersion="17", deletionTimestamp="2026-10-21T00:00:00Z")
    obj["spec"]["nodeName"] = "worker-a"
    obj["status"] = {
        "phase": "Failed",
        "containerStatuses": [{"name": "app", "state": {"terminated": {"exitCode": 1}}}],
    }
    return obj


def test_status_terminal_is_only_introduced_by_authenticated_bound_kubelet(template):
    calls = []
    verifier = policy(
        lambda _: calls.append(True) or (_ for _ in ()).throw(AssertionError("backend callback forbidden"))
    )
    obj = terminal(template)
    old = copy.deepcopy(obj)
    old["status"] = {"phase": "Running"}
    assert allowed(
        verifier,
        request(
            obj,
            operation="UPDATE",
            subresource="status",
            username="system:node:worker-a",
            groups=["system:nodes"],
            old=old,
        ),
    )
    for username, groups in [
        (MANAGER, []),
        ("system:kube-controller-manager", []),
        ("system:node:other", ["system:nodes"]),
        ("system:node:worker-a", []),
    ]:
        assert not allowed(
            verifier, request(obj, operation="UPDATE", subresource="status", username=username, groups=groups, old=old)
        )
    assert not calls


def test_status_terminal_cannot_be_reactivated_or_rebound(template):
    verifier = policy(lambda _: pytest.fail("status must not read backend"))
    old = terminal(template)
    new = copy.deepcopy(old)
    new["status"]["phase"] = "Running"
    assert not allowed(
        verifier,
        request(
            new,
            operation="UPDATE",
            subresource="status",
            username="system:node:worker-a",
            groups=["system:nodes"],
            old=old,
        ),
    )
    new = copy.deepcopy(old)
    new["spec"]["nodeName"] = "other"
    assert not allowed(
        verifier,
        request(
            new,
            operation="UPDATE",
            subresource="status",
            username="system:node:other",
            groups=["system:nodes"],
            old=old,
        ),
    )


def test_nonterminal_scheduler_condition_update_has_no_backend_dependency(template):
    obj = copy.deepcopy(template)
    obj["metadata"]["uid"] = UID
    obj["status"] = {"phase": "Pending", "conditions": [{"type": "PodScheduled", "status": "False"}]}
    old = copy.deepcopy(obj)
    old["status"] = {"phase": "Pending"}
    assert allowed(
        policy(lambda _: pytest.fail("backend read forbidden")),
        request(obj, operation="UPDATE", subresource="status", username="system:kube-scheduler", old=old),
    )


def test_delete_and_finalizer_removal_require_uid_and_committed_stop(template, plan):
    old = terminal(template)
    options = {"preconditions": {"uid": UID, "resourceVersion": "17"}, "gracePeriodSeconds": 30}
    assert allowed(policy(lambda _: plan), request(old, operation="DELETE", old=old, options=options))
    for change in ({"gracePeriodSeconds": 0}, {"preconditions": {"uid": "other", "resourceVersion": "17"}}):
        assert not allowed(
            policy(lambda _: plan), request(old, operation="DELETE", old=old, options={**options, **change})
        )
    new = copy.deepcopy(old)
    new["metadata"]["finalizers"] = []
    assert not allowed(policy(lambda _: plan), request(new, operation="UPDATE", old=old))
    plan["stop_state"] = "confirmed"
    plan["cleanup_only"] = True
    plan["allow_create"] = False
    assert allowed(policy(lambda _: plan), request(new, operation="UPDATE", old=old))
    assert not allowed(policy(lambda _: plan), request(template))


def test_terminal_kubelet_may_tighten_delete_grace_without_backend_callback(template):
    old = terminal(template)
    review = request(
        old,
        operation="DELETE",
        old=old,
        username="system:node:worker-a",
        groups=["system:nodes"],
        options={"preconditions": {"uid": UID}, "gracePeriodSeconds": 0},
    )
    assert allowed(policy(lambda _: pytest.fail("backend callback forbidden")), review)
    review["request"]["userInfo"]["username"] = "system:kube-controller-manager"
    assert not allowed(policy(lambda _: None), review)


def test_validator_http_entrypoint_accepts_real_admission_review(template, plan):
    from fastapi.testclient import TestClient

    from runtime_manager.k8s_admission import create_app

    with TestClient(create_app(policy(lambda _: plan))) as client:
        response = client.post("/validate", json=request(template))
    assert response.status_code == 200
    assert response.json()["response"]["allowed"] is True


def test_api_quantity_serialization_does_not_change_frozen_resource_limits(template, plan):
    obj = copy.deepcopy(template)
    for c in obj["spec"]["containers"] + obj["spec"]["initContainers"]:
        for side in ("limits", "requests"):
            cpu = c["resources"][side]["cpu"]
            c["resources"][side]["cpu"] = str(int(cpu[:-1]) / 1000)
    assert allowed(policy(lambda _: plan), request(obj))


def test_resource_update_cannot_add_an_extra_protection_finalizer(template, plan):
    old = terminal(template)
    new = copy.deepcopy(old)
    new["metadata"]["finalizers"].append("attacker.invalid/hold")
    assert not allowed(policy(lambda _: plan), request(new, operation="UPDATE", old=old))


def test_secret_plan_contains_digest_only_and_matches_content(template):
    from runtime_manager.k8s_admission import secret_projection

    obj = {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": copy.deepcopy(template["metadata"]),
        "immutable": True,
        "type": "Opaque",
        "data": {"key": "ZmFrZS1rZXk="},
    }
    ref = obj["metadata"]["labels"][RESOURCE_LABEL]
    projection = secret_projection(obj)
    assert "data" not in projection and "data_sha256" in projection
    plan = {
        "resource_ref": ref,
        "namespace": NAMESPACE,
        "name": obj["metadata"]["name"],
        "kind": "Secret",
        "template": projection,
        "allow_create": True,
    }
    review = request(obj)
    review["request"]["resource"]["resource"] = "secrets"
    assert allowed(policy(lambda _: plan), review)
    review["request"]["object"]["data"]["key"] = "dGFtcGVy"
    assert not allowed(policy(lambda _: plan), review)


def test_readonly_plan_client_rotates_separate_key_and_never_follows_redirects(tmp_path, plan):
    import httpx

    from runtime_manager.k8s_admission import AdmissionPlanClient, AdmissionRefused

    key_file = tmp_path / "admission.key"
    key_file.write_text("a" * 64)
    calls = []
    responses = [httpx.Response(200, json=plan), httpx.Response(302, headers={"Location": "https://other.invalid"})]

    def handler(req):
        calls.append(req)
        return responses.pop(0)

    client = AdmissionPlanClient(
        "https://platform.invalid",
        key_id="readonly-admission",
        secret_file=key_file,
        transport=httpx.MockTransport(handler),
    )
    try:
        assert client("resource-a")["resource_ref"] == "resource-a"
        key_file.write_text("b" * 64)
        with pytest.raises(AdmissionRefused):
            client("resource-a")
        assert len(calls) == 2
        assert all(r.headers["X-Runtime-Key-Id"] == "readonly-admission" for r in calls)
        assert calls[0].headers["X-Runtime-Signature"] != calls[1].headers["X-Runtime-Signature"]
        assert calls[0].url.path == "/api/v1/internal/app-runtime/v2/admission/plans/resource-a"
        with pytest.raises(ValueError):
            client("../resources")
        assert len(calls) == 2
    finally:
        client.close()


@pytest.mark.parametrize("value", ["1e999999", "NaN", "-1", "0"])
def test_extreme_resource_quantities_are_rejected_without_large_allocation(template, plan, value):
    obj = copy.deepcopy(template)
    obj["spec"]["containers"][0]["resources"]["limits"]["memory"] = value
    assert not allowed(policy(lambda _: plan), request(obj))


def test_pod_approved_plan_never_contains_plaintext_environment_credentials(template):
    from runtime_manager.k8s_admission import template_projection

    secret = "fake-application-runtime-credential"
    template["spec"]["containers"][0]["env"].append({"name": "BISHENG_APP_API_KEY", "value": secret})
    projection = template_projection(template)
    assert secret not in str(projection)
    assert projection["spec"]["containers"][0]["env"][-1]["value_sha256"]
    assert template["spec"]["containers"][0]["env"][-1]["value"] == secret


def test_even_approved_templates_cannot_mount_arbitrary_configmaps(template, plan):
    from runtime_manager.k8s_admission import template_projection

    template["spec"]["volumes"].append(
        {
            "name": "data-keys",
            "configMap": {
                "name": "foreign-config",
                "defaultMode": 292,
                "items": [{"key": "public-keys.json", "path": "public-keys.json"}],
            },
        }
    )
    plan["template"] = template_projection(template)
    assert not allowed(policy(lambda _: plan), request(template))


def test_installed_cni_can_only_change_its_own_network_annotations(template):
    from runtime_manager.k8s_admission import AdmissionPolicy
    from runtime_manager.k8s_templates import STOP_FINALIZER

    cni = "system:serviceaccount:kube-system:calico-node"
    verifier = AdmissionPolicy(
        namespace=NAMESPACE,
        manager_username=MANAGER,
        status_policy_revision="v1",
        plan_reader=lambda _: pytest.fail("CNI metadata must not call backend"),
        cni_username=cni,
    )
    old = copy.deepcopy(template)
    old["metadata"]["uid"] = UID
    old["spec"]["nodeName"] = "worker-a"
    new = copy.deepcopy(old)
    new["metadata"]["annotations"].update(
        {
            "cni.projectcalico.org/containerID": "a" * 64,
            "cni.projectcalico.org/podIP": "10.233.64.10/32",
            "cni.projectcalico.org/podIPs": "10.233.64.10/32",
        }
    )
    assert allowed(verifier, request(new, operation="UPDATE", old=old, username=cni))
    for mutation in ("image", "finalizer", "status", "label"):
        changed = copy.deepcopy(new)
        if mutation == "image":
            changed["spec"]["containers"][0]["image"] = "attacker/image:latest"
        elif mutation == "finalizer":
            changed["metadata"]["finalizers"].remove(STOP_FINALIZER)
        elif mutation == "status":
            changed["status"] = {"phase": "Succeeded"}
        else:
            changed["metadata"]["labels"]["attacker"] = "yes"
        assert not allowed(verifier, request(changed, operation="UPDATE", old=old, username=cni))


def test_pvc_binding_controller_can_only_bind_once_and_manage_protection(template):
    old = {
        "apiVersion": "v1",
        "kind": "PersistentVolumeClaim",
        "metadata": copy.deepcopy(template["metadata"]),
        "spec": {
            "accessModes": ["ReadWriteOnce"],
            "storageClassName": "",
            "volumeMode": "Filesystem",
            "resources": {"requests": {"storage": "1Gi"}},
        },
    }
    old["metadata"]["uid"] = UID
    old["metadata"].pop("finalizers")
    new = copy.deepcopy(old)
    new["spec"]["volumeName"] = "installed-app-volume"
    new["metadata"]["annotations"]["pv.kubernetes.io/bind-completed"] = "yes"
    new["metadata"]["finalizers"] = ["kubernetes.io/pvc-protection"]
    verifier = policy(lambda _: pytest.fail("PVC controller metadata must not call backend"))

    def review(obj, previous):
        data = request(obj, operation="UPDATE", old=previous, username="system:kube-controller-manager")
        data["request"]["resource"]["resource"] = "persistentvolumeclaims"
        return data

    assert allowed(verifier, review(new, old))
    changed = copy.deepcopy(new)
    changed["spec"]["volumeName"] = "other-volume"
    assert not allowed(verifier, review(changed, new))
    changed = copy.deepcopy(new)
    changed["spec"]["resources"]["requests"]["storage"] = "100Gi"
    assert not allowed(verifier, review(changed, old))
    changed = copy.deepcopy(new)
    changed["metadata"]["labels"]["attacker"] = "yes"
    assert not allowed(verifier, review(changed, old))
