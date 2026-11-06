"""覆盖 AC: AC-15、AC-23、AC-46、AC-47、AC-48、AC-53. Current outbound candidates only."""

from datetime import timedelta

from bisheng.app_runtime.domain.models.runtime_kubernetes import RuntimeExecutionResource, RuntimeMaterialDelegation
from test.app_runtime.test_runtime_material_service import bind, create
from test.app_runtime.test_runtime_material_service import control as control
from test.app_runtime.test_runtime_material_service import materials as materials
from test.app_runtime.test_runtime_material_service import repo as repo


async def test_candidates_exclude_unbound_stopped_revoked_and_other_nodes(materials):
    c = materials
    grant = await create(c)
    assert await c.repo.material_policy_candidates("node-a", c.clock["now"]) == []
    await bind(c, grant)
    assert [r.id for r in await c.repo.material_policy_candidates("node-a", c.clock["now"])] == [grant["delegation_id"]]
    assert await c.repo.material_policy_candidates("node-b", c.clock["now"]) == []
    row = await c.repo.get(RuntimeMaterialDelegation, grant["delegation_id"])
    row.revoked_at = c.clock["now"]
    await c.repo.save(row)
    assert await c.repo.material_policy_candidates("node-a", c.clock["now"]) == []
    row.revoked_at = None
    row.expires_at = c.clock["now"] - timedelta(seconds=1)
    await c.repo.save(row)
    assert await c.repo.material_policy_candidates("node-a", c.clock["now"]) == []
    row.expires_at = None
    await c.repo.save(row)
    resource = await c.repo.get(RuntimeExecutionResource, c.body["exec_ref"])
    resource.stop_requested_at = c.clock["now"]
    await c.repo.save(resource)
    assert await c.repo.material_policy_candidates("node-a", c.clock["now"]) == []
    assert (await c.repo.get(RuntimeMaterialDelegation, row.id)).id == row.id
