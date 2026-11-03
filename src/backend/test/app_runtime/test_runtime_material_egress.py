"""覆盖 AC: AC-07、AC-12、AC-15、AC-21、AC-23、AC-46、AC-47、AC-53."""

from datetime import UTC

import pytest

from bisheng.app_runtime.domain.models.runtime_delivery import RuntimeArtifact, RuntimeNode
from bisheng.app_runtime.domain.models.runtime_kubernetes import RuntimeMaterialDelegation
from bisheng.app_runtime.domain.services.runtime_protocol import ServiceIdentity
from test.app_runtime.test_runtime_material_service import bind, create, reframe, serving
from test.app_runtime.test_runtime_material_service import control as control
from test.app_runtime.test_runtime_material_service import materials as materials
from test.app_runtime.test_runtime_material_service import repo as repo

EGRESS = ServiceIdentity("egress", "node-a", ("egress",))


@pytest.fixture
async def policies(materials):
    from bisheng.app_runtime.domain.services.runtime_material_policy_service import RuntimeMaterialPolicyService

    return RuntimeMaterialPolicyService(
        materials.repo,
        materials=materials.svc,
        platform_origin="https://platform.example:8443",
        clock=lambda: materials.clock["now"],
    )


async def test_material_identity_survives_completed_prepare_and_tracks_current_serving_owner(materials, policies):
    grant = await create(materials)
    await bind(materials, grant)
    await serving(materials)
    rows = await policies.policies(EGRESS)
    assert len(rows) == 1 and rows[0]["principal"] == grant["proxy"]["principal"]
    assert (
        rows[0]["credential_hash"]
        == (await materials.repo.get(RuntimeMaterialDelegation, grant["delegation_id"])).proxy_credential_hash
    )
    assert rows[0]["destinations"] == [{"host": "platform.example", "ports": [8443], "trusted": True}]
    assert rows[0]["not_after"] <= materials.clock["now"].replace(tzinfo=UTC).timestamp() + 5
    assert grant["proxy"]["token"] not in str(rows) and "private_key" not in str(rows)
    materials.app.state = "deleted"
    assert await policies.policies(EGRESS) == []


async def test_revocation_and_wrong_node_are_not_projected(materials, policies):
    grant = await create(materials)
    await bind(materials, grant)
    assert await policies.policies(ServiceIdentity("egress-b", "node-b", ("egress",))) == []
    row = await materials.repo.get(RuntimeMaterialDelegation, grant["delegation_id"])
    row.revoked_at = materials.clock["now"]
    await materials.repo.save(row)
    assert await policies.policies(EGRESS) == []


async def test_only_prepare_download_can_reach_configured_package_endpoints(materials, policies):
    await reframe(materials, "prepare", "prepare-download")
    source = await materials.repo.save(
        RuntimeArtifact(
            tenant_id=1,
            app_id=materials.op.app_id,
            scope_key="1/" + materials.op.app_id,
            kind="source",
            sha256="a" * 64,
            size_bytes=0,
            object_key="fixture/source",
            state="verified",
            confirmed_at=materials.clock["now"],
        )
    )
    materials.op.payload = {**materials.op.payload, "offline": False, "source_artifact_id": source.id}
    await materials.repo.save(materials.op)
    node = await materials.repo.get(RuntimeNode, "node-a")
    node.capabilities = {**node.capabilities, "package_sources": ["https://packages.example/simple"]}
    await materials.repo.save(node)
    grant = await create(materials)
    await bind(materials, grant)
    rows = await policies.policies(EGRESS)
    assert {x["host"] for x in rows[0]["destinations"]} == {"platform.example", "packages.example"}
    materials.op.payload = {**materials.op.payload, "offline": True}
    await materials.repo.save(materials.op)
    rows = await policies.policies(EGRESS)
    assert {x["host"] for x in rows[0]["destinations"]} == {"platform.example"}


async def test_operation_service_egress_projection_includes_material_rows(materials, policies, monkeypatch):
    from bisheng.app_runtime.domain.services import runtime_operation_service as mod

    grant = await create(materials)
    await bind(materials, grant)
    monkeypatch.setattr(
        "bisheng.app_runtime.domain.services.runtime_material_policy_service.RuntimeMaterialPolicyService",
        lambda *a, **k: policies,
    )
    result = await mod.RuntimeOperationService(materials.repo, clock=lambda: materials.clock["now"]).policies(EGRESS)
    assert any(row["principal"] == grant["proxy"]["principal"] for row in result["policies"])
