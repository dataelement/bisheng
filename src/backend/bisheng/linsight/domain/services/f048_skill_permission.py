"""Business-owned F048 adapter for personal skills.

Enterprise skills (owner 0) are not authorized through this port. Using them
does not read the owner written at creation. A personal skill is resolvable
only for its owner, in the row's tenant.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol

from bisheng.common.errcode.permission import PermissionInvalidResourceError
from bisheng.linsight.domain.models.linsight_skill import LinsightSkillDao
from bisheng.linsight.domain.services.skill_service import SKILL_OBJECT_TYPE
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.services.permission_action_service import PermissionActor


@dataclass(frozen=True, slots=True)
class SkillPermissionRecord:
    tenant_id: int
    resource_id: str
    owner_user_id: int
    permission_version: int
    context_version: str


class SkillPermissionLoader(Protocol):
    async def load_permission_record(self, resource_id: str) -> SkillPermissionRecord | None: ...


class SkillDaoPermissionLoader:
    """Load one personal skill before an edit or delete check."""

    def __init__(self, version_port) -> None:
        self._versions = version_port

    async def load_permission_record(self, resource_id: str) -> SkillPermissionRecord | None:
        if not resource_id.isdigit():
            return None
        row = await LinsightSkillDao.get_by_id(int(resource_id))
        if row is None or row.id is None or int(row.owner_user_id or 0) <= 0:
            return None
        tenant_id = int(row.tenant_id or 0)
        if tenant_id <= 0:
            return None
        version, permission_context = await self._versions.get_permission_version(
            tenant_id=tenant_id,
            resource_type=SKILL_OBJECT_TYPE,
            resource_id=str(row.id),
        )
        stamp = row.update_time.isoformat() if row.update_time else "0"
        context_version = sha256(f"{permission_context}|{stamp}".encode()).hexdigest()[:64]
        return SkillPermissionRecord(
            tenant_id=tenant_id,
            resource_id=str(row.id),
            owner_user_id=int(row.owner_user_id),
            permission_version=version,
            context_version=context_version,
        )


class F048SkillPermissionAdapter:
    """Validate a personal skill, then hand the target to the permission facade."""

    def __init__(self, *, loader: SkillPermissionLoader, permission) -> None:
        self._loader = loader
        self._permission = permission

    async def load_permission_record(self, resource_id: str) -> SkillPermissionRecord | None:
        return await self._loader.load_permission_record(resource_id)

    async def resolve_permission_target(
        self,
        *,
        resource_id: str,
        actor: PermissionActor,
        action: str,
    ) -> VerifiedPermissionTarget:
        del action
        record = await self._loader.load_permission_record(resource_id)
        if (
            record is None
            or record.resource_id != resource_id
            or record.tenant_id != actor.current_tenant_id
            or record.owner_user_id != actor.subject_id
        ):
            raise PermissionInvalidResourceError()
        return VerifiedPermissionTarget.from_business_service(
            tenant_id=record.tenant_id,
            resource_type=SKILL_OBJECT_TYPE,
            resource_id=record.resource_id,
            resource_version=record.permission_version,
            context_version=record.context_version,
        )
