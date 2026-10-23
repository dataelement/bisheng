"""覆盖 AC: AC-13、AC-30、AC-49."""

import copy
import logging

import pytest

from runtime_manager.k8s_admission import AdmissionPolicy, AdmissionRefused, template_projection
from runtime_manager.k8s_templates import PodPlan, pod_template

NAMESPACE = "bisheng-runtime-apps"
MANAGER = "system:serviceaccount:bisheng-system:runtime-manager"
LOGGER = "runtime_manager.k8s_admission"
PRIVATE_MARKER = "synthetic-sensitive-diagnostic-marker"


@pytest.fixture
def case():
    pod = pod_template(
        PodPlan(
            namespace=NAMESPACE,
            app_id="app-a",
            operation_id="operation-a",
            resource_ref="resource-a",
            node_id="node-a",
            generation=1,
            owner_epoch=1,
            purpose="probe",
            platform="linux/amd64",
            status_policy_revision="v1",
            image="example/runtime@sha256:" + "a" * 64,
            helper_image="example/helper@sha256:" + "b" * 64,
            command=("python", "main.py"),
            memory_mb=128,
            cpu_millicores=50,
            mode="image",
            deadline_seconds=60,
            env={"PRIVATE_VALUE": PRIVATE_MARKER},
        )
    )
    plan = {
        "resource_ref": "resource-a",
        "namespace": NAMESPACE,
        "name": pod["metadata"]["name"],
        "kind": "Pod",
        "template": template_projection(pod),
        "allow_create": True,
    }
    review = {
        "apiVersion": "admission.k8s.io/v1",
        "kind": "AdmissionReview",
        "request": {
            "uid": PRIVATE_MARKER + "-uid",
            "operation": "CREATE",
            "namespace": NAMESPACE,
            "name": pod["metadata"]["name"],
            "resource": {"group": "", "version": "v1", "resource": "pods"},
            "userInfo": {"username": MANAGER},
            "headers": {"Authorization": "Bearer " + PRIVATE_MARKER},
            "object": copy.deepcopy(pod),
        },
    }
    policy = AdmissionPolicy(
        namespace=NAMESPACE,
        manager_username=MANAGER,
        status_policy_revision="v1",
        plan_reader=lambda _: plan,
    )
    return policy, plan, review


def assert_safe_refusal_log(caplog, expected):
    records = [record for record in caplog.records if record.name == LOGGER]
    assert [record.getMessage() for record in records] == [expected]
    assert all(record.levelno == logging.WARNING for record in records)
    assert all(record.exc_info is None and record.stack_info is None for record in records)
    assert PRIVATE_MARKER not in caplog.text


@pytest.mark.parametrize(
    "change, reason",
    [
        ("template", "admission_template_mismatch"),
        ("action", "admission_plan_action_refused"),
        ("baseline", "admission_pod_baseline_refused"),
        ("actor", "admission_actor_refused"),
        ("plan-scope", "admission_plan_scope_refused"),
    ],
)
def test_real_policy_refusals_log_only_fixed_reason_and_keep_response(case, caplog, change, reason):
    policy, plan, review = case
    if change == "template":
        review["request"]["object"]["spec"]["containers"][0]["image"] = "example/other@sha256:" + "c" * 64
    elif change == "action":
        plan["allow_create"] = False
    elif change == "baseline":
        review["request"]["object"]["spec"]["hostNetwork"] = True
    elif change == "actor":
        review["request"]["userInfo"]["username"] = "system:serviceaccount:bisheng-system:untrusted"
    elif change == "plan-scope":
        plan["kind"] = "Service"
    caplog.set_level(logging.WARNING, logger=LOGGER)
    response = policy.review(review)
    assert response == {
        "apiVersion": "admission.k8s.io/v1",
        "kind": "AdmissionReview",
        "response": {
            "uid": review["request"]["uid"],
            "allowed": False,
            "status": {"code": 403, "message": reason},
        },
    }
    assert_safe_refusal_log(caplog, reason)


@pytest.mark.parametrize(
    "exception_type", [RuntimeError, AdmissionRefused, type(PRIVATE_MARKER, (AdmissionRefused,), {})]
)
def test_plan_reader_exception_text_and_type_cannot_enter_logs(case, caplog, exception_type):
    policy, _, review = case

    def unavailable(_):
        raise exception_type("token=" + PRIVATE_MARKER)

    policy.plan_reader = unavailable
    caplog.set_level(logging.WARNING, logger=LOGGER)
    response = policy.review(review)["response"]
    assert response == {
        "uid": review["request"]["uid"],
        "allowed": False,
        "status": {"code": 403, "message": "admission_plan_unavailable"},
    }
    assert_safe_refusal_log(caplog, "admission_plan_unavailable")


def test_reason_outside_logging_subset_uses_fixed_fallback_without_changing_response(case, caplog):
    policy, _, review = case
    review["request"]["namespace"] = "untrusted-namespace"
    caplog.set_level(logging.WARNING, logger=LOGGER)
    response = policy.review(review)["response"]
    assert response["status"] == {"code": 403, "message": "admission_namespace_refused"}
    assert_safe_refusal_log(caplog, "admission_refused")


def test_malformed_input_logs_fixed_reason_without_exception_details(case, caplog):
    policy, _, review = case
    review["request"]["resource"] = None
    caplog.set_level(logging.WARNING, logger=LOGGER)
    response = policy.review(review)["response"]
    assert response["status"] == {"code": 403, "message": "admission_input_invalid"}
    assert_safe_refusal_log(caplog, "admission_input_invalid")


def test_allowed_review_does_not_log_request_or_diagnostic_noise(case, caplog):
    policy, _, review = case
    caplog.set_level(logging.DEBUG, logger=LOGGER)
    assert policy.review(review)["response"] == {"uid": review["request"]["uid"], "allowed": True}
    assert not [record for record in caplog.records if record.name == LOGGER]
