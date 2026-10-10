"""部门库规则在没有部门库时改用科室库, 找不到或绑了多个库时不再进兜底库."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.common.errcode.filelib_sync import FilelibSyncConflictError, FilelibSyncNotFoundError
from bisheng.common.errcode.knowledge_space import DepartmentKnowledgeSpaceAmbiguousError
from bisheng.database.models.department import Department
from bisheng.developer_token.domain.schemas import DeveloperTokenFileSyncRule
from bisheng.knowledge.domain.models.knowledge import Knowledge
from bisheng.knowledge.domain.services.department_space_target_resolver import DepartmentSpaceTargetKind
from bisheng.open_endpoints.domain.services.filelib_sync_service import FilelibSyncService


def _department() -> Department:
    return Department(id=20, dept_id="D-20", name="智新科室", path="/1/20/")


def _service(repository, knowledge_space_service) -> FilelibSyncService:
    service = FilelibSyncService(
        request=SimpleNamespace(headers={}),
        login_user=SimpleNamespace(user_id=1, user_name="caller", user_role=[2], tenant_id=1),
        token_id=42,
        token_name="联调Token",
        file_sync_rule=DeveloperTokenFileSyncRule.model_validate(
            {
                "category": {"code": "POLICY", "subcategory_code": "MGMT_POLICY"},
                "business_domain": {"mode": "fixed", "code": "IT"},
                "target_space": {
                    "mode": "dynamic",
                    "dynamic_source": "department_id",
                },
            }
        ),
        repository=repository,
        knowledge_space_service=knowledge_space_service,
    )
    return service


def _identity() -> SimpleNamespace:
    department = _department()
    return SimpleNamespace(
        target_space_department=department,
        business_domain_department=None,
        main_department=department,
        caller_department=department,
        responsible_user_id=7,
        responsible_user_name="上传人",
    )


@pytest.mark.asyncio
async def test_department_rule_uses_clinic_space_when_department_space_missing() -> None:
    """组织链上没有部门库时, 文件进入同一条链上的科室库."""
    clinic_space = Knowledge(id=301, name="智新科室库", type=3)
    repository = SimpleNamespace(find_knowledge_by_id=AsyncMock(return_value=clinic_space))
    knowledge_space_service = SimpleNamespace(ensure_personal_default_space=AsyncMock())

    async def _resolve(_department_ids, *, kind, allow_legacy=False):
        if kind == DepartmentSpaceTargetKind.DEPARTMENT:
            return None
        return 301

    with patch(
        "bisheng.open_endpoints.domain.services.filelib_sync_service.DepartmentSpaceTargetResolver.resolve",
        new=AsyncMock(side_effect=_resolve),
    ):
        target = await _service(repository, knowledge_space_service)._resolve_target_space(_identity())

    assert target.space.id == 301
    assert target.used_personal_fallback is False
    assert target.used_responsible_person_personal is False
    knowledge_space_service.ensure_personal_default_space.assert_not_awaited()


@pytest.mark.asyncio
async def test_department_rule_rejects_when_clinic_space_also_missing() -> None:
    """部门库和科室库都不存在时, 同步失败, 不写入令牌用户个人库."""
    repository = SimpleNamespace(find_knowledge_by_id=AsyncMock())
    knowledge_space_service = SimpleNamespace(ensure_personal_default_space=AsyncMock())
    service = _service(repository, knowledge_space_service)

    with patch(
        "bisheng.open_endpoints.domain.services.filelib_sync_service.DepartmentSpaceTargetResolver.resolve",
        new=AsyncMock(return_value=None),
    ):
        with pytest.raises(FilelibSyncNotFoundError):
            await service._resolve_target_space(_identity())

    knowledge_space_service.ensure_personal_default_space.assert_not_awaited()


@pytest.mark.asyncio
async def test_department_rule_rejects_when_multiple_clinic_spaces_are_bound() -> None:
    """没有部门库且同一组织绑了多个科室库时, 同步失败, 不取第一个也不进兜底库."""
    repository = SimpleNamespace(find_knowledge_by_id=AsyncMock())
    knowledge_space_service = SimpleNamespace(ensure_personal_default_space=AsyncMock())

    async def _resolve(_department_ids, *, kind, allow_legacy=False):
        if kind == DepartmentSpaceTargetKind.DEPARTMENT:
            return None
        raise DepartmentKnowledgeSpaceAmbiguousError(department_id=20, candidate_space_ids=[11, 12])

    with patch(
        "bisheng.open_endpoints.domain.services.filelib_sync_service.DepartmentSpaceTargetResolver.resolve",
        new=AsyncMock(side_effect=_resolve),
    ):
        with pytest.raises(FilelibSyncConflictError, match="multiple target clinic"):
            await _service(repository, knowledge_space_service)._resolve_target_space(_identity())

    repository.find_knowledge_by_id.assert_not_awaited()
    knowledge_space_service.ensure_personal_default_space.assert_not_awaited()
