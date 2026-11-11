"""F008 AC-13/14/15: official seeds never invent an administrator."""

import hashlib
import json

import pytest

from bisheng.app_runtime.domain.repositories.runtime_delivery_repository import RuntimeConflict
from bisheng.app_runtime.domain.services.system_profile_service import seed_official_catalog
from test.app_runtime.test_runtime_delivery_repository import runtime_repo as runtime_repo
from test.app_runtime.test_runtime_profiles import definition


def catalog(tmp_path, documents):
    raw = json.dumps({"profiles": documents, "defaults": {"python3.11": "python311-standard@1"}}).encode()
    (tmp_path / "catalog.json").write_bytes(raw)
    (tmp_path / "catalog.lock.json").write_text(
        json.dumps({"schema_version": 1, "release": "3.1.0-beta1", "catalog_sha256": hashlib.sha256(raw).hexdigest()})
    )
    return tmp_path


async def test_system_seed_has_no_fake_user_and_is_idempotent(runtime_repo, tmp_path):
    from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeProfile, RuntimeProfileDefault

    root = catalog(tmp_path, [definition()])
    await seed_official_catalog(root, repository=runtime_repo)
    rows = await runtime_repo.find(RuntimeProfile)
    assert len(rows) == 1 and rows[0].created_by is None and rows[0].origin == "system"
    defaults = await runtime_repo.find(RuntimeProfileDefault)
    defaults[0].generation = 7
    await runtime_repo.save(defaults[0])
    await seed_official_catalog(root, repository=runtime_repo)
    assert len(await runtime_repo.find(RuntimeProfile)) == 1
    assert (await runtime_repo.find(RuntimeProfileDefault))[0].generation == 7


async def test_catalog_conflict_and_tampering_fail(runtime_repo, tmp_path):
    root = catalog(tmp_path, [definition()])
    await seed_official_catalog(root, repository=runtime_repo)
    changed = definition()
    changed["platforms"]["linux/amd64"]["abi"] = "changed"
    catalog(tmp_path, [changed])
    with pytest.raises(RuntimeConflict, match="immutable"):
        await seed_official_catalog(root, repository=runtime_repo)
    (root / "catalog.json").write_text("{}")
    with pytest.raises(RuntimeConflict, match="catalog"):
        await seed_official_catalog(root, repository=runtime_repo)


def test_public_release_profile_schema_matches_actual_product_model():
    from pathlib import Path

    from pydantic import ValidationError

    from bisheng.app_runtime.domain.schemas.runtime_delivery import RuntimeProfileDefinition

    root = Path(__file__).parents[4]
    schema = json.loads((root / "docker/helm/bisheng/files/runtime-profile.schema.json").read_text())
    assert schema == RuntimeProfileDefinition.model_json_schema()
    with pytest.raises(ValidationError):
        RuntimeProfileDefinition.model_validate({**definition(), "origin": "system"})
