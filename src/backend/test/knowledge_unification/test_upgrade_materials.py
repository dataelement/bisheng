import hashlib
import json

import pytest

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.knowledge.application.unification_upgrade_materials import UpgradeMaterials


def test_private_content_addressed_materials_and_atomic_active_binding(tmp_path):
    materials = UpgradeMaterials(tmp_path / "materials", run_id="upgrade-1")
    value = {"schema_version": 1, "run_id": "upgrade-1", "kind": "upgrade_flow", "records": [{"ready": True}]}
    ref = materials.write_object("upgrade_flow", value)
    assert materials.read_object(ref, kind="upgrade_flow") == value
    assert (materials.root / "objects" / (ref["sha256"] + ".json")).stat().st_mode & 0o777 == 0o600
    materials.activate(ref)
    assert materials.active() == ref
    content = (materials.root / "objects" / (ref["sha256"] + ".json")).read_bytes()
    assert hashlib.sha256(content).hexdigest() == ref["sha256"]
    assert content == json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def test_materials_reject_tamper_cross_run_and_symlink(tmp_path):
    materials = UpgradeMaterials(tmp_path / "m", run_id="upgrade-1")
    value = {"schema_version": 1, "run_id": "upgrade-1", "kind": "upgrade_flow", "records": []}
    ref = materials.write_object("upgrade_flow", value)
    materials.activate(ref)
    with pytest.raises(KnowledgeOperationPlanConflictError):
        UpgradeMaterials(tmp_path / "m", run_id="other").active()
    (materials.root / "objects" / (ref["sha256"] + ".json")).write_text("{}")
    with pytest.raises(KnowledgeOperationPlanConflictError):
        materials.read_object(ref, kind="upgrade_flow")
    destination = tmp_path / "outside"
    destination.mkdir()
    (tmp_path / "linked").symlink_to(destination, target_is_directory=True)
    with pytest.raises(KnowledgeOperationPlanConflictError):
        UpgradeMaterials(tmp_path / "linked", run_id="upgrade-1")


def test_missing_active_material_is_explicit(tmp_path):
    materials = UpgradeMaterials(tmp_path / "m", run_id="upgrade-1")
    assert materials.active(required=False) is None
    with pytest.raises(KnowledgeOperationPlanConflictError):
        materials.active()
