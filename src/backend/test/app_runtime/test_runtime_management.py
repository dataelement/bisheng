"""覆盖 AC: AC-07、AC-14、AC-15、AC-30、AC-45、AC-53。"""

import hashlib
import io
import json
import tarfile
from types import SimpleNamespace

import pytest

from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import RuntimeConflict
from bisheng.app_runtime.domain.services import runtime_profile_service
from bisheng.app_runtime.domain.services.runtime_offline_package import validate_offline_package


@pytest.mark.parametrize(
    "identity",
    [
        SimpleNamespace(subject_type="service_account", subject_id=10, tenant_id=1, super_admin=True),
        SimpleNamespace(subject_type="user", subject_id=11, tenant_id=1, super_admin=False),
        SimpleNamespace(subject_type="user", subject_id=10, tenant_id=2, super_admin=False),
    ],
)
async def test_non_super_identities_cannot_change_global_runtime_catalog(identity, monkeypatch):
    async def resolve(_actor):
        return identity

    monkeypatch.setattr(runtime_profile_service, "resolve_permission_actor", resolve)
    with pytest.raises(RuntimeConflict, match="platform_super_admin_required"):
        await runtime_profile_service.require_platform_super(object())


async def test_platform_super_can_manage_global_runtime_catalog(monkeypatch):
    identity = SimpleNamespace(subject_type="user", subject_id=10, tenant_id=1, super_admin=True)

    async def resolve(_actor):
        return identity

    monkeypatch.setattr(runtime_profile_service, "resolve_permission_actor", resolve)
    assert await runtime_profile_service.require_platform_super(object()) is identity


def test_package_content_and_abi_are_verified(tmp_path):
    data = b"offline"
    profile = {"profile_id": "id", "profile_digest": "digest", "platform": "linux/arm64", "abi": "cp311"}
    metadata = {
        "schema_version": 1,
        **profile,
        "files": {"wheels/one.whl": {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}},
    }
    path = tmp_path / "offline.tar.gz"
    with tarfile.open(path, "w:gz") as archive:
        for name, body in [("wheels/one.whl", data), ("offline.json", json.dumps(metadata).encode())]:
            item = tarfile.TarInfo(name)
            item.size = len(body)
            archive.addfile(item, io.BytesIO(body))
    assert validate_offline_package(path, profile) == metadata
    with pytest.raises(RuntimeConflict, match="incompatible"):
        validate_offline_package(path, {**profile, "abi": "different"})
