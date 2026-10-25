"""覆盖 AC: AC-07、AC-14、AC-15、AC-30、AC-45、AC-53。"""

import hashlib
import io
import json
import tarfile
from types import SimpleNamespace

import pytest

from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import RuntimeConflict
from bisheng.app_runtime.domain.services.runtime_offline_package import validate_offline_package
from bisheng.app_runtime.domain.services.runtime_profile_service import require_natural_owner


@pytest.mark.parametrize(
    "identity",
    [
        SimpleNamespace(subject_type="service_account", subject_id=10, tenant_id=1),
        SimpleNamespace(subject_type="user", subject_id=11, tenant_id=1),
        SimpleNamespace(subject_type="user", subject_id=10, tenant_id=2),
    ],
)
def test_admin_service_and_foreign_identities_cannot_take_owner_actions(identity):
    with pytest.raises(RuntimeConflict, match="natural_owner"):
        require_natural_owner(SimpleNamespace(owner_user_id=10, tenant_id=1), identity)


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
