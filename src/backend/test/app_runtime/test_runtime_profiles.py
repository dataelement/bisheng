"""Environment revisions and administrative shortcuts have explicit boundaries."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from test.app_runtime.test_runtime_delivery_repository import runtime_repo as runtime_repo


def definition(revision=1):
    d = "sha256:" + "a" * 64
    image = {
        "runtime_image": "example/runtime@" + d,
        "runtime_digest": d,
        "runtime_image_id": d,
        "preparer_image": "example/preparer@" + d,
        "preparer_digest": d,
        "preparer_image_id": d,
        "abi": "cp311-linux",
        "toolchain": {"pip": "24.0"},
    }
    return {
        "code": "python311-standard",
        "revision": revision,
        "language": "python3.11",
        "official": True,
        "platforms": {"linux/amd64": image, "linux/arm64": deepcopy(image)},
    }


@pytest.fixture
def actors(monkeypatch):
    from bisheng.app_runtime.domain.services import runtime_profile_service as mod

    async def identity(actor):
        return actor

    monkeypatch.setattr(mod, "resolve_permission_actor", identity)
    return SimpleNamespace(
        admin=SimpleNamespace(subject_type="user", subject_id=2, tenant_id=1, super_admin=True),
        owner=SimpleNamespace(subject_type="user", subject_id=10, tenant_id=1, super_admin=False),
        sak=SimpleNamespace(subject_type="service_account", subject_id=10, tenant_id=1, super_admin=False),
    )


async def test_immutable_revision_and_default_freeze(runtime_repo, actors):
    """AC-14, AC-15, AC-16: defaults change future resolution, not old revisions."""
    from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import RuntimeConflict
    from bisheng.app_runtime.domain.services.runtime_profile_service import RuntimeProfileService

    service = RuntimeProfileService(runtime_repo)
    a = await service.import_revision(definition(), actor=actors.admin)
    await service.set_default("python3.11", a.id, expected_generation=0, actor=actors.admin)
    frozen = await service.resolve("python3.11", None, "linux/arm64")
    b = await service.import_revision(definition(2), actor=actors.admin)
    await service.set_default("python3.11", b.id, expected_generation=1, actor=actors.admin)
    assert (await service.resolve("python3.11", None, "linux/arm64"))["profile_id"] == b.id
    assert frozen["profile_id"] == a.id
    changed = definition()
    changed["platforms"]["linux/arm64"]["abi"] = "incompatible"
    with pytest.raises(RuntimeConflict, match="immutable"):
        await service.import_revision(changed, actor=actors.admin)


async def test_only_superadmin_manages_global_catalog(runtime_repo, actors):
    """AC-14, AC-30: owner and service account do not become global admins."""
    from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import RuntimeConflict
    from bisheng.app_runtime.domain.services.runtime_profile_service import RuntimeProfileService

    service = RuntimeProfileService(runtime_repo)
    for actor in [actors.owner, actors.sak]:
        with pytest.raises(RuntimeConflict, match="super_admin"):
            await service.import_revision(definition(), actor=actor)


def test_official_delivery_requires_both_architectures():
    """AC-31, AC-55: amd64-only is not a successful official release."""
    from pydantic import ValidationError

    from bisheng.app_runtime.domain.schemas.runtime_delivery import RuntimeProfileDefinition

    body = definition()
    del body["platforms"]["linux/arm64"]
    with pytest.raises(ValidationError):
        RuntimeProfileDefinition.model_validate(body)


def test_private_material_and_restore_owner_guard(actors):
    """AC-30, AC-45: admin status never grants another owner's data action."""
    from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import RuntimeConflict
    from bisheng.app_runtime.domain.services.runtime_profile_service import require_natural_owner

    app = SimpleNamespace(tenant_id=1, owner_user_id=10)
    require_natural_owner(app, actors.owner)
    for actor in [
        actors.admin,
        actors.sak,
        SimpleNamespace(subject_type="user", subject_id=10, tenant_id=2, super_admin=True),
    ]:
        with pytest.raises(RuntimeConflict, match="owner"):
            require_natural_owner(app, actor)


def test_offline_catalog_export_matches_backend_normalized_identity():
    """AC-27, AC-55: a factory pack can address the same profile before customer import."""
    import importlib.util
    from pathlib import Path

    from bisheng.app_runtime.domain.schemas.runtime_delivery import RuntimeProfileDefinition
    from bisheng.app_runtime.domain.services.runtime_protocol import content_digest

    script = Path(__file__).parents[3] / "runtime-manager/tools/runtime_materials.py"
    spec = importlib.util.spec_from_file_location("runtime_materials_contract", script)
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    body = definition()
    exported = tool.export_profile({"profiles": [body]}, "python311-standard@1", "linux/arm64")
    expected = content_digest(RuntimeProfileDefinition.model_validate(body).model_dump(mode="json"))
    assert exported["profile_digest"] == expected
    assert exported["profile_id"] == expected[:32]
