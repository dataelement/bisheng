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
    return getattr(skill, "source", "manual") != "personal" or (
        user_id is not None and getattr(skill, "created_by", None) == user_id
    )


class UserSkillsService:
    def __init__(self, user_id, repository=None):
        self.user_id = user_id
        self.repository = repository or SkillAvailabilityRepository()

    async def records(self, available_only=True):
        from bisheng.linsight.domain.models.linsight_skill import LinsightSkillDao

        rows = [row for row in await LinsightSkillDao.list_enabled() if visible_to(row, self.user_id)]
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
        if row.source != "personal" or row.created_by != self.user_id:
            raise HTTPException(404, "Personal skill is unavailable")
        return row

    async def save_personal_upload(self, user, file, client_id, skill_id=None):
        import hashlib

        from bisheng.common.errcode.linsight import SkillFileTooLargeError
        from bisheng.common.schemas.api import resp_200
        from bisheng.linsight.domain.services.skill_service import SkillService
        from bisheng.linsight.domain.services.skill_store import (
            pack_bundle_zip,
            parse_skill_md,
            render_skill_md,
            resolve_skill_unpacked_limit,
            resolve_skill_upload_limit,
        )

        service = SkillService(personal_owner=user.user_id)
        data = await file.read(await resolve_skill_upload_limit() + 1)
        if len(data) > await resolve_skill_upload_limit():
            raise SkillFileTooLargeError()
        meta, files = service._parse_upload(
            file.filename,
            data,
            max_size=await resolve_skill_upload_limit(),
            max_unpacked=await resolve_skill_unpacked_limit(),
        )
        if skill_id is not None:
            row = await UserSkillsService(user.user_id).personal(skill_id)
            name = row.name
        else:
            name = f"personal-{user.user_id}-{hashlib.sha256(client_id.encode()).hexdigest()[:24]}"
            from bisheng.linsight.domain.models.linsight_skill import LinsightSkillDao

            existing = await LinsightSkillDao.get_by_name(name)
            if existing is not None:
                await UserSkillsService(user.user_id).personal(existing.id)
                return resp_200({"id": existing.id})
        front, body = parse_skill_md(files["SKILL.md"].decode("utf8"))
        front["name"] = name
        front.setdefault("metadata", {})["display-name"] = meta.display_name
        files["SKILL.md"] = render_skill_md(front, body).encode("utf8")
        if skill_id is None:
            result = await service._create(
                user.tenant_id, user.user_id, name, meta.display_name, meta.description, files
            )
        else:
            result = await service.update_from_upload(user.tenant_id, name, "skill.zip", pack_bundle_zip(files))
        return resp_200({"id": result.id})
