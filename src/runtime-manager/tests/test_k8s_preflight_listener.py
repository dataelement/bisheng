"""Cold CRI work cannot spend the finite lifetime of a later network listener."""

import copy
from types import SimpleNamespace
from uuid import uuid4

import pytest

from tests.test_k8s_installation import load_installer, negative_probe_verifier

HELPER = "example/helper@sha256:" + "a" * 64
RUNTIME = "example/python@sha256:" + "b" * 64
RUNTIMES = (RUNTIME, *("example/python-" + digest + "@sha256:" + digest * 64 for digest in "def"))


def verifier_with_clock(tool):
    verifier = tool.InstallationVerifier.__new__(tool.InstallationVerifier)
    verifier.document = {
        "platform": "linux/amd64",
        "helper_image": HELPER,
        "status_policy_revision": "v1",
        "canary_profiles": [{"runtime_image": image, "command": ["python", "--version"]} for image in RUNTIMES],
    }
    verifier.options = {}
    verifier.namespace = "runtime-apps"
    verifier.timeout = 180
    verifier.created, verifier.control_created, verifier.idle = [], [], None
    clock, events = SimpleNamespace(value=0), []
    verifier.api = SimpleNamespace(get=lambda *_args, **_kwargs: {"status": {"nodeInfo": {"architecture": "amd64"}}})

    def create(pod):
        pod = copy.deepcopy(pod)
        pod["metadata"].update(uid=str(uuid4()), resourceVersion="1")
        pod["spec"]["nodeName"] = "worker-a"
        pod["status"] = {
            "phase": "Pending",
            "podIP": "192.0.2." + str(len(verifier.created) + 1),
            "containerStatuses": [{"imageID": "sha256:" + "c" * 64}],
        }
        verifier.created.append({"resource": "pods", "uid": pod["metadata"]["uid"], "pod": pod})
        events.append(("create", clock.value, pod))
        return pod

    def observe(pod, *, running=False):
        if pod["spec"]["containers"][0]["image"] in RUNTIMES:
            # Each pull is inside its 180-second wait; their total exceeds the
            # old listener's 600 seconds before network checks even begin.
            clock.value += 175
        pod["status"]["phase"] = "Running" if running else "Succeeded"
        events.append(("observe", clock.value, pod))
        return pod

    verifier._create, verifier._observe = create, observe
    return verifier, clock, events


def install_other_checks(verifier):
    proof = {"ok": True, "evidence": {"uid": str(uuid4())}}
    for name in ("_namespace_budget", "_binding_fence", "_rbac", "_storage", "_platform"):
        setattr(verifier, name, lambda *_args, **_kwargs: proof)
    for name in ("_admission_negative", "_status", "_no_exec"):
        setattr(verifier, name, lambda **_kwargs: verifier._proof(verifier.idle))

    def network(group):
        if group == "network-direct-denied":
            return verifier._proof(verifier._listener())
        return proof

    verifier._network = network
    verifier._control_probe = lambda *_args, **_kwargs: None


def test_live_verifies_real_cold_images_before_any_fresh_listener_is_created():
    tool = load_installer()
    verifier, clock, events = verifier_with_clock(tool)
    install_other_checks(verifier)
    cleaned = []
    verifier.cleanup = lambda: cleaned.extend(verifier.created)

    report = verifier.live()

    assert report["checks"][0]["name"] == "image-cri"
    assert all(row["ok"] for row in report["checks"])
    creates = [event for event in events if event[0] == "create"]
    assert creates[0][2]["spec"]["containers"][0]["command"] == ["python", "--version"]
    assert creates[0][2]["status"]["phase"] == "Succeeded"
    listeners = [event for event in creates if event[2]["spec"]["containers"][0]["command"][-1] == "idle"]
    assert len(listeners) == 6
    assert clock.value == 700 and all(event[1] == 700 for event in listeners)
    assert all(event[2]["spec"]["activeDeadlineSeconds"] == 600 for event in listeners)
    assert len({event[2]["metadata"]["uid"] for event in listeners}) == len(listeners)
    assert {row["uid"] for row in cleaned} == {event[2]["metadata"]["uid"] for event in creates}
    observations = report["artifacts"]["image-cri"]
    assert {row["image_ref"] for row in observations} == {HELPER, *RUNTIMES}
    assert {row["uid"] for row in observations} == {
        event[2]["metadata"]["uid"] for event in creates[: 1 + len(RUNTIMES)]
    }


def test_each_listener_consumer_gets_a_new_tracked_pod_after_previous_expiry():
    tool = load_installer()
    verifier, clock, _events = verifier_with_clock(tool)
    first = verifier._listener()
    clock.value += 900
    second = verifier._listener()
    assert first["metadata"]["uid"] != second["metadata"]["uid"]
    assert verifier.idle is second
    assert {row["uid"] for row in verifier.created} == {first["metadata"]["uid"], second["metadata"]["uid"]}
    assert first["spec"]["activeDeadlineSeconds"] == second["spec"]["activeDeadlineSeconds"] == 600


def test_failed_listener_does_not_run_consumer_or_use_the_old_pod():
    tool = load_installer()
    verifier, _clock, _events = verifier_with_clock(tool)
    first = verifier._listener()
    called = []

    def fail(_pod, **_kwargs):
        raise tool.ProbeError("preflight_pod_failed")

    verifier._observe = fail
    with pytest.raises(tool.ProbeError, match="preflight_pod_failed"):
        verifier._with_listener(lambda: called.append(True))
    assert not called
    assert verifier.idle is first
    assert len(verifier.created) == 2  # Failed new canary is still owned by cleanup.


def test_failed_image_check_remains_failed_while_other_checks_keep_real_evidence():
    tool = load_installer()
    verifier, _clock, _events = verifier_with_clock(tool)
    install_other_checks(verifier)
    verifier.document["canary_profiles"][0]["command"] = ["sh", "-c", "unapproved"]
    verifier.cleanup = lambda: None
    report = verifier.live()
    image = report["checks"][0]
    assert image["name"] == "image-cri" and image["ok"] is False and not image["evidence"]
    assert "image-cri" not in report["artifacts"]
    assert {row["name"] for row in report["checks"]} == tool.REQUIRED_CHECKS


def test_initial_helper_failure_preserves_original_cleanup_failure_classification():
    tool = load_installer()
    verifier, _clock, _events = verifier_with_clock(tool)
    install_other_checks(verifier)
    probe_error = tool.ProbeError("preflight_pod_failed")
    cleanup_error = tool.ProbeError("preflight_cleanup_identity_changed")

    def fail(*_args, **_kwargs):
        raise probe_error

    def cleanup():
        raise cleanup_error

    verifier._observe, verifier.cleanup = fail, cleanup
    with pytest.raises(tool.ProbeRunFailure) as caught:
        verifier.live()
    assert caught.value.probe_error is probe_error
    assert caught.value.cleanup_error is cleanup_error
    assert len(verifier.created) == 1


@pytest.mark.parametrize("psa", [False, True])
def test_admission_negative_copies_current_listener_plan_after_old_helper_plan_expires(monkeypatch, psa):
    tool = load_installer()
    verifier = negative_probe_verifier(tool, outcome="psa" if psa else "template")
    monkeypatch.setattr(tool.time, "time", lambda: 4001)
    current = verifier.created[0]
    current["plan"]["expires_at"] = 7501
    current["plan"]["template"]["spec"]["containers"][0]["command"] = [
        "python",
        "-I",
        "-m",
        "runtime_manager.k8s_capabilities",
        "idle",
    ]
    old = copy.deepcopy(current)
    old["uid"] = old["plan"]["uid"] = str(uuid4())
    old["name"] = old["plan"]["name"] = old["plan"]["template"]["metadata"]["name"] = "preflight-old-helper"
    old["plan"]["expires_at"] = 1000
    old["plan"]["template"]["spec"]["containers"][0]["command"] = ["python", "--version"]
    verifier.created.insert(0, old)
    before = copy.deepcopy(verifier.created)
    writes, publish = [], verifier._plans

    def plans(ref, plan=None, **kwargs):
        if plan is not None:
            writes.append(copy.deepcopy(plan))
        return publish(ref, plan, **kwargs)

    verifier._plans = plans
    result = verifier._admission_negative(psa=psa)

    assert result["evidence"]["uid"] == current["uid"]
    assert len(writes) == 1 and writes[0]["expires_at"] == 7501
    assert writes[0]["template"]["spec"]["containers"][0]["command"][-1] == "idle"
    assert verifier.created == before  # Never renew the expired historical approval.
    requests = [path for method, path, *_rest in verifier.calls if method == "POST"]
    assert len(requests) == 1 and requests[0].endswith("?dryRun=All")


@pytest.mark.parametrize(
    "change", ["absent", "record-uid", "plan-uid", "duplicate", "name", "namespace", "no-listener"]
)
def test_admission_negative_refuses_unconfirmed_listener_record_before_plan_or_dry_run(change):
    tool = load_installer()
    verifier = negative_probe_verifier(tool)
    if change == "absent":
        verifier.created.clear()
    elif change == "record-uid":
        verifier.created[0]["uid"] = str(uuid4())
    elif change == "plan-uid":
        verifier.created[0]["plan"]["uid"] = str(uuid4())
    elif change == "duplicate":
        verifier.created.append(copy.deepcopy(verifier.created[0]))
    elif change in {"name", "namespace"}:
        verifier.created[0]["plan"][change] = "unmatched"
    else:
        verifier.idle = None
    with pytest.raises(tool.ProbeError, match="admission_negative_unconfirmed"):
        verifier._admission_negative(psa=True)
    assert not verifier.calls
