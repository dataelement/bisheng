"""覆盖 AC: AC-04、AC-13、AC-15、AC-24、AC-25、AC-36、AC-48、AC-55.

Real manifest serialization, Kubernetes control service and SQL resource ledger.
No replacement of _validate_pod, register_resource or the delivery schema.
"""

import copy

import pytest

from bisheng.app_publish.domain.schemas.app_manifest import BundleDelivery, SourceImageDelivery
from bisheng.app_runtime.domain.models.runtime_kubernetes import RuntimeExecutionResource
from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import RuntimeConflict
from test.app_runtime.test_runtime_kubernetes_repository import repo as repo
from test.app_runtime.test_runtime_kubernetes_service import HELPER, IMAGE, MANAGER, REF, document, short_hash
from test.app_runtime.test_runtime_kubernetes_service import control as control

PREPARER = "example.invalid/preparer@sha256:" + "c" * 64
BUILT_IMAGE = "example.invalid/source-result@sha256:" + "d" * 64
FOREIGN_IMAGE = "example.invalid/foreign@sha256:" + "e" * 64
PROFILE = {
    "profile_id": "profile-a",
    "profile_revision": "f059-python@1",
    "platform": "linux/amd64",
    "language": "python3.11",
    "runtime_image": IMAGE,
    "preparer_image": PREPARER,
    "uid": 10001,
    "gid": 10001,
}


def manifest_delivery(reference="f059-python@1"):
    return BundleDelivery(profile=reference).model_dump(mode="json")


async def configure(control, *, kind, payload, purpose, image):
    svc, repository, operation = control
    operation.kind, operation.payload = kind, copy.deepcopy(payload)
    await repository.save(operation)
    body = document(operation, purpose=purpose)
    spec = body["template"]["spec"]
    if purpose in {"serve", "migrate", "restore", "data", "purge"}:
        body["template"]["metadata"]["name"] = "app-" + short_hash(operation.app_id)
        claim = "data-" + short_hash(operation.app_id)
        spec["volumes"] = [{"name": "data", "persistentVolumeClaim": {"claimName": claim}}]
    elif purpose.startswith("prepare-") or purpose == "assemble":
        claim = "scratch-" + short_hash(operation.id)
        spec["volumes"] = [{"name": "scratch", "persistentVolumeClaim": {"claimName": claim}}]
    else:
        spec["volumes"] = []
    spec["containers"][0].update(name="prepare" if purpose == "prepare-install" else "app", image=image)
    return svc, repository, operation, body


async def assert_registered(control, **kwargs):
    svc, repository, operation, body = await configure(control, **kwargs)
    result = await svc.register_resource(MANAGER, body)
    assert result["resource_ref"] == REF and result["uid"] is None
    row = await repository.get(RuntimeExecutionResource, REF)
    assert row.approved_template["spec"]["containers"][0]["image"] == kwargs["image"]
    assert row.operation_id == operation.id
    return row


async def assert_refused(control, *, reason, **kwargs):
    svc, repository, operation, body = await configure(control, **kwargs)
    with pytest.raises(RuntimeConflict, match="^" + reason + "$"):
        await svc.register_resource(MANAGER, body)
    assert await repository.find(RuntimeExecutionResource, operation_id=operation.id) == []


@pytest.mark.parametrize("reference", ["f059-python@1", None])
@pytest.mark.parametrize("stale_output", [False, True])
async def test_prepare_uses_resolved_payload_profile_with_real_manifest(control, reference, stale_output):
    payload = {"delivery": manifest_delivery(reference), "profile": copy.deepcopy(PROFILE)}
    assert payload["delivery"]["profile"] == reference
    if stale_output:
        payload["resolved_delivery"] = {
            "mode": "bundle",
            "profile": {"runtime_image": FOREIGN_IMAGE, "preparer_image": FOREIGN_IMAGE},
        }
    await assert_registered(control, kind="prepare", payload=payload, purpose="prepare-install", image=PREPARER)


async def test_runtime_uses_only_the_frozen_delivery_profile(control):
    payload = {
        "delivery": manifest_delivery("stale@99"),
        "profile": {"runtime_image": FOREIGN_IMAGE, "preparer_image": FOREIGN_IMAGE},
        "resolved_delivery": {"mode": "bundle", "profile": copy.deepcopy(PROFILE)},
    }
    await assert_registered(control, kind="deploy", payload=payload, purpose="serve", image=IMAGE)


@pytest.mark.parametrize("kind", ["prepare", "deploy"])
@pytest.mark.parametrize("invalid", ["bundle", ["bundle"], None])
async def test_nonoptional_delivery_container_is_rejected_before_resource_persistence(control, kind, invalid):
    payload = {
        "delivery": manifest_delivery(),
        "profile": copy.deepcopy(PROFILE),
        "resolved_delivery": {"mode": "bundle", "profile": copy.deepcopy(PROFILE)},
    }
    payload["delivery" if kind == "prepare" else "resolved_delivery"] = invalid
    await assert_refused(
        control,
        reason="resource_delivery_invalid",
        kind=kind,
        payload=payload,
        purpose="prepare-install" if kind == "prepare" else "serve",
        image=PREPARER if kind == "prepare" else IMAGE,
    )


@pytest.mark.parametrize("kind", ["prepare", "deploy"])
@pytest.mark.parametrize("invalid", ["f059-python@1", ["profile"], None, {}])
async def test_nonoptional_profile_object_is_rejected_instead_of_falling_back(control, kind, invalid):
    payload = {
        "delivery": manifest_delivery(),
        "profile": copy.deepcopy(PROFILE),
        "resolved_delivery": {"mode": "bundle", "profile": copy.deepcopy(PROFILE)},
    }
    if kind == "prepare":
        payload["profile"] = invalid
    else:
        payload["resolved_delivery"]["profile"] = invalid
    await assert_refused(
        control,
        reason="resource_profile_invalid",
        kind=kind,
        payload=payload,
        purpose="prepare-install" if kind == "prepare" else "serve",
        image=PREPARER if kind == "prepare" else IMAGE,
    )


@pytest.mark.parametrize("explicit_none", [False, True])
async def test_complete_image_allows_absent_profile_without_trusting_stale_prepare_profile(control, explicit_none):
    delivery = {"mode": "image", "image_ref": BUILT_IMAGE}
    if explicit_none:
        delivery["profile"] = None
    payload = {"resolved_delivery": delivery, "profile": {"runtime_image": FOREIGN_IMAGE}}
    await assert_registered(control, kind="deploy", payload=payload, purpose="serve", image=BUILT_IMAGE)


@pytest.mark.parametrize("kind,purpose", [("deploy", "serve"), ("destroy", "purge")])
@pytest.mark.parametrize("invalid", ["profile-ref", ["profile"]])
async def test_optional_profile_still_rejects_an_explicit_wrong_type(control, kind, purpose, invalid):
    payload = {
        "purge_volume": True,
        "resolved_delivery": {"mode": "image", "image_ref": BUILT_IMAGE, "profile": invalid},
    }
    await assert_refused(
        control,
        reason="resource_profile_invalid",
        kind=kind,
        payload=payload,
        purpose=purpose,
        image=BUILT_IMAGE if kind == "deploy" else HELPER,
    )


@pytest.mark.parametrize("state", ["missing", "null", "optional-map"])
async def test_purge_allows_no_application_delivery_or_profile(control, state):
    payload = {"purge_volume": True}
    if state != "missing":
        payload["resolved_delivery"] = None if state == "null" else {"mode": "image", "profile": None}
    await assert_registered(control, kind="destroy", payload=payload, purpose="purge", image=HELPER)


@pytest.mark.parametrize("mode", ["bundle", "image", "purge"])
async def test_optional_profile_never_widens_the_application_image_allowlist(control, mode):
    payload = {
        "delivery": manifest_delivery(),
        "profile": {"runtime_image": FOREIGN_IMAGE, "preparer_image": FOREIGN_IMAGE},
    }
    if mode != "purge":
        payload["resolved_delivery"] = {"mode": mode, "image_ref": BUILT_IMAGE}
        if mode == "bundle":
            payload["resolved_delivery"]["profile"] = copy.deepcopy(PROFILE)
    else:
        payload["purge_volume"] = True
    await assert_refused(
        control,
        reason="resource_image_not_frozen",
        kind="destroy" if mode == "purge" else "deploy",
        payload=payload,
        purpose="purge" if mode == "purge" else "serve",
        image=FOREIGN_IMAGE,
    )


async def test_source_image_preparation_uses_its_resolved_preparer(control):
    payload = {
        "delivery": SourceImageDelivery(mode="source-image").model_dump(mode="json"),
        "profile": copy.deepcopy(PROFILE),
        "resolved_delivery": {"mode": "source-image", "image_ref": FOREIGN_IMAGE},
    }
    await assert_registered(control, kind="prepare", payload=payload, purpose="prepare-install", image=PREPARER)


async def test_source_image_runtime_keeps_the_frozen_result_image(control):
    payload = {
        "profile": {"runtime_image": FOREIGN_IMAGE, "preparer_image": FOREIGN_IMAGE},
        "resolved_delivery": {"mode": "source-image", "image_ref": BUILT_IMAGE, "profile": copy.deepcopy(PROFILE)},
    }
    await assert_registered(control, kind="deploy", payload=payload, purpose="serve", image=BUILT_IMAGE)


async def test_runtime_does_not_allow_a_preparer_from_an_unfrozen_top_level_profile(control):
    payload = {
        "profile": {"runtime_image": FOREIGN_IMAGE, "preparer_image": FOREIGN_IMAGE},
        "resolved_delivery": {"mode": "source-image", "image_ref": BUILT_IMAGE, "profile": copy.deepcopy(PROFILE)},
    }
    await assert_refused(
        control,
        reason="resource_image_not_frozen",
        kind="deploy",
        payload=payload,
        purpose="serve",
        image=FOREIGN_IMAGE,
    )


@pytest.mark.parametrize("invalid", ["image", ["image"]])
async def test_purge_does_not_accept_an_explicit_nonobject_delivery(control, invalid):
    await assert_refused(
        control,
        reason="resource_delivery_invalid",
        kind="destroy",
        purpose="purge",
        image=HELPER,
        payload={"purge_volume": True, "resolved_delivery": invalid},
    )


async def test_source_image_preparation_does_not_trust_a_stale_resolved_result_image(control):
    payload = {
        "delivery": SourceImageDelivery(mode="source-image").model_dump(mode="json"),
        "profile": copy.deepcopy(PROFILE),
        "resolved_delivery": {"mode": "source-image", "image_ref": FOREIGN_IMAGE},
    }
    await assert_refused(
        control,
        reason="resource_image_not_frozen",
        kind="prepare",
        payload=payload,
        purpose="prepare-install",
        image=FOREIGN_IMAGE,
    )
