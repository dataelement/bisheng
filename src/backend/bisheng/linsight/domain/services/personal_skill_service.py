"""Personal skills: one user's copies inside the current tenant.

Quota, the import id and the row insert share one transaction. A rejected
upload does not write object storage, and the unpack directory is removed
before the request returns.
"""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path
from typing import NamedTuple

from loguru import logger
from sqlalchemy.exc import IntegrityError

from bisheng.common.errcode.linsight import (
    SkillCountLimitError,
    SkillImportMismatchError,
    SkillNameDuplicateError,
    SkillNotFoundError,
    SkillStorageLimitError,
    SkillValidationError,
    SkillVersionConflictError,
)
from bisheng.core.context.tenant import bypass_tenant_filter, get_current_tenant_id
from bisheng.core.database import get_async_db_session
from bisheng.database.models.audit_log import AuditLog
from bisheng.linsight.domain.models.linsight_skill import (
    SKILL_SOURCE_MANUAL,
    LinsightSkill,
    LinsightSkillDao,
    PersonalQuotaExceeded,
)
from bisheng.linsight.domain.services.skill_service import SKILL_OBJECT_TYPE, SkillService
from bisheng.linsight.domain.services.skill_store import (
    BundleRef,
    SkillStore,
    accept_skill_upload,
    bundle_content_hash,
    parse_skill_md,
)

PERSONAL_SKILL_COUNT_LIMIT = 20
PERSONAL_SKILL_BYTES_LIMIT = 209715200


class PersonalSkillUsage(NamedTuple):
    count: int
    used_bytes: int
    count_limit: int
    bytes_limit: int


class SkillUploadPreview(NamedTuple):
    """A parsed upload that has not been saved."""

    name: str
    display_name: str
    description: str
    size: int
    files: tuple[str, ...]


class SkillCenter(NamedTuple):
    personal: list[LinsightSkill]
    enterprise: list[LinsightSkill]
    personal_count: int
    enterprise_count: int


class PersonalSkillDetail(NamedTuple):
    skill: LinsightSkill
    bundle_missing: bool
    source_text: str
    preview: str
    files: list[dict]


class PersonalSkillFile(NamedTuple):
    path: str
    content: str


class PersonalSkillService:
    def __init__(self, store: SkillStore | None = None, owner_projection=None, unpack_root: str | Path | None = None):
        self.store = store or SkillStore()
        self._owner_projection = owner_projection
        self.unpack_root = Path(unpack_root) if unpack_root else Path(tempfile.gettempdir()) / "personal-skill-unpack"
        self.unpack_root.mkdir(parents=True, exist_ok=True)

    async def list_center(self, user_id: int, *, tab: str = "personal", keyword: str | None = None) -> SkillCenter:
        """Enabled tenant skills, plus every personal skill this user owns.

        A keyword filters only the tab being searched. Counts stay the size of
        each group, not the size of the search result.
        """
        personal, enterprise = await self._center_rows(user_id)
        shown_personal = personal
        shown_enterprise = enterprise
        if keyword:
            if tab == "enterprise":
                shown_enterprise = [row for row in enterprise if _matches_keyword(row, keyword)]
            else:
                shown_personal = [row for row in personal if _matches_keyword(row, keyword)]
        return SkillCenter(shown_personal, shown_enterprise, len(personal), len(enterprise))

    async def list_candidates(self, user_id: int) -> list[LinsightSkill]:
        """Enabled tenant skills and enabled personal skills.

        An enabled personal skill hides the tenant skill of the same name.
        """
        personal, enterprise = await self._center_rows(user_id)
        covered = {row.name for row in personal if bool(row.enabled)}
        candidates = [row for row in personal if bool(row.enabled)]
        candidates.extend(row for row in enterprise if row.name not in covered)
        return candidates

    async def _center_rows(self, user_id: int) -> tuple[list[LinsightSkill], list[LinsightSkill]]:
        rows = await LinsightSkillDao.list_visible(user_id)
        personal = [row for row in rows if row.owner_user_id == user_id]
        enterprise = [row for row in rows if row.owner_user_id == 0 and bool(row.enabled)]
        return personal, enterprise

    async def usage(self, user_id: int) -> PersonalSkillUsage:
        count, total = await LinsightSkillDao.personal_usage(user_id)
        return PersonalSkillUsage(count, total, PERSONAL_SKILL_COUNT_LIMIT, PERSONAL_SKILL_BYTES_LIMIT)

    async def find_by_import(self, user_id: int, import_id: str) -> LinsightSkill:
        row = await LinsightSkillDao.get_by_last_import_id(import_id, owner_user_id=user_id)
        if row is None:
            raise SkillNotFoundError()
        return row

    async def _load_own_skill(self, user_id: int, skill_id: int, *, action: str = "edit") -> LinsightSkill:
        """Load one personal skill in the current tenant.

        Missing, or owned by someone else, is 11053 and does not call
        ``require_business_action``. After the row is this user's, that check
        runs before any content is returned. ``delete`` passes its own action;
        detail, file read, update and enable/disable use ``edit``.
        """
        row = await LinsightSkillDao.get_by_id(skill_id)
        if row is None or row.owner_user_id != user_id or user_id == 0:
            raise SkillNotFoundError()
        from types import SimpleNamespace

        from bisheng.permission.application import business_authorization

        await business_authorization.require_business_action(
            SimpleNamespace(user_id=user_id, tenant_id=row.tenant_id, is_global_super=False),
            resource_type=SKILL_OBJECT_TYPE,
            resource_id=row.id,
            action=action,
        )
        return row

    async def _load_center_skill(self, user_id: int, skill_id: int) -> LinsightSkill:
        """A skill the center can open: this user's copy, or a tenant skill.

        Tenant skills are not checked with ``require_business_action``. Using
        one does not depend on the owner written when it was created.
        """
        row = await LinsightSkillDao.get_by_id(skill_id)
        if row is None:
            raise SkillNotFoundError()
        if row.owner_user_id == 0:
            return row
        return await self._load_own_skill(user_id, skill_id, action="edit")

    async def get(self, *, user_id: int, skill_id: int) -> PersonalSkillDetail:
        """Detail for one center skill. A missing bundle is still a 200."""
        skill = await self._load_center_skill(user_id, skill_id)
        try:
            source_text = self.store.read_text(
                skill.tenant_id, skill.name, skill.content_hash, owner_user_id=skill.owner_user_id
            )
            _, body = parse_skill_md(source_text)
            files = self.store.list_files(
                skill.tenant_id, skill.name, skill.content_hash, owner_user_id=skill.owner_user_id
            )
        except (FileNotFoundError, ValueError):
            return PersonalSkillDetail(skill, True, "", "", [])
        return PersonalSkillDetail(skill, False, source_text, body.strip(), files)

    def is_bundle_missing(self, skill: LinsightSkill) -> bool:
        """Whether this row's object is gone. The HTTP layer must not touch storage."""
        return not self.store.exists(
            skill.tenant_id,
            skill.name,
            skill.content_hash,
            owner_user_id=skill.owner_user_id,
        )

    async def read_file(self, *, user_id: int, skill_id: int, path: str) -> PersonalSkillFile:
        skill = await self._load_center_skill(user_id, skill_id)
        try:
            content = self.store.read_text(
                skill.tenant_id,
                skill.name,
                skill.content_hash,
                path,
                owner_user_id=skill.owner_user_id,
            )
        except ValueError:
            raise SkillValidationError(msg="illegal file path") from None
        except FileNotFoundError:
            raise SkillNotFoundError() from None
        return PersonalSkillFile(path, content)

    async def set_enabled(self, *, user_id: int, skill_id: int, enabled: bool) -> LinsightSkill:
        """Turn a personal skill on or off. The bundle stays where it is."""
        skill = await self._load_own_skill(user_id, skill_id)
        if bool(skill.enabled) == bool(enabled):
            return skill
        await LinsightSkillDao.set_owner_enabled(skill_id, owner_user_id=user_id, enabled=enabled)
        saved = await self._load_own_skill(user_id, skill_id)
        await self._audit(
            saved,
            user_id,
            saved.tenant_id,
            event_type="personal_skill_status",
            action="linsight.personal_skill.status",
        )
        return saved

    async def delete(self, *, user_id: int, skill_id: int) -> None:
        """Remove the row and the object it pointed at.

        A missing id, or one that belongs to someone else, looks the same as a
        delete that already happened: an empty result, with no name and no body.
        """
        try:
            skill = await self._load_own_skill(user_id, skill_id, action="delete")
        except SkillNotFoundError:
            return None
        tenant_id = skill.tenant_id
        name = skill.name
        content_hash = skill.content_hash
        await LinsightSkillDao.delete_owned(skill.id, owner_user_id=user_id)
        # The row is gone, so nothing still points at this object.
        self.store.delete_version(tenant_id, name, content_hash, owner_user_id=user_id)
        await self._audit(
            skill,
            user_id,
            tenant_id,
            event_type="personal_skill_delete",
            action="linsight.personal_skill.delete",
        )
        return None

    async def inspect_upload(
        self,
        *,
        user_id: int,
        filename: str,
        data: bytes,
        content_type: str | None = None,
        skill_id: int | None = None,
    ) -> SkillUploadPreview:
        """Parse and check one upload. Nothing is written until create or overwrite."""
        work = Path(tempfile.mkdtemp(dir=self.unpack_root))
        try:
            files = await accept_skill_upload(filename, data, owner_user_id=user_id, content_type=content_type)
            _stage_unpack(work, files)
            meta = object.__new__(SkillService)._extract_meta(files)
            if skill_id is not None:
                skill = await self._load_own_skill(user_id, skill_id)
                meta = SkillService._keep_skill_id(
                    files, meta, skill.name, current_display_name=skill.display_name or ""
                )
            size = sum(len(content) for content in files.values())
            if skill_id is not None:
                _, total = await LinsightSkillDao.personal_usage(user_id)
                if total - int(skill.size or 0) + size > PERSONAL_SKILL_BYTES_LIMIT:
                    raise SkillStorageLimitError()
            else:
                existing = await LinsightSkillDao.get_by_name(meta.name, owner_user_id=user_id)
                if existing is not None:
                    raise SkillNameDuplicateError(skill_id=existing.id, content_hash=existing.content_hash)
                count, total = await LinsightSkillDao.personal_usage(user_id)
                if count >= PERSONAL_SKILL_COUNT_LIMIT:
                    raise SkillCountLimitError()
                if total + size > PERSONAL_SKILL_BYTES_LIMIT:
                    raise SkillStorageLimitError()
            return SkillUploadPreview(
                name=meta.name,
                display_name=meta.display_name,
                description=meta.description,
                size=size,
                files=tuple(sorted(files)),
            )
        finally:
            shutil.rmtree(work, ignore_errors=True)

    async def create(
        self,
        *,
        user_id: int,
        filename: str,
        data: bytes,
        import_id: str,
        content_type: str | None = None,
    ) -> LinsightSkill:
        tenant_id = get_current_tenant_id() or 1
        work = Path(tempfile.mkdtemp(dir=self.unpack_root))
        written: BundleRef | None = None
        try:
            files = await accept_skill_upload(filename, data, owner_user_id=user_id, content_type=content_type)
            _stage_unpack(work, files)
            meta = object.__new__(SkillService)._extract_meta(files)
            content_hash = bundle_content_hash(files)
            size = sum(len(content) for content in files.values())

            imported = await LinsightSkillDao.get_by_last_import_id(import_id, owner_user_id=user_id)
            if imported is not None:
                if imported.content_hash == content_hash:
                    return imported
                raise SkillImportMismatchError()

            existing = await LinsightSkillDao.get_by_name(meta.name, owner_user_id=user_id)
            if existing is not None:
                raise SkillNameDuplicateError(skill_id=existing.id, content_hash=existing.content_hash)

            count, total = await LinsightSkillDao.personal_usage(user_id)
            if count >= PERSONAL_SKILL_COUNT_LIMIT:
                raise SkillCountLimitError()
            if total + size > PERSONAL_SKILL_BYTES_LIMIT:
                raise SkillStorageLimitError()

            written = self.store.write_bundle(tenant_id, meta.name, files, owner_user_id=user_id)
            skill = LinsightSkill(
                tenant_id=tenant_id,
                owner_user_id=user_id,
                name=meta.name,
                display_name=meta.display_name,
                description=meta.description,
                enabled=True,
                source=SKILL_SOURCE_MANUAL,
                object_path=written.object_key,
                content_hash=written.content_hash,
                size=written.size,
                created_by=user_id,
                last_import_id=import_id,
            )
            try:
                skill = await LinsightSkillDao.create_personal(
                    skill,
                    count_limit=PERSONAL_SKILL_COUNT_LIMIT,
                    bytes_limit=PERSONAL_SKILL_BYTES_LIMIT,
                )
            except asyncio.CancelledError:
                await self._drop_unpublished(tenant_id, meta.name, written, user_id)
                written = None
                raise
            except PersonalQuotaExceeded as exc:
                await self._drop_unpublished(tenant_id, meta.name, written, user_id)
                written = None
                if exc.kind == "count":
                    raise SkillCountLimitError() from None
                raise SkillStorageLimitError() from None
            except IntegrityError:
                await self._drop_unpublished(tenant_id, meta.name, written, user_id)
                written = None
                return await self._resolve_insert_conflict(user_id, meta.name, import_id, content_hash)

            await self._authorize(skill, user_id, tenant_id)
            await self._audit(skill, user_id, tenant_id)
            return skill
        finally:
            shutil.rmtree(work, ignore_errors=True)

    async def overwrite(
        self,
        *,
        user_id: int,
        skill_id: int,
        filename: str,
        data: bytes,
        expected_content_hash: str,
        import_id: str,
        content_type: str | None = None,
    ) -> LinsightSkill:
        """Replace one personal skill's bundle. The id and enabled flag stay."""
        tenant_id = get_current_tenant_id() or 1
        skill = await self._load_own_skill(user_id, skill_id)
        if skill.content_hash != expected_content_hash:
            raise SkillVersionConflictError()

        work = Path(tempfile.mkdtemp(dir=self.unpack_root))
        try:
            files = await accept_skill_upload(filename, data, owner_user_id=user_id, content_type=content_type)
            _stage_unpack(work, files)
            meta = object.__new__(SkillService)._extract_meta(files)
            meta = SkillService._keep_skill_id(files, meta, skill.name, current_display_name=skill.display_name or "")
            new_hash = bundle_content_hash(files)
            new_size = sum(len(content) for content in files.values())
            _, total = await LinsightSkillDao.personal_usage(user_id)
            if total - int(skill.size or 0) + new_size > PERSONAL_SKILL_BYTES_LIMIT:
                raise SkillStorageLimitError()

            previous_hash = skill.content_hash
            written = self.store.write_bundle(tenant_id, skill.name, files, owner_user_id=user_id)
            updated = await LinsightSkillDao.update_bundle(
                skill.id,
                owner_user_id=user_id,
                expected_content_hash=expected_content_hash,
                content_hash=written.content_hash,
                object_path=written.object_key,
                size=written.size,
                display_name=meta.display_name,
                description=meta.description,
                last_import_id=import_id,
            )
            if not updated:
                raise SkillVersionConflictError()
            if new_hash != previous_hash:
                try:
                    self.store.delete_version(tenant_id, skill.name, previous_hash, owner_user_id=user_id)
                except Exception as exc:
                    logger.warning("personal skill old bundle delete failed for {}: {}", skill.id, exc)
            saved = await LinsightSkillDao.get_by_id(skill.id)
            await self._audit(
                saved,
                user_id,
                tenant_id,
                event_type="personal_skill_overwrite",
                action="linsight.personal_skill.overwrite",
            )
            return saved
        finally:
            shutil.rmtree(work, ignore_errors=True)

    async def _drop_unpublished(self, tenant_id: int, name: str, ref: BundleRef, user_id: int) -> None:
        current = await LinsightSkillDao.get_by_name(name, owner_user_id=user_id)
        if current is not None and current.content_hash == ref.content_hash:
            return
        self.store.delete_version(tenant_id, name, ref.content_hash, owner_user_id=user_id)

    async def _resolve_insert_conflict(
        self, user_id: int, name: str, import_id: str, content_hash: str
    ) -> LinsightSkill:
        imported = await LinsightSkillDao.get_by_last_import_id(import_id, owner_user_id=user_id)
        if imported is not None and imported.content_hash == content_hash:
            return imported
        if imported is not None:
            raise SkillImportMismatchError()
        current = await LinsightSkillDao.get_by_name(name, owner_user_id=user_id)
        if current is not None:
            raise SkillNameDuplicateError(skill_id=current.id, content_hash=current.content_hash)
        raise SkillNameDuplicateError()

    async def _authorize(self, skill: LinsightSkill, user_id: int, tenant_id: int) -> None:
        projection = self._owner_projection
        if projection is None:
            from bisheng.linsight.domain.services.skill_service import _ConfiguredOwnerProjection

            projection = _ConfiguredOwnerProjection()
        await projection.authorize_created(
            tenant_id=tenant_id,
            resource_type=SKILL_OBJECT_TYPE,
            resource_id=str(skill.id),
            owner_user_id=user_id,
            resource_version=0,
            context_version=f"{SKILL_OBJECT_TYPE}:{skill.id}:v0",
            idempotency_key=f"{SKILL_OBJECT_TYPE}:create:{tenant_id}:{skill.id}",
        )

    async def _audit(
        self,
        skill: LinsightSkill,
        user_id: int,
        tenant_id: int,
        *,
        event_type: str = "personal_skill_create",
        action: str = "linsight.personal_skill.create",
    ) -> None:
        try:
            entry = AuditLog(
                operator_id=user_id,
                operator_tenant_id=tenant_id,
                tenant_id=tenant_id,
                system_id="linsight",
                event_type=event_type,
                action=action,
                target_type=SKILL_OBJECT_TYPE,
                target_id=str(skill.id),
                object_type=SKILL_OBJECT_TYPE,
                object_id=str(skill.id),
                audit_metadata={
                    "source": skill.source,
                    "content_hash": skill.content_hash,
                    "result": "success",
                },
            )
            with bypass_tenant_filter():
                async with get_async_db_session() as session:
                    session.add(entry)
                    await session.commit()
        except Exception as exc:
            logger.warning("personal skill audit insert failed for skill {}: {}", skill.id, exc)


def _matches_keyword(skill: LinsightSkill, keyword: str) -> bool:
    needle = keyword.casefold()
    return any(needle in (value or "").casefold() for value in (skill.display_name, skill.name, skill.description))


def _stage_unpack(work: Path, files: dict[str, bytes]) -> None:
    for rel, content in files.items():
        target = work / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
