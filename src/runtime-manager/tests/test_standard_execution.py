"""F008 AC-16/17/19: parameters affect real templates without widening safety."""

from dataclasses import replace

import pytest

from runtime_manager.k8s_templates import pod_template, pvc_template
from tests.test_k8s_templates import plan as plan


def test_nondefault_helpers_and_node_placement_reach_real_pod(plan):
    configured = replace(
        plan,
        helper_resources={
            "sidecar": {"memory_mb": 192, "cpu_millicores": 75},
            "init": {"memory_mb": 160, "cpu_millicores": 40},
        },
        placement={"nodeSelector": {"pool": "applications"}, "tolerations": [{"key": "app", "operator": "Exists"}]},
    )
    spec = pod_template(configured)["spec"]
    assert spec["nodeSelector"] == {"kubernetes.io/os": "linux", "kubernetes.io/arch": "amd64", "pool": "applications"}
    assert spec["tolerations"][-1]["key"] == "app"
    sidecar = next(c for c in spec["containers"] if c["name"] == "data-helper")
    assert sidecar["resources"]["requests"]["memory"] == "192Mi"
    assert sidecar["resources"]["requests"] == sidecar["resources"]["limits"]
    assert spec["initContainers"][0]["resources"]["requests"]["cpu"] == "40m"


@pytest.mark.parametrize("placement", [{"nodeName": "some-node"}, {"nodeSelector": {"kubernetes.io/arch": "arm64"}}])
def test_placement_cannot_bypass_platform_selection(plan, placement):
    with pytest.raises(ValueError):
        pod_template(replace(plan, placement=placement))


@pytest.mark.parametrize("value,present", [(None, False), ("", True), ("bounded-ext4", True)])
def test_storage_class_three_states(plan, value, present):
    spec = pvc_template(plan, name="data-test", size_mb=1024, storage_class=value)["spec"]
    assert ("storageClassName" in spec) is present
    if present:
        assert spec["storageClassName"] == value


def test_health_timeout_reaches_kubelet_startup_probe(plan):
    configured = replace(plan, timeouts={"health": 180})
    app = next(c for c in pod_template(configured)["spec"]["containers"] if c["name"] == "app")
    assert app["startupProbe"]["periodSeconds"] * app["startupProbe"]["failureThreshold"] == 180
