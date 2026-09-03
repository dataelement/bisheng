"""Role-configurable cap on how many Knowledge Spaces a user may create.

Before this, `_MAX_SPACE_PER_USER = 30` sat in the service module and won over
the role quota: lowering `quota_config.knowledge_space` worked, raising it (or
setting -1) did nothing. These tests pin the new behaviour, above all that
raising the quota actually raises the ceiling.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.common.errcode.knowledge_space import SpaceLimitError
from bisheng.common.errcode.llm import WorkbenchEmbeddingError
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService

_SVC = "bisheng.knowledge.domain.services.knowledge_space_service"
_QUOTA = "bisheng.role.domain.services.quota_service"


def _make_role(role_id, quota_config=None):
    role = MagicMock()
    role.id = role_id
    role.quota_config = quota_config
    return role


def _make_user_role(role_id):
    ur = MagicMock()
    ur.role_id = role_id
    return ur


def _make_tenant(tenant_id=1, quota_config=None):
    t = MagicMock()
    t.id = tenant_id
    t.quota_config = quota_config
    return t


def _make_user(user_id=10, tenant_id=1, is_admin=False):
    user = MagicMock()
    user.user_id = user_id
    user.tenant_id = tenant_id
    user.is_admin.return_value = is_admin
    return user


def _service(user=None) -> KnowledgeSpaceService:
    return KnowledgeSpaceService(request=MagicMock(), login_user=user or _make_user())


async def _effective(quota_config, resource="knowledge_space", **kw):
    from bisheng.role.domain.services.quota_service import QuotaService

    roles = kw.get("roles") or [_make_role(3, quota_config)]
    user_roles = [_make_user_role(r.id) for r in roles]
    with (
        patch(f"{_QUOTA}.UserRoleDao") as ur,
        patch(f"{_QUOTA}.RoleDao") as rd,
        patch(f"{_QUOTA}.TenantDao") as td,
    ):
        ur.aget_user_roles = AsyncMock(return_value=user_roles)
        rd.aget_role_by_ids = AsyncMock(return_value=roles)
        td.aget_by_id = AsyncMock(return_value=_make_tenant(quota_config=kw.get("tenant_quota")))
        return await QuotaService.get_effective_quota(
            user_id=10,
            resource_type=resource,
            tenant_id=1,
            login_user=kw.get("login_user") or _make_user(),
        )


class TestEffectiveQuota:
    def test_default_is_50(self):
        from bisheng.role.domain.services.quota_service import (
            DEFAULT_ROLE_QUOTA,
            QuotaResourceType,
        )

        assert QuotaResourceType.KNOWLEDGE_SPACE == "knowledge_space"
        assert DEFAULT_ROLE_QUOTA["knowledge_space"] == 50

    async def test_role_quota_raises_the_ceiling(self):
        """The regression this whole change is about: 100 must mean 100, not 30."""
        assert await _effective({"knowledge_space": 100}) == 100

    async def test_role_quota_lowers_the_ceiling(self):
        assert await _effective({"knowledge_space": 2}) == 2

    async def test_role_unlimited(self):
        assert await _effective({"knowledge_space": -1}) == -1

    async def test_missing_key_falls_back_to_default(self):
        assert await _effective({"channel": 5}) == 50

    async def test_multi_role_takes_max(self):
        roles = [_make_role(3, {"knowledge_space": 10}), _make_role(4, {"knowledge_space": 80})]
        assert await _effective(None, roles=roles) == 80

    async def test_admin_is_unlimited(self):
        from bisheng.role.domain.services.quota_service import QuotaService

        result = await QuotaService.get_effective_quota(
            user_id=1,
            resource_type="knowledge_space",
            tenant_id=1,
            login_user=_make_user(user_id=1, is_admin=True),
        )
        assert result == -1


class TestCreationGate:
    async def test_unlimited_quota_skips_counting(self):
        """-1 must short-circuit before the COUNT — that is the cheap path."""
        service = _service()
        with (
            patch(f"{_SVC}.QuotaService.get_effective_quota", new=AsyncMock(return_value=-1)),
            patch(f"{_SVC}.KnowledgeDao.async_count_spaces_by_user", new_callable=AsyncMock) as count,
        ):
            await service._assert_space_creation_quota()
        count.assert_not_awaited()

    async def test_allows_when_below_quota(self):
        service = _service()
        with (
            patch(f"{_SVC}.QuotaService.get_effective_quota", new=AsyncMock(return_value=50)),
            patch(f"{_SVC}.KnowledgeDao.async_count_spaces_by_user", new=AsyncMock(return_value=49)),
        ):
            await service._assert_space_creation_quota()

    async def test_blocks_when_quota_reached(self):
        service = _service()
        with (
            patch(f"{_SVC}.QuotaService.get_effective_quota", new=AsyncMock(return_value=50)),
            patch(f"{_SVC}.KnowledgeDao.async_count_spaces_by_user", new=AsyncMock(return_value=50)),
        ):
            with pytest.raises(SpaceLimitError):
                await service._assert_space_creation_quota()

    async def test_raised_quota_lets_the_51st_through(self):
        """Under the old hardcoded 30 this user was blocked regardless of role."""
        service = _service()
        with (
            patch(f"{_SVC}.QuotaService.get_effective_quota", new=AsyncMock(return_value=100)),
            patch(f"{_SVC}.KnowledgeDao.async_count_spaces_by_user", new=AsyncMock(return_value=50)),
        ):
            await service._assert_space_creation_quota()

    async def test_zero_quota_blocks_immediately(self):
        service = _service()
        with (
            patch(f"{_SVC}.QuotaService.get_effective_quota", new=AsyncMock(return_value=0)),
            patch(f"{_SVC}.KnowledgeDao.async_count_spaces_by_user", new=AsyncMock(return_value=0)),
        ):
            with pytest.raises(SpaceLimitError):
                await service._assert_space_creation_quota()

    async def test_counts_exclude_department_spaces(self):
        """Department spaces carry the operator as user_id — counting them would
        burn an admin's personal quota after a batch create."""
        service = _service()
        with (
            patch(f"{_SVC}.QuotaService.get_effective_quota", new=AsyncMock(return_value=50)),
            patch(f"{_SVC}.KnowledgeDao.async_count_spaces_by_user", new_callable=AsyncMock) as count,
        ):
            count.return_value = 0
            await service._assert_space_creation_quota()
        count.assert_awaited_once_with(service.login_user.user_id, exclude_department_spaces=True)

    async def test_skip_user_limit_bypasses_the_gate(self):
        """Department batch-create passes skip_user_limit=True and must not be
        capped by the operator's personal quota."""
        service = _service()
        with (
            patch.object(service, "_existing_creation", new=AsyncMock(return_value=None)),
            patch.object(service, "_assert_space_creation_quota", new_callable=AsyncMock) as gate,
            patch(f"{_SVC}.LLMService.get_workbench_llm", new=AsyncMock(return_value=None)),
        ):
            with pytest.raises(WorkbenchEmbeddingError):
                await service.create_knowledge_space(name="Space", skip_user_limit=True)
        gate.assert_not_awaited()

    def test_create_endpoint_has_no_quota_decorator(self):
        """The gate must stay in the service layer so the domain code survives.

        `@require_quota` runs before the handler and raises the generic 19402
        ("当前角色配额已用尽"), which hides 18001 and with it *which* quota ran
        out. The service-layer check also covers the v2 open API and the F050
        prospective-grant GETs, which the decorator cannot reach.
        """
        import inspect

        from bisheng.knowledge.api.endpoints import knowledge_space as ep

        # Match decorator lines only — the comment above the handler explains
        # why it is absent and mentions the name.
        decorators = [
            ln.strip() for ln in inspect.getsource(ep).splitlines() if ln.strip().startswith("@")
        ]
        assert not any(d.startswith("@require_quota") for d in decorators), decorators

    async def test_gate_runs_before_the_embedding_lookup(self):
        """Fail-closed ordering: quota must reject before any downstream work."""
        service = _service()
        with (
            patch.object(service, "_existing_creation", new=AsyncMock(return_value=None)),
            patch.object(
                service, "_assert_space_creation_quota", new=AsyncMock(side_effect=SpaceLimitError())
            ),
            patch(f"{_SVC}.LLMService.get_workbench_llm", new_callable=AsyncMock) as llm,
        ):
            with pytest.raises(SpaceLimitError):
                await service.create_knowledge_space(name="Space")
        llm.assert_not_awaited()
