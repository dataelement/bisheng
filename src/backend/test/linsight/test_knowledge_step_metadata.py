"""Candidate names require real type, tenant and batch visibility evidence."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


def _row(id, type=0, name="Library", tenant_id=2, user_id=8):
    return SimpleNamespace(id=id, type=type, name=name, tenant_id=tenant_id, user_id=user_id)


async def test_resolver_reloads_real_types_and_batches_visible_names():
    from bisheng.linsight.domain.services import knowledge_step_metadata as module

    rows = [_row(1), _row(2, type=3, name="Space"), _row(3, name="Hidden"), _row(4, type=2, name="Secret personal")]
    loader = AsyncMock(return_value=rows)

    async def check(user, *, resource_type, resource_ids, actions):
        assert actions == ("visible",)
        if resource_type == "knowledge_library":
            assert set(resource_ids) == {"1", "3"}
            return {"1": {"visible"}}
        assert resource_type == "knowledge_space"
        assert list(resource_ids) == ["2"]
        return {"2": {"visible"}}

    identity = SimpleNamespace(user_id=8, tenant_id=2, is_global_super=False)
    candidates = [_row(1, type=3, name="Forged"), *rows[1:]]
    targets = await module.KnowledgeStepMetadataResolver(load_rows=loader, check_actions=check).resolve(
        identity, candidates
    )
    assert targets == {
        "1": {"version": 1, "knowledge_id": "1", "kind": "knowledge_base", "name": "Library"},
        "2": {"version": 1, "knowledge_id": "2", "kind": "space", "name": "Space"},
        "4": {"version": 1, "knowledge_id": "4", "kind": "personal"},
    }


@pytest.mark.parametrize("identity", [None, SimpleNamespace(user_id=8, tenant_id=None)])
async def test_resolver_without_identity_has_no_display_evidence(identity):
    from bisheng.linsight.domain.services.knowledge_step_metadata import KnowledgeStepMetadataResolver

    assert await KnowledgeStepMetadataResolver().resolve(identity, [_row(1)]) == {}


async def test_lookup_failure_and_cross_tenant_candidates_fail_closed():
    from bisheng.linsight.domain.services.knowledge_step_metadata import KnowledgeStepMetadataResolver

    loader = AsyncMock(return_value=[_row(1, tenant_id=3)])
    check = AsyncMock(return_value={"1": {"visible"}})
    identity = SimpleNamespace(user_id=8, tenant_id=2)
    resolver = KnowledgeStepMetadataResolver(load_rows=loader, check_actions=check)
    assert await resolver.resolve(identity, [_row(1)]) == {}
    check.assert_not_awaited()
    loader.side_effect = RuntimeError("down")
    assert await resolver.resolve(identity, [_row(1)]) == {}
