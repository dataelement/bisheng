"""覆盖 AC: AC-03、AC-13、AC-14、AC-15、AC-16、AC-20、AC-21、AC-23、AC-30、AC-31、AC-32、AC-49."""

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


@pytest.mark.parametrize("changed", ["none", "equivalent-quantity", "app-request", "init-request"])
def test_create_accepts_only_api_computed_pending_qos_status(template, plan, changed):
    """AC-13, AC-30, AC-49: v1.28.15 PrepareForCreate runs before validating admission."""
    from runtime_manager.k8s_admission import template_projection

    if changed == "equivalent-quantity":
        template["spec"]["containers"][0]["resources"]["requests"]["cpu"] = "0.25"
        template["spec"]["containers"][0]["resources"]["limits"]["cpu"] = "250m"
    elif changed == "app-request":
        template["spec"]["containers"][0]["resources"]["requests"]["cpu"] = "100m"
    elif changed == "init-request":
        template["spec"]["initContainers"][0]["resources"]["requests"]["memory"] = "64Mi"
    plan["template"] = template_projection(template)
    qos = "Burstable" if changed in {"app-request", "init-request"} else "Guaranteed"
    template["status"] = {"phase": "Pending", "qosClass": qos}
    assert allowed(policy(lambda _: plan), request(template))
    template["status"]["qosClass"] = "Guaranteed" if qos == "Burstable" else "Burstable"
    assert not allowed(policy(lambda _: plan), request(template))


@pytest.mark.parametrize(
    "status",
    [
        {"phase": "Succeeded", "qosClass": "Guaranteed"},
        {"phase": "Failed", "qosClass": "Guaranteed"},
        {"phase": "Running", "qosClass": "Guaranteed"},
        {"phase": "Pending", "qosClass": "BestEffort"},
        {"phase": "Pending"},
        {"qosClass": "Guaranteed"},
        {"phase": "Pending", "qosClass": "Guaranteed", "containerStatuses": []},
        {
            "phase": "Pending",
            "qosClass": "Guaranteed",
            "containerStatuses": [{"name": "app", "state": {"terminated": {"exitCode": 0}}}],
        },
        {"phase": "Pending", "qosClass": "Guaranteed", "initContainerStatuses": []},
        {
            "phase": "Pending",
            "qosClass": "Guaranteed",
            "initContainerStatuses": [{"name": "material-fetch", "state": {"terminated": {"exitCode": 0}}}],
        },
        {"phase": "Pending", "qosClass": "Guaranteed", "ephemeralContainerStatuses": []},
        {"phase": "Pending", "qosClass": "Guaranteed", "conditions": [{"type": "Ready", "status": "True"}]},
        {"phase": "Pending", "qosClass": "Guaranteed", "podIP": "10.233.64.10"},
        {"phase": "Pending", "qosClass": "Guaranteed", "startTime": "2026-10-22T00:00:00Z"},
        [],
        None,
    ],
)
def test_create_rejects_status_evidence_not_generated_by_pod_create_strategy(template, plan, status):
    """AC-13, AC-49: initial Pending is never a waiver for runtime or malformed status."""
    template["status"] = status
    assert not allowed(policy(lambda _: plan), request(template))


def test_approved_template_does_not_allow_manager_prefilled_terminal_status(template, plan):
    """AC-13, AC-49: a committed plan cannot grant the manager kubelet status authority."""
    from runtime_manager.k8s_admission import template_projection

    template["status"] = {"phase": "Succeeded", "qosClass": "Guaranteed"}
    plan["template"] = template_projection(template)
    assert not allowed(policy(lambda _: plan), request(template))


@pytest.mark.parametrize(
    "username,groups",
    [
        ("system:node:worker-a", ["system:nodes"]),
        ("system:kube-scheduler", []),
        ("system:serviceaccount:other:attacker", []),
    ],
)
def test_default_pending_status_does_not_authorize_another_creator(template, plan, username, groups):
    """AC-13, AC-49: status defaults do not substitute for the manager's verified actor."""
    template["status"] = {"phase": "Pending", "qosClass": "Guaranteed"}
    assert not allowed(policy(lambda _: plan), request(template, username=username, groups=groups))


@pytest.mark.parametrize(
    "kind,resource,initial,forged",
    [
        ("PersistentVolumeClaim", "persistentvolumeclaims", {}, {"phase": "Bound"}),
        ("Service", "services", {"loadBalancer": {}}, {"loadBalancer": {"ingress": [{"ip": "10.0.0.1"}]}}),
        ("Secret", "secrets", None, {"phase": "Pending"}),
    ],
)
def test_other_create_resources_accept_only_their_api_default_status(template, plan, kind, resource, initial, forged):
    """AC-13, AC-49: PVC and Service create strategies clear status; Secret has none."""
    from runtime_manager.k8s_admission import template_projection

    obj = {"apiVersion": "v1", "kind": kind, "metadata": copy.deepcopy(template["metadata"])}
    obj["metadata"].pop("finalizers")
    if kind == "PersistentVolumeClaim":
        obj["spec"] = {
            "accessModes": ["ReadWriteOnce"],
            "volumeMode": "Filesystem",
            "resources": {"requests": {"storage": "1Gi"}},
        }
    elif kind == "Service":
        obj["spec"] = {"type": "ClusterIP", "selector": {RESOURCE_LABEL: "pod-a"}, "ports": [{"port": 8080}]}
    else:
        obj.update(type="Opaque", immutable=True, data={"identity.json": "e30="})
    plan.update(kind=kind, template=template_projection(obj))
    if initial is not None:
        obj["status"] = initial
    review = request(obj)
    review["request"]["resource"]["resource"] = resource
    assert allowed(policy(lambda _: plan), review)
    obj["status"] = forged
    assert not allowed(policy(lambda _: plan), review)


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
    """AC-13, AC-30: accept observed canary defaults and documented v1.28.15 fieldRef defaults."""
    obj = copy.deepcopy(template)
    obj["metadata"].update(uid=UID, creationTimestamp="2026-10-22T10:42:03Z")
    obj["status"] = {"phase": "Pending", "qosClass": "Guaranteed"}
    obj["spec"].update(
        serviceAccountName="default",
        serviceAccount="default",
        schedulerName="default-scheduler",
        priority=0,
        preemptionPolicy="PreemptLowerPriority",
    )
    for c in obj["spec"]["containers"] + obj["spec"]["initContainers"]:
        c.update(terminationMessagePath="/dev/termination-log", terminationMessagePolicy="File")
        # Kubernetes v1.28.15 SetDefaults_ObjectFieldSelector defaults the
        # downward API version before validating admission sees the Pod.
        for env in c.get("env", []):
            if "fieldRef" in env.get("valueFrom", {}):
                env["valueFrom"]["fieldRef"].setdefault("apiVersion", "v1")
        if c.get("env") == []:
            c.pop("env")
    assert allowed(policy(lambda _: plan), request(obj))
    obj["spec"]["serviceAccountName"] = "privileged"
    assert not allowed(policy(lambda _: plan), request(obj))


@pytest.mark.parametrize("container_name", ["material-fetch", "data-helper"])
@pytest.mark.parametrize(
    "change",
    [
        {"apiVersion": "v2"},
        {"fieldPath": "metadata.name"},
        {"unapprovedField": "unapproved"},
    ],
    ids=["non-v1", "different-field-path", "extra-field"],
)
def test_downward_api_uid_selector_mutations_remain_refused(template, plan, container_name, change):
    """AC-13, AC-30, AC-49: freeze UID selectors without ignoring unknown fields."""
    obj = copy.deepcopy(template)
    container = next(
        item for item in obj["spec"]["containers"] + obj["spec"]["initContainers"] if item["name"] == container_name
    )
    selector = next(env["valueFrom"]["fieldRef"] for env in container["env"] if "valueFrom" in env)
    selector.update(change)
    response = policy(lambda _: plan).review(request(obj))["response"]
    assert response["allowed"] is False
    assert response["status"] == {"code": 403, "message": "admission_template_mismatch"}


@pytest.mark.parametrize("group", ["containers", "initContainers"])
@pytest.mark.parametrize("change", ["added", "changed", "removed", "null", "mapping"])
def test_empty_env_default_does_not_ignore_nonempty_or_malformed_environment(template, plan, group, change):
    """AC-13, AC-49: only an absent versus empty container env list is equivalent."""
    from runtime_manager.k8s_admission import template_projection

    container = template["spec"][group][0]
    container["env"] = [] if change == "added" else [{"name": "APP_SETTING", "value": "frozen"}]
    plan["template"] = template_projection(template)
    obj = copy.deepcopy(template)
    container = obj["spec"][group][0]
    if change == "added":
        container["env"] = [{"name": "APP_SETTING", "value": "added"}]
    elif change == "changed":
        container["env"][0]["value"] = "changed"
    elif change == "removed":
        container.pop("env")
    elif change == "null":
        container["env"] = None
    else:
        container["env"] = {}
    assert not allowed(policy(lambda _: plan), request(obj))


@pytest.mark.parametrize("location", ["spec", "container"])
def test_empty_env_default_does_not_ignore_other_empty_lists(template, plan, location):
    """AC-13: omitempty handling is scoped to container env, never arbitrary empty fields."""
    obj = copy.deepcopy(template)
    if location == "spec":
        obj["spec"]["imagePullSecrets"] = []
    else:
        obj["spec"]["containers"][0]["args"] = []
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


@pytest.mark.parametrize("omit_finalizers", [False, True])
def test_delete_and_finalizer_removal_require_uid_and_committed_stop(template, plan, omit_finalizers):
    old = terminal(template)
    options = {"preconditions": {"uid": UID, "resourceVersion": "17"}, "gracePeriodSeconds": 30}
    assert allowed(policy(lambda _: plan), request(old, operation="DELETE", old=old, options=options))
    assert allowed(
        policy(lambda _: plan), request(old, operation="DELETE", old=old, options={**options, "gracePeriodSeconds": 0})
    )
    for change in ({"preconditions": {"uid": "other", "resourceVersion": "17"}},):
        assert not allowed(
            policy(lambda _: plan), request(old, operation="DELETE", old=old, options={**options, **change})
        )
    new = copy.deepcopy(old)
    new["metadata"]["finalizers"] = []
    if omit_finalizers:
        new["metadata"].pop("finalizers")
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


@pytest.fixture
def calico_history(template, plan):
    from runtime_manager.k8s_admission import AdmissionPolicy

    cni = "system:serviceaccount:kube-system:calico-node"
    verifier = AdmissionPolicy(
        namespace=NAMESPACE,
        manager_username=MANAGER,
        status_policy_revision="v1",
        plan_reader=lambda _: plan,
        cni_username=cni,
    )
    old = terminal(template)
    annotated = copy.deepcopy(old)
    annotated["metadata"]["annotations"].update(
        {
            "cni.projectcalico.org/containerID": "a" * 64,
            "cni.projectcalico.org/podIP": "10.233.64.10/32",
            "cni.projectcalico.org/podIPs": "10.233.64.10/32",
        }
    )
    assert allowed(verifier, request(annotated, operation="UPDATE", old=old, username=cni))
    return verifier, old, annotated, cni


def test_manager_preserves_authenticated_calico_annotations_during_normal_metadata_update(calico_history):
    """AC-13, AC-49: accepted CNI fields survive a same-UID manager update unchanged."""
    verifier, _, old, _ = calico_history
    new = copy.deepcopy(old)
    new["metadata"]["resourceVersion"] = "18"
    assert allowed(verifier, request(new, operation="UPDATE", old=old))


@pytest.mark.parametrize("omit_finalizers", [False, True])
def test_manager_can_remove_only_confirmed_stop_finalizer_after_calico_update(calico_history, plan, omit_finalizers):
    """AC-13, AC-49: CNI annotations must not deadlock confirmed terminal Pod cleanup."""
    verifier, _, old, _ = calico_history
    new = copy.deepcopy(old)
    new["metadata"]["finalizers"] = []
    if omit_finalizers:
        new["metadata"].pop("finalizers")
    assert not allowed(verifier, request(new, operation="UPDATE", old=old))
    plan["stop_state"] = "confirmed"
    assert allowed(verifier, request(new, operation="UPDATE", old=old))


@pytest.mark.parametrize("mutation", ["add", "change", "remove", "all-remove", "uid"])
def test_manager_cannot_forge_change_or_remove_calico_source_fields(calico_history, mutation):
    """AC-13, AC-49: manager metadata never creates or alters CNI-owned values."""
    verifier, clean, annotated, _ = calico_history
    old = copy.deepcopy(clean if mutation == "add" else annotated)
    new = copy.deepcopy(annotated)
    if mutation == "change":
        new["metadata"]["annotations"]["cni.projectcalico.org/podIP"] = "10.233.64.11/32"
    elif mutation == "remove":
        new["metadata"]["annotations"].pop("cni.projectcalico.org/containerID")
    elif mutation == "all-remove":
        new = copy.deepcopy(clean)
    elif mutation == "uid":
        old["metadata"]["uid"] = "33333333-3333-4333-8333-333333333333"
    assert not allowed(verifier, request(new, operation="UPDATE", old=old))


def test_manager_create_cannot_prefill_calico_even_in_an_approved_template(template, plan, calico_history):
    """AC-13: a manager-supplied frozen template is not CNI provenance."""
    from runtime_manager.k8s_admission import template_projection

    verifier, _, annotated, _ = calico_history
    obj = copy.deepcopy(template)
    obj["metadata"]["annotations"] = copy.deepcopy(annotated["metadata"]["annotations"])
    plan["template"] = template_projection(obj)
    assert not allowed(verifier, request(obj))


def test_cni_metadata_exemption_requires_a_configured_cni_identity(calico_history, plan):
    """AC-13: disabling the trusted CNI actor does not grant a generic annotation exemption."""
    _, _, old, _ = calico_history
    assert not allowed(policy(lambda _: plan), request(copy.deepcopy(old), operation="UPDATE", old=old))


@pytest.mark.parametrize("mutation", ["image", "finalizer", "volume", "node", "extra-annotation"])
def test_authenticated_cni_update_cannot_change_any_other_pod_contract(calico_history, mutation):
    """AC-13, AC-16, AC-49: only three network annotations may be changed by CNI."""
    verifier, old, annotated, cni = calico_history
    new = copy.deepcopy(annotated)
    if mutation == "image":
        new["spec"]["containers"][0]["image"] = "evil/image:latest"
    elif mutation == "finalizer":
        new["metadata"]["finalizers"] = []
    elif mutation == "volume":
        new["spec"]["volumes"][0] = {"name": "foreign", "persistentVolumeClaim": {"claimName": "data-other"}}
    elif mutation == "node":
        new["spec"]["nodeName"] = "worker-b"
    else:
        new["metadata"]["annotations"]["cni.projectcalico.org/arbitrary"] = "untrusted"
    assert not allowed(verifier, request(new, operation="UPDATE", old=old, username=cni))


def test_status_update_cannot_be_used_to_forge_calico_annotation_provenance(calico_history):
    """AC-13, AC-49: even the authenticated bound node cannot write CNI fields via /status."""
    verifier, clean, annotated, _ = calico_history
    assert not allowed(
        verifier,
        request(
            annotated,
            operation="UPDATE",
            subresource="status",
            old=clean,
            username="system:node:worker-a",
            groups=["system:nodes"],
        ),
    )


def test_bound_kubelet_can_finish_after_calico_when_network_metadata_is_unchanged(calico_history):
    """AC-13, AC-49: preserving CNI fields leaves authenticated terminal status handling independent."""
    verifier, _, terminal_pod, _ = calico_history
    verifier.plan_reader = lambda _: pytest.fail("status must not read backend")
    running = copy.deepcopy(terminal_pod)
    running["status"] = {"phase": "Running", "containerStatuses": [{"name": "app", "state": {"running": {}}}]}
    assert allowed(
        verifier,
        request(
            terminal_pod,
            operation="UPDATE",
            subresource="status",
            old=running,
            username="system:node:worker-a",
            groups=["system:nodes"],
        ),
    )


@pytest.mark.parametrize("phase", ["Pending", "Failed"])
@pytest.mark.parametrize("action", ["ADD", "DELETE-remove", "DELETE-empty"])
def test_configured_calico_status_endpoint_only_updates_network_metadata(calico_history, phase, action):
    """AC-13, AC-49: Calico ADD/DELETE may preserve status while updating its annotations."""
    verifier, clean, annotated, cni = calico_history
    verifier.plan_reader = lambda _: pytest.fail("CNI metadata maintenance must not read backend")
    old = copy.deepcopy(clean if action == "ADD" else annotated)
    if phase == "Pending":
        old["metadata"].pop("deletionTimestamp")
        old["status"] = {"phase": "Pending", "qosClass": "Guaranteed"}
    new = copy.deepcopy(old)
    if action == "ADD":
        new["metadata"]["annotations"] = copy.deepcopy(annotated["metadata"]["annotations"])
    else:
        for key in ("cni.projectcalico.org/containerID", "cni.projectcalico.org/podIP", "cni.projectcalico.org/podIPs"):
            if action == "DELETE-remove":
                new["metadata"]["annotations"].pop(key)
            else:
                new["metadata"]["annotations"][key] = ""
    new["metadata"]["resourceVersion"] = "18"
    assert allowed(verifier, request(new, operation="UPDATE", subresource="status", old=old, username=cni))


@pytest.mark.parametrize(
    "mutation",
    [
        "terminal",
        "container-status",
        "init-status",
        "conditions",
        "image",
        "volume",
        "node",
        "unbound",
        "uid",
        "uid-missing",
        "namespace",
        "finalizer",
        "extra-annotation",
        "label",
        "equivalent-spec-change",
    ],
)
def test_calico_status_metadata_exception_cannot_change_any_other_contract(calico_history, mutation):
    """AC-13, AC-16, AC-49: CNI is never a source for status, spec, identity or finalizers."""
    verifier, clean, annotated, cni = calico_history
    old, new = copy.deepcopy(clean), copy.deepcopy(annotated)
    old["status"] = {"phase": "Pending", "qosClass": "Guaranteed"}
    new["status"] = copy.deepcopy(old["status"])
    if mutation == "terminal":
        new["status"]["phase"] = "Succeeded"
    elif mutation == "container-status":
        new["status"]["containerStatuses"] = [{"name": "app", "state": {"terminated": {"exitCode": 0}}}]
    elif mutation == "init-status":
        new["status"]["initContainerStatuses"] = [{"name": "data-layout", "state": {"terminated": {"exitCode": 0}}}]
    elif mutation == "conditions":
        new["status"]["conditions"] = [{"type": "Ready", "status": "True"}]
    elif mutation == "image":
        new["spec"]["containers"][0]["image"] = "attacker/image:latest"
    elif mutation == "volume":
        new["spec"]["volumes"][0] = {"name": "foreign", "persistentVolumeClaim": {"claimName": "data-foreign"}}
    elif mutation == "node":
        new["spec"]["nodeName"] = "worker-b"
    elif mutation == "unbound":
        old["spec"].pop("nodeName")
        new["spec"].pop("nodeName")
    elif mutation == "uid":
        new["metadata"]["uid"] = "33333333-3333-4333-8333-333333333333"
    elif mutation == "uid-missing":
        old["metadata"].pop("uid")
        new["metadata"].pop("uid")
    elif mutation == "namespace":
        new["metadata"]["namespace"] = "foreign"
    elif mutation == "finalizer":
        new["metadata"]["finalizers"] = []
    elif mutation == "extra-annotation":
        new["metadata"]["annotations"]["cni.projectcalico.org/arbitrary"] = "untrusted"
    elif mutation == "label":
        new["metadata"]["labels"]["network-role"] = "manager"
    else:
        new["spec"]["containers"][0]["resources"]["limits"]["cpu"] = "0.25"
    assert not allowed(verifier, request(new, operation="UPDATE", subresource="status", old=old, username=cni))


@pytest.mark.parametrize(
    "username,groups,configured",
    [
        (MANAGER, [], True),
        ("system:node:worker-a", ["system:nodes"], True),
        ("system:serviceaccount:kube-system:another-cni", [], True),
        ("system:serviceaccount:kube-system:calico-node", [], False),
    ],
)
def test_calico_status_metadata_exception_requires_the_exact_configured_actor(
    calico_history, username, groups, configured
):
    """AC-13, AC-49: a node, manager or unconfigured CNI cannot claim the metadata exception."""
    verifier, old, new, _ = calico_history
    if not configured:
        verifier.cni_username = ""
    assert not allowed(
        verifier,
        request(new, operation="UPDATE", subresource="status", old=old, username=username, groups=groups),
    )


def test_api_normalized_zero_grace_is_allowed_only_for_never_bound_pending_pod(template, plan):
    """覆盖 AC: AC-13、AC-20、AC-49。Unscheduled delete is normalized by the API server."""
    old = copy.deepcopy(template)
    old["metadata"].update(uid=UID, resourceVersion="17")
    old["status"] = {"phase": "Pending", "qosClass": "Guaranteed"}
    options = {"preconditions": {"uid": UID, "resourceVersion": "17"}, "gracePeriodSeconds": 0}
    assert allowed(policy(lambda _: plan), request(old, operation="DELETE", old=old, options=options))


@pytest.mark.parametrize("mutation", ["bound", "running", "init-state", "unknown", "lost", "missing-phase", "stale-rv"])
def test_zero_grace_keeps_bound_uncertain_or_changed_pods_protected(template, plan, mutation):
    """覆盖 AC: AC-13、AC-20、AC-49。Zero grace never proves a possible writer stopped."""
    old = copy.deepcopy(template)
    old["metadata"].update(uid=UID, resourceVersion="17")
    old["status"] = {"phase": "Pending", "qosClass": "Guaranteed"}
    options = {"preconditions": {"uid": UID, "resourceVersion": "17"}, "gracePeriodSeconds": 0}
    if mutation == "bound":
        old["spec"]["nodeName"] = "worker-a"
    elif mutation == "running":
        old["status"]["containerStatuses"] = [{"state": {"running": {}}}]
    elif mutation == "init-state":
        old["status"]["initContainerStatuses"] = [{"state": {"terminated": {"exitCode": 0}}}]
    elif mutation == "unknown":
        old["status"]["phase"] = "Unknown"
    elif mutation == "lost":
        old["status"]["reason"] = "NodeLost"
    elif mutation == "missing-phase":
        old["status"].pop("phase")
    else:
        options["preconditions"]["resourceVersion"] = "old"
    assert not allowed(policy(lambda _: plan), request(old, operation="DELETE", old=old, options=options))


def finished_pod(template, *, phase="Succeeded", deleting=False):
    old = copy.deepcopy(template)
    old["metadata"].update(uid=UID, resourceVersion="17")
    if deleting:
        old["metadata"]["deletionTimestamp"] = "2026-10-22T00:00:00Z"
    old["spec"]["nodeName"] = "worker-a"
    old["status"] = {"phase": phase}
    for spec_key, status_key in (("containers", "containerStatuses"), ("initContainers", "initContainerStatuses")):
        old["status"][status_key] = [
            {
                "name": container["name"],
                "containerID": "containerd://finished-" + container["name"],
                "state": {
                    "terminated": {
                        "exitCode": 0 if phase == "Succeeded" else 1,
                        "reason": "Completed" if phase == "Succeeded" else "Error",
                    }
                },
            }
            for container in old["spec"].get(spec_key, [])
        ]
    return old


@pytest.mark.parametrize("phase", ["Succeeded", "Failed"])
@pytest.mark.parametrize("deleting", [False, True])
def test_manager_delete_accepts_api_zero_grace_for_protected_bound_terminal_pod(template, plan, phase, deleting):
    """覆盖 AC: AC-13、AC-20、AC-49。API normalization never removes the stop finalizer."""
    from runtime_manager.k8s_templates import STOP_FINALIZER

    old = finished_pod(template, phase=phase, deleting=deleting)
    before = copy.deepcopy(old)
    options = {"preconditions": {"uid": UID, "resourceVersion": "17"}, "gracePeriodSeconds": 0}
    assert allowed(policy(lambda _: plan), request(old, operation="DELETE", old=old, options=options))
    assert old == before and STOP_FINALIZER in old["metadata"]["finalizers"]
    assert plan["stop_state"] == "held"


def test_manager_zero_grace_allows_trusted_init_failure_with_never_started_app(template, plan):
    old = finished_pod(template, phase="Failed")
    old["status"]["containerStatuses"] = [
        {"name": container["name"], "state": {"waiting": {"reason": "PodInitializing"}}}
        for container in old["spec"]["containers"]
    ]
    options = {"preconditions": {"uid": UID, "resourceVersion": "17"}, "gracePeriodSeconds": 0}
    assert allowed(policy(lambda _: plan), request(old, operation="DELETE", old=old, options=options))


@pytest.mark.parametrize(
    "mutation",
    [
        "running-phase",
        "unknown-phase",
        "node-lost",
        "unknown-reason",
        "unbound",
        "app-running",
        "init-running",
        "ephemeral-running",
        "waiting-container-id",
        "empty-state-container-id",
        "unknown-termination",
        "malformed-status-array",
        "malformed-state",
        "missing-policy",
        "wrong-policy",
        "missing-finalizer",
        "stale-rv",
        "missing-rv",
        "wrong-uid",
        "wrong-plan-uid",
        "wrong-plan-name",
        "wrong-actor",
        "delete-unapproved",
        "wrong-kind",
        "boolean-grace",
    ],
)
def test_manager_normalized_zero_grace_preserves_uncertain_writers_and_identity_fences(template, plan, mutation):
    from runtime_manager.k8s_templates import STOP_FINALIZER

    old = finished_pod(template)
    options = {"preconditions": {"uid": UID, "resourceVersion": "17"}, "gracePeriodSeconds": 0}
    username = MANAGER
    if mutation == "running-phase":
        old["status"]["phase"] = "Running"
    elif mutation == "unknown-phase":
        old["status"]["phase"] = "Unknown"
    elif mutation == "node-lost":
        old["status"]["reason"] = "NodeLost"
    elif mutation == "unknown-reason":
        old["status"]["reason"] = "Unknown"
    elif mutation == "unbound":
        old["spec"].pop("nodeName")
    elif mutation in {"app-running", "init-running", "ephemeral-running"}:
        group = {
            "app-running": "containerStatuses",
            "init-running": "initContainerStatuses",
            "ephemeral-running": "ephemeralContainerStatuses",
        }[mutation]
        old["status"][group] = [{"name": "possible-writer", "state": {"running": {}}}]
    elif mutation == "waiting-container-id":
        old["status"]["containerStatuses"][0]["state"] = {"waiting": {"reason": "Unknown"}}
    elif mutation == "empty-state-container-id":
        old["status"]["containerStatuses"][0]["state"] = {}
    elif mutation == "unknown-termination":
        old["status"]["containerStatuses"][0]["state"]["terminated"]["reason"] = "ContainerStatusUnknown"
    elif mutation == "malformed-status-array":
        old["status"]["initContainerStatuses"] = {"state": {"terminated": {"exitCode": 0}}}
    elif mutation == "malformed-state":
        old["status"]["containerStatuses"][0]["state"] = None
    elif mutation == "missing-policy":
        old["metadata"]["annotations"].pop(POLICY_ANNOTATION)
    elif mutation == "wrong-policy":
        old["metadata"]["annotations"][POLICY_ANNOTATION] = "foreign"
    elif mutation == "missing-finalizer":
        old["metadata"]["finalizers"].remove(STOP_FINALIZER)
    elif mutation == "stale-rv":
        options["preconditions"]["resourceVersion"] = "old"
    elif mutation == "missing-rv":
        old["metadata"].pop("resourceVersion")
        options["preconditions"].pop("resourceVersion")
    elif mutation == "wrong-uid":
        options["preconditions"]["uid"] = "foreign"
    elif mutation == "wrong-plan-uid":
        plan["uid"] = "foreign"
    elif mutation == "wrong-plan-name":
        plan["name"] = "foreign"
    elif mutation == "wrong-actor":
        username = "system:serviceaccount:foreign:runtime-manager"
    elif mutation == "delete-unapproved":
        plan["allow_delete"] = False
    elif mutation == "wrong-kind":
        old["kind"] = "Service"
    else:
        options["gracePeriodSeconds"] = False
    assert not allowed(
        policy(lambda _: plan), request(old, operation="DELETE", old=old, options=options, username=username)
    )


def test_delete_never_uses_manager_supplied_terminal_object_as_stop_evidence(template, plan):
    old = finished_pod(template)
    old["status"]["phase"] = "Running"
    forged = finished_pod(template)
    options = {"preconditions": {"uid": UID, "resourceVersion": "17"}, "gracePeriodSeconds": 0}
    assert not allowed(policy(lambda _: plan), request(forged, operation="DELETE", old=old, options=options))


@pytest.mark.parametrize(
    "mutation",
    [
        "stale-rv",
        "wrong-uid",
        "wrong-node",
        "missing-node-group",
        "missing-delete-time",
        "wrong-namespace",
        "wrong-request-name",
        "node-lost",
        "unknown-waiting",
    ],
)
def test_kubelet_terminal_delete_preserves_identity_status_and_protection_fences(template, mutation):
    old = finished_pod(template, deleting=True)
    options = {"preconditions": {"uid": UID, "resourceVersion": "17"}, "gracePeriodSeconds": 0}
    username, groups = "system:node:worker-a", ["system:nodes"]
    if mutation == "stale-rv":
        options["preconditions"]["resourceVersion"] = "old"
    elif mutation == "wrong-uid":
        options["preconditions"]["uid"] = "foreign"
    elif mutation == "wrong-node":
        username = "system:node:worker-b"
    elif mutation == "missing-node-group":
        groups = []
    elif mutation == "missing-delete-time":
        old["metadata"].pop("deletionTimestamp")
    elif mutation == "wrong-namespace":
        old["metadata"]["namespace"] = "foreign"
    elif mutation == "node-lost":
        old["status"]["reason"] = "NodeLost"
    elif mutation == "unknown-waiting":
        old["status"]["containerStatuses"] = [{"name": "app", "state": {"waiting": {"reason": "Unknown"}}}]
    review = request(old, operation="DELETE", old=old, options=options, username=username, groups=groups)
    if mutation == "wrong-request-name":
        review["request"]["name"] = "foreign"
    calls = []
    verifier = policy(lambda ref: calls.append(ref) or pytest.fail("kubelet DELETE must not call backend"))
    assert not allowed(verifier, review)
    assert not calls


@pytest.mark.parametrize("phase", ["Succeeded", "Failed"])
@pytest.mark.parametrize("omit_finalizers", [False, True])
def test_kubelet_zero_grace_after_finalizer_removal_requires_fresh_persisted_stop(
    template, plan, phase, omit_finalizers
):
    """F059 覆盖 AC: AC-13、AC-20、AC-31、AC-49、AC-52."""
    old = finished_pod(template, phase=phase, deleting=True)
    old["metadata"]["finalizers"] = []
    if omit_finalizers:
        old["metadata"].pop("finalizers")
    old["metadata"]["deletionGracePeriodSeconds"] = 30
    plan.update(stop_state="confirmed", stop_confirmed=True, cleanup_only=True)
    options = {"preconditions": {"uid": UID}, "gracePeriodSeconds": 0}
    review = request(
        old, operation="DELETE", old=old, options=options, username="system:node:worker-a", groups=["system:nodes"]
    )
    calls = []
    verifier = policy(lambda ref: calls.append(ref) or copy.deepcopy(plan))
    before = copy.deepcopy(old)
    assert allowed(verifier, review)
    assert calls == ["resource-a"] and old == before
    plan["allow_delete"] = False
    assert not allowed(verifier, review)
    assert calls == ["resource-a", "resource-a"]


@pytest.mark.parametrize(
    "mutation",
    [
        "missing-proof",
        "unconfirmed",
        "truthy-proof",
        "delete-refused",
        "truthy-delete",
        "wrong-ref",
        "wrong-namespace",
        "wrong-name",
        "wrong-kind",
        "wrong-plan-uid",
        "replacement-uid",
        "missing-ref",
        "missing-delete-time",
        "wrong-node",
        "missing-node-group",
        "missing-policy",
        "running",
        "unknown",
        "node-lost",
        "app-running",
        "unknown-termination",
        "waiting-id",
        "missing-rv",
        "stale-rv",
        "wrong-delete-uid",
        "missing-delete-uid",
        "nonzero-grace",
        "boolean-grace",
    ],
)
def test_finalizer_free_kubelet_delete_denies_unproven_or_changed_resources(template, plan, mutation):
    """F059 覆盖 AC: AC-13、AC-20、AC-31、AC-49、AC-52."""
    old = finished_pod(template, deleting=True)
    old["metadata"].pop("finalizers")
    plan.update(stop_state="confirmed", stop_confirmed=True, cleanup_only=True)
    options = {"preconditions": {"uid": UID, "resourceVersion": "17"}, "gracePeriodSeconds": 0}
    username, groups = "system:node:worker-a", ["system:nodes"]
    if mutation == "missing-proof":
        plan.pop("stop_confirmed")
    elif mutation == "unconfirmed":
        plan["stop_state"] = "requested"
    elif mutation == "truthy-proof":
        plan["stop_confirmed"] = "true"
    elif mutation in {"delete-refused", "truthy-delete"}:
        plan["allow_delete"] = False if mutation == "delete-refused" else "true"
    elif mutation.startswith("wrong-") and mutation.removeprefix("wrong-") in {
        "ref",
        "namespace",
        "name",
        "kind",
        "plan-uid",
    }:
        key = {"ref": "resource_ref", "plan-uid": "uid"}.get(mutation[6:], mutation[6:])
        plan[key] = "foreign"
    elif mutation == "replacement-uid":
        old["metadata"]["uid"] = "33333333-3333-4333-8333-333333333333"
        options["preconditions"]["uid"] = old["metadata"]["uid"]
    elif mutation == "missing-ref":
        old["metadata"]["labels"].pop(RESOURCE_LABEL)
    elif mutation == "missing-delete-time":
        old["metadata"].pop("deletionTimestamp")
    elif mutation == "wrong-node":
        username = "system:node:worker-b"
    elif mutation == "missing-node-group":
        groups = []
    elif mutation == "missing-policy":
        old["metadata"]["annotations"].pop(POLICY_ANNOTATION)
    elif mutation in {"running", "unknown"}:
        old["status"]["phase"] = mutation.title()
    elif mutation == "node-lost":
        old["status"]["reason"] = "NodeLost"
    elif mutation == "app-running":
        old["status"]["containerStatuses"][0]["state"] = {"running": {}}
    elif mutation == "unknown-termination":
        old["status"]["containerStatuses"][0]["state"]["terminated"]["reason"] = "ContainerStatusUnknown"
    elif mutation == "waiting-id":
        old["status"]["containerStatuses"][0]["state"] = {"waiting": {"reason": "PodInitializing"}}
    elif mutation == "missing-rv":
        old["metadata"].pop("resourceVersion")
        options["preconditions"].pop("resourceVersion")
    elif mutation == "stale-rv":
        options["preconditions"]["resourceVersion"] = "old"
    elif mutation == "wrong-delete-uid":
        options["preconditions"]["uid"] = "foreign"
    elif mutation == "missing-delete-uid":
        options["preconditions"].pop("uid")
    else:
        options["gracePeriodSeconds"] = 1 if mutation == "nonzero-grace" else False
    review = request(old, operation="DELETE", old=old, options=options, username=username, groups=groups)
    assert not allowed(policy(lambda _: plan), review)


@pytest.mark.parametrize("backend", ["unavailable", "invalid"])
def test_finalizer_free_kubelet_delete_fails_closed_when_backend_is_uncertain(template, backend):
    """F059 覆盖 AC: AC-13、AC-20、AC-31、AC-49、AC-52."""
    old = finished_pod(template, deleting=True)
    old["metadata"].pop("finalizers")
    options = {"preconditions": {"uid": UID}, "gracePeriodSeconds": 0}

    def reader(_):
        if backend == "unavailable":
            raise RuntimeError("sensitive-backend-detail")
        return None

    review = request(
        old, operation="DELETE", old=old, options=options, username="system:node:worker-a", groups=["system:nodes"]
    )
    result = policy(reader).review(review)
    assert not result["response"]["allowed"] and "sensitive-backend-detail" not in str(result)


def test_persisted_stop_does_not_relax_manager_zero_grace_or_status_authority(template, plan):
    """F059 覆盖 AC: AC-13、AC-20、AC-31、AC-49、AC-52."""
    old = finished_pod(template, deleting=True)
    old["metadata"].pop("finalizers")
    plan.update(stop_state="confirmed", stop_confirmed=True, cleanup_only=True)
    options = {"preconditions": {"uid": UID, "resourceVersion": "17"}, "gracePeriodSeconds": 0}
    assert not allowed(policy(lambda _: plan), request(old, operation="DELETE", old=old, options=options))
    before = copy.deepcopy(old)
    before["status"]["phase"] = "Running"
    assert not allowed(policy(lambda _: plan), request(old, operation="UPDATE", subresource="status", old=before))


def test_finalizer_free_cleanup_uses_a_new_backend_http_plan_for_every_review(template, plan, tmp_path):
    """F059 覆盖 AC: AC-13、AC-20、AC-31、AC-49、AC-52."""
    import httpx

    from runtime_manager.k8s_admission import AdmissionPlanClient

    old = finished_pod(template, deleting=True)
    old["metadata"].pop("finalizers")
    plan.update(stop_state="confirmed", stop_confirmed=True, cleanup_only=True)
    options = {"preconditions": {"uid": UID}, "gracePeriodSeconds": 0}
    review = request(
        old, operation="DELETE", old=old, options=options, username="system:node:worker-a", groups=["system:nodes"]
    )
    calls = []

    def handler(incoming):
        calls.append((incoming.method, incoming.url.path))
        return httpx.Response(200, json=copy.deepcopy(plan))

    key_file = tmp_path / "test-admission-key"
    key_file.write_text("x" * 32)
    client = AdmissionPlanClient(
        "https://backend.invalid", key_id="test", secret_file=key_file, transport=httpx.MockTransport(handler)
    )
    try:
        verifier = policy(client)
        assert allowed(verifier, review)
        plan["stop_confirmed"] = False
        assert not allowed(verifier, review)
        assert calls == [("GET", "/api/v1/internal/app-runtime/v2/admission/plans/resource-a")] * 2
    finally:
        client.close()
