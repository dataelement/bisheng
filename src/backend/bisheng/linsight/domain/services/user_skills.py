"""Account-scoped skill availability and personal bundle ownership."""

from fastapi import HTTPException

from bisheng.tool.domain.repositories.user_availability import UserToolAvailabilityRepository


class SkillAvailabilityRepository(UserToolAvailabilityRepository):
    @staticmethod
    def prefix(user_id: int) -> str:
        return UserToolAvailabilityRepository.prefix(user_id).replace(
            "user-tool-availability:", "user-skill-availability:", 1
        )


def visible_to(skill, user_id):
    owner = int(getattr(skill, "owner_user_id", 0) or 0)
    if owner:
        return owner == user_id
    return getattr(skill, "source", "manual") != "personal" or (
        user_id is not None and getattr(skill, "created_by", None) == user_id
    )


class UserSkillsService:
    def __init__(self, user_id, repository=None):
        self.user_id = user_id
        self.repository = repository or SkillAvailabilityRepository()

    async def records(self, available_only=True, *, candidates=None, actor=None):
        from bisheng.linsight.domain.models.linsight_skill import LinsightSkillDao

        if candidates is None:
            tenant_rows = await LinsightSkillDao.list_enabled()
            personal_rows = await LinsightSkillDao.list_enabled(owner_user_id=self.user_id) if self.user_id else []
            by_name = {row.name: row for row in tenant_rows if visible_to(row, self.user_id)}
            by_name.update({row.name: row for row in personal_rows if visible_to(row, self.user_id)})
            rows = list(by_name.values())
        else:
            rows = [row for row in candidates if visible_to(row, self.user_id)]
        if self.user_id is None:
            return []
        from bisheng.common.dependencies.user_deps import UserPayload
        from bisheng.core.context.tenant import get_current_tenant_id
        from bisheng.permission.application.business_authorization import batch_check_business_actions
        from bisheng.utils.http_middleware import _check_is_global_super

        user = actor
        if user is None:
            user = UserPayload(
                user_id=self.user_id,
                user_name="",
                user_role=[],
                tenant_id=get_current_tenant_id(),
                is_global_super=await _check_is_global_super(self.user_id),
            )
        actions = await batch_check_business_actions(
            user, resource_type="linsight_skill", resource_ids=(row.id for row in rows), actions=("use",)
        )
        rows = [row for row in rows if "use" in actions.get(str(row.id), ())]
        disabled = await self.repository.disabled_ids(self.user_id) if self.user_id is not None else set()
        return [(row, row.id not in disabled) for row in rows if not available_only or row.id not in disabled]

    async def require(self, skill_id, available_only=True):
        row = next((row for row, _ in await self.records(available_only) if row.id == skill_id), None)
        if row is None:
            raise HTTPException(404, "Skill is unavailable for this account")
        return row

    async def toggle(self, skill_id, enabled):
        await self.require(skill_id, False)
        await self.repository.save(self.user_id, skill_id, enabled)

    async def personal(self, skill_id):
        row = await self.require(skill_id, False)
        if not visible_to(row, self.user_id) or not (row.source == "personal" or getattr(row, "owner_user_id", 0)):
            raise HTTPException(404, "Personal skill is unavailable")
        return row

    async def save_personal_upload(self, user, file, client_id, skill_id=None):
        from uuid import uuid4

        from bisheng.common.errcode.linsight import SkillFileTooLargeError
        from bisheng.common.schemas.api import resp_200
        from bisheng.linsight.domain.services.personal_skill_service import PersonalSkillService
        from bisheng.linsight.domain.services.skill_store import resolve_skill_upload_limit

        limit = await resolve_skill_upload_limit()
        data = await file.read(limit + 1)
        if len(data) > limit:
            raise SkillFileTooLargeError()
        service = PersonalSkillService()
        options = {
            "user_id": user.user_id,
            "filename": file.filename,
            "data": data,
            "import_id": client_id or str(uuid4()),
            "content_type": file.content_type,
        }
        if skill_id is None:
            result = await service.create(**options)
        else:
            row = await self.personal(skill_id)
            result = await service.overwrite(skill_id=skill_id, expected_content_hash=row.content_hash, **options)
        return resp_200({"id": result.id})
