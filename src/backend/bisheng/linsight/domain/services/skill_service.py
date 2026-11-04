"""Tenant custom skill management service (F035 Track D, design §7.4/§7.5).

Validation chain (design §7.4): size gate → unpack/parse → frontmatter +
name/display_name checks → duplicate checks → disk bundle write → DB metadata
→ durable F048 protected-owner projection.

built-in skills never pass through here: any name that does not exist in the
tenant's `linsight_skill` table is answered with 11053 (not-found), so their
existence is not leaked (design §7.5).
"""

from __future__ import annotations

import asyncio
from typing import NamedTuple, Protocol

from loguru import logger
from sqlalchemy.exc import IntegrityError

from bisheng.common.errcode.linsight import (
    SkillBundleTooLargeError,
    SkillFileTooLargeError,
    SkillNameDuplicateError,
    SkillNotFoundError,
    SkillValidationError,
)
from bisheng.common.schemas.api import PageData
from bisheng.linsight.domain.models.linsight_skill import (
    SKILL_SOURCE_BUILTIN,
    SKILL_SOURCE_MANUAL,
    LinsightSkill,
    LinsightSkillDao,
)
from bisheng.linsight.domain.schemas.skill_schema import (
    SkillBrief,
    SkillCreateForm,
    SkillDetail,
    SkillFileContent,
    SkillFileEntry,
    SkillRuntimeEntry,
    SkillSelectable,
)
from bisheng.linsight.domain.services.github_skill_fetcher import fetch_skill_files, parse_github_url
from bisheng.linsight.domain.services.skill_store import (
    DISPLAY_NAME_META_KEY,
    MAX_BUNDLE_SIZE,
    MAX_DESCRIPTION_LEN,
    MAX_DISPLAY_NAME_LEN,
    MAX_UNPACKED_SIZE,
    SKILL_MD,
    BundleTooLargeError,
    SkillStore,
    compose_skill_md,
    pack_bundle_zip,
    parse_skill_md,
    render_skill_md,
    resolve_skill_unpacked_limit,
    resolve_skill_upload_limit,
    slugify_pinyin,
    unpack_zip_bytes,
    validate_skill_name,
)

_ARCHIVE_SUFFIXES = (".zip", ".skill")


class SkillMeta(NamedTuple):
    """Frontmatter fields extracted from an imported bundle.

    ``normalized_from`` carries the original frontmatter name when it was
    auto-normalized to a spec-legal skill ID, so the API can tell the user.
    """

    name: str
    display_name: str
    description: str
    normalized_from: str | None = None


SKILL_OBJECT_TYPE = "linsight_skill"


def _display_name_from_frontmatter(meta: dict, fallback: str) -> str:
    """Read a human name from frontmatter, then fall back to the skill id."""
    metadata = meta.get("metadata") if isinstance(meta.get("metadata"), dict) else {}
    for value in (metadata.get(DISPLAY_NAME_META_KEY), meta.get("display_name"), meta.get("display-name")):
        text = str(value or "").strip()
        if text:
            return text
    return fallback


class LinsightSkillOwnerProjectionPort(Protocol):
    """Durable owner projection required before skill creation completes."""

    async def authorize_created(
        self,
        *,
        tenant_id: int,
        resource_type: str,
        resource_id: str,
        owner_user_id: int,
        resource_version: int,
        context_version: str,
        idempotency_key: str,
        shared_with_tenant: bool = False,
    ): ...


class _ConfiguredOwnerProjection:
    async def authorize_created(self, **kwargs):
        from bisheng.permission.application.process_runtime import get_f048_process_runtime

        await get_f048_process_runtime()
        if _owner_projection is None:
            raise RuntimeError("F048 Linsight skill owner projection is not configured")
        return await _owner_projection.authorize_created(**kwargs)


_owner_projection: LinsightSkillOwnerProjectionPort | None = None


def configure_linsight_skill_owner_projection(
    projection: LinsightSkillOwnerProjectionPort,
) -> None:
    """Install the process-local durable owner projection adapter."""

    global _owner_projection
    _owner_projection = projection


class SkillService:
    """All methods assume the tenant context is already established
    (endpoint dependency or worker context, design §6.5). Skills are
    tenant-private: ``LinsightSkillDao`` enforces strict ``tenant_id = current``
    isolation on every read/write (no Root→child sharing), so a tenant only
    ever sees and mutates its own skills."""

    def __init__(
        self,
        store: SkillStore | None = None,
        owner_projection: LinsightSkillOwnerProjectionPort | None = None,
        personal_owner: int | None = None,
    ):
        self.personal_owner = personal_owner
        self.store = store or SkillStore()
        self._owner_projection = owner_projection or _ConfiguredOwnerProjection()

    # ------------------------------------------------------------- queries --
    async def get_page(
        self, keyword: str | None, enabled: bool | None, page: int, page_size: int
    ) -> PageData[SkillBrief]:
        skills, total = await LinsightSkillDao.get_page(
            keyword=keyword, enabled=enabled, page=page, page_size=page_size
        )
        return PageData(data=[SkillBrief.from_model(s) for s in skills], total=total)

    async def get_selectable(self, user_id=None) -> list[SkillSelectable]:
        from bisheng.linsight.domain.services.user_skills import UserSkillsService

        skills = [row for row, _ in await UserSkillsService(user_id).records()]
        return [
            SkillSelectable(
                name=s.name,
                display_name=s.display_name or s.name,
                description=s.description,
                default_checked=False,
            )
            for s in skills
        ]

    async def get_runtime_catalog(self, user_id=None) -> list[SkillRuntimeEntry]:
        from bisheng.linsight.domain.services.user_skills import UserSkillsService

        skills = [row for row, _ in await UserSkillsService(user_id).records()]
        return [
            SkillRuntimeEntry(
                id=skill.id,
                name=skill.name,
                display_name=skill.display_name or skill.name,
                description=skill.description,
                default_checked=bool(skill.default_checked),
                content_hash=skill.content_hash,
            )
            for skill in skills
        ]

    async def get_runtime_bundle(self, tenant_id: int, skill_id: int, version: str, user_id=None) -> bytes:
        from bisheng.linsight.domain.services.user_skills import UserSkillsService

        async def authorized():
            skill = next(
                (
                    row
                    for row, _ in await UserSkillsService(user_id).records()
                    if row.id == skill_id and row.tenant_id == tenant_id
                ),
                None,
            )
            if skill is None:
                raise SkillNotFoundError()
            if skill.content_hash != version:
                raise SkillValidationError(msg="Skill version changed. Refresh the skill catalog.")
            return skill

        skill = await authorized()
        bundle = await asyncio.to_thread(
            lambda: pack_bundle_zip(
                self._load_existing_bundle(tenant_id, skill.name, version, owner_user_id=skill.owner_user_id)
            )
        )
        await authorized()
        return bundle

    async def get_detail(self, tenant_id: int, name: str) -> SkillDetail:
        skill = await self._get_or_404(name)
        try:
            source_text = self.store.read_text(tenant_id, name, skill.content_hash)
            _, body = parse_skill_md(source_text)
        except (FileNotFoundError, ValueError) as exc:
            # Row exists but its bundle object doesn't (never migrated, or deleted
            # out-of-band) — surface, don't hide.
            logger.warning("skill bundle read failed for {}: {}", name, exc)
            source_text, body = "", ""
        detail = SkillDetail(
            **SkillBrief.from_model(skill).model_dump(),
            preview=body.strip(),
            source_text=source_text,
            files=[SkillFileEntry(**e) for e in self.store.list_files(tenant_id, name, skill.content_hash)],
        )
        return detail

    async def read_bundle_file(self, tenant_id: int, name: str, path: str) -> SkillFileContent:
        skill = await self._get_or_404(name)
        try:
            content = self.store.read_text(tenant_id, name, skill.content_hash, path)
        except ValueError:
            raise SkillValidationError(msg=f"illegal file path: {path}")
        except FileNotFoundError:
            raise SkillNotFoundError(msg=f"file not found in skill bundle: {path}")
        return SkillFileContent(path=path, content=content)

    # ----------------------------------------------------------- mutations --
    async def create_from_form(self, tenant_id: int, user_id: int, form: SkillCreateForm) -> SkillDetail:
        files = {
            SKILL_MD: compose_skill_md(
                name=form.name,
                description=form.description,
                body=form.content,
                display_name=form.display_name,
            ).encode("utf-8")
        }
        return await self._create(tenant_id, user_id, form.name, form.display_name, form.description, files)

    async def create_from_upload(self, tenant_id: int, user_id: int, filename: str, data: bytes) -> SkillDetail:
        meta, files = self._parse_upload(
            filename,
            data,
            max_size=await resolve_skill_upload_limit(),
            max_unpacked=await resolve_skill_unpacked_limit(),
        )
        detail = await self._create(tenant_id, user_id, meta.name, meta.display_name, meta.description, files)
        detail.normalized_from = meta.normalized_from
        return detail

    async def create_from_github(self, tenant_id: int, user_id: int, url: str) -> SkillDetail:
        """Import a skill from a public GitHub directory URL.

        The downloaded bundle joins the exact same create chain as the upload path,
        so frontmatter/size/duplicate checks and the owner tuple are all reused.
        """
        target = parse_github_url(url)
        files = await fetch_skill_files(target)
        meta = self._extract_meta(files)
        detail = await self._create(tenant_id, user_id, meta.name, meta.display_name, meta.description, files)
        detail.normalized_from = meta.normalized_from
        return detail

    @staticmethod
    def _mark_forked(skill) -> None:
        """An edited built-in skill becomes this tenant's own copy.

        The startup seeder refreshes ``source='builtin'`` rows from the image on
        every boot. Leaving the marker on an edited skill would silently revert
        the customer's changes at the next upgrade, so the first edit opts that
        copy out of re-seeding for good.
        """
        if skill.source == SKILL_SOURCE_BUILTIN:
            skill.source = SKILL_SOURCE_MANUAL

    async def update_from_form(self, tenant_id: int, name: str, form: SkillCreateForm) -> SkillDetail:
        skill = await self._get_or_404(name)
        if form.name != name:
            raise SkillValidationError(msg="skill ID cannot be changed when editing")
        self._validate_fields(form.name, form.display_name, form.description)
        await self._check_duplicate(
            form.name, form.display_name, exclude_id=skill.id, owner_user_id=skill.owner_user_id
        )
        # Re-render SKILL.md, keep any other bundle assets untouched.
        new_md = compose_skill_md(
            name=form.name, description=form.description, body=form.content, display_name=form.display_name
        ).encode("utf-8")
        files = self._load_existing_bundle(tenant_id, name, skill.content_hash)
        files[SKILL_MD] = new_md
        ref = self.store.write_bundle(tenant_id, name, files)
        skill.display_name, skill.description = form.display_name, form.description
        skill.size, skill.content_hash, skill.object_path = ref.size, ref.content_hash, ref.object_key
        self._mark_forked(skill)
        await LinsightSkillDao.update(skill)
        return await self.get_detail(tenant_id, name)

    @staticmethod
    def _keep_skill_id(
        files: dict[str, bytes],
        meta: SkillMeta,
        skill_name: str,
        *,
        current_display_name: str = "",
    ) -> SkillMeta:
        """Keep the skill ID already stored on this row.

        An uploaded bundle may name itself differently. The row, its id and the
        directory stay. SKILL.md is rewritten so its frontmatter matches. A bundle
        with no display name of its own reports its skill id as the display name;
        that must not replace the name already shown for this skill.
        """
        uploaded_name = meta.name
        if meta.name != skill_name:
            parsed, body = parse_skill_md(files[SKILL_MD].decode("utf-8"))
            parsed["name"] = skill_name
            files[SKILL_MD] = render_skill_md(parsed, body).encode("utf-8")
            meta = meta._replace(name=skill_name, normalized_from=None)
        if current_display_name and meta.display_name == uploaded_name:
            meta = meta._replace(display_name=current_display_name)
        return meta

    async def update_from_upload(self, tenant_id: int, name: str, filename: str, data: bytes) -> SkillDetail:
        """Whole-bundle replacement. The skill ID stays the path name."""
        skill = await self._get_or_404(name)
        meta, files = self._parse_upload(
            filename,
            data,
            max_size=await resolve_skill_upload_limit(),
            max_unpacked=await resolve_skill_unpacked_limit(),
        )
        meta = self._keep_skill_id(files, meta, name, current_display_name=skill.display_name or "")
        await self._check_duplicate(name, meta.display_name, exclude_id=skill.id, owner_user_id=skill.owner_user_id)
        ref = self.store.write_bundle(tenant_id, name, files)
        skill.display_name, skill.description = meta.display_name, meta.description
        skill.size, skill.content_hash, skill.object_path = ref.size, ref.content_hash, ref.object_key
        self._mark_forked(skill)
        await LinsightSkillDao.update(skill)
        detail = await self.get_detail(tenant_id, name)
        detail.normalized_from = meta.normalized_from
        return detail

    async def set_status(self, name: str, enabled: bool) -> None:
        if not await LinsightSkillDao.set_enabled(name, enabled):
            raise SkillNotFoundError()

    async def set_default_checked(self, name: str, default_checked: bool) -> None:
        if not await LinsightSkillDao.set_default_checked(name, default_checked):
            raise SkillNotFoundError()

    async def delete(self, tenant_id: int, name: str) -> None:
        skill = await self._get_or_404(name)
        await LinsightSkillDao.delete_by_name(name)
        if not self.store.delete(tenant_id, name):
            logger.warning("skill bundle already absent on delete: tenant={} name={}", tenant_id, skill.name)

    # ----------------------------------------------------------- internals --
    async def _get_or_404(self, name: str) -> LinsightSkill:
        skill = await LinsightSkillDao.get_by_name(name)
        if not skill or (skill.source == "personal" and skill.created_by != self.personal_owner):
            # built-in names also land here: 404 without leaking existence (design §7.5).
            raise SkillNotFoundError()
        return skill

    def _parse_upload(
        self,
        filename: str,
        data: bytes,
        *,
        max_size: int = MAX_BUNDLE_SIZE,
        max_unpacked: int = MAX_UNPACKED_SIZE,
    ) -> tuple[SkillMeta, dict[str, bytes]]:
        if len(data) > max_size:
            raise SkillFileTooLargeError(limit_mb=max_size // (1024 * 1024))
        lower = (filename or "").lower()
        if lower.endswith(_ARCHIVE_SUFFIXES):
            try:
                # The unpacked cap is checked inside, before anything is decompressed.
                files = unpack_zip_bytes(data, max_unpacked=max_unpacked)
            except BundleTooLargeError:
                raise SkillBundleTooLargeError(limit_mb=max_unpacked // (1024 * 1024))
            except ValueError as exc:
                raise SkillValidationError(msg=str(exc))
        elif lower.endswith(".md"):
            files = {SKILL_MD: data}
        else:
            raise SkillValidationError(msg="unsupported file type: expecting .md, .zip or .skill")
        return self._extract_meta(files), files

    def _extract_meta(self, files: dict[str, bytes]) -> SkillMeta:
        """Parse SKILL.md frontmatter from a bundle into a SkillMeta.

        Shared by the upload and GitHub-import paths so both validate identically.
        A frontmatter ``name`` that violates the skill-ID spec (external skills
        commonly ship capitalized names, e.g. ``Presentations``) is normalized via
        ``slugify_pinyin`` instead of rejected: SKILL.md is rewritten in place so
        the stored frontmatter still equals the bundle directory name (deepagents
        hard constraint), and the original name becomes the display name.
        """
        if SKILL_MD not in files:
            raise SkillValidationError(msg="SKILL.md not found")
        try:
            meta, body = parse_skill_md(files[SKILL_MD].decode("utf-8", errors="replace"))
        except ValueError as exc:
            raise SkillValidationError(msg=str(exc))
        name = str(meta.get("name") or "").strip()
        description = str(meta.get("description") or "").strip()
        display_name = _display_name_from_frontmatter(meta, name)
        if not description:
            raise SkillValidationError(msg="frontmatter 'description' is required")
        normalized_from: str | None = None
        if name and validate_skill_name(name):
            slug = slugify_pinyin(name)
            if not validate_skill_name(slug):
                normalized_from, name = name, slug
                display_name = _display_name_from_frontmatter(meta, normalized_from)
                meta["name"] = slug
                metadata = meta.get("metadata") if isinstance(meta.get("metadata"), dict) else {}
                if display_name == normalized_from and not metadata.get(DISPLAY_NAME_META_KEY):
                    metadata[DISPLAY_NAME_META_KEY] = normalized_from
                    meta["metadata"] = metadata
                files[SKILL_MD] = render_skill_md(meta, body).encode("utf-8")
        self._validate_fields(name, display_name, description)
        return SkillMeta(name, display_name, description, normalized_from)

    def _validate_fields(self, name: str, display_name: str, description: str) -> None:
        if err := validate_skill_name(name):
            raise SkillValidationError(msg=err)
        if not display_name or len(display_name) > MAX_DISPLAY_NAME_LEN:
            raise SkillValidationError(msg=f"display_name is required and must be <= {MAX_DISPLAY_NAME_LEN} chars")
        if not description or len(description) > MAX_DESCRIPTION_LEN:
            raise SkillValidationError(msg=f"description is required and must be <= {MAX_DESCRIPTION_LEN} chars")

    async def _check_duplicate(
        self,
        name: str,
        display_name: str,
        exclude_id: int | None = None,
        *,
        owner_user_id: int = 0,
    ) -> None:
        existing = await LinsightSkillDao.get_by_name(name, owner_user_id=owner_user_id)
        if existing and existing.id != exclude_id:
            raise SkillNameDuplicateError()
        # A personal skill is keyed by its skill id. The same display name with a
        # different id is a new skill. Tenant skills (owner 0) keep the display-name check.
        if owner_user_id != 0:
            return
        existing = await LinsightSkillDao.get_by_display_name(display_name, owner_user_id=owner_user_id)
        if existing and existing.id != exclude_id:
            raise SkillNameDuplicateError()

    def _load_existing_bundle(
        self, tenant_id: int, name: str, content_hash: str, *, owner_user_id: int = 0
    ) -> dict[str, bytes]:
        """Read a stored bundle back as a file mapping (edit = read-modify-write).

        Goes through the store's reader rather than joining paths itself; the
        bundle's authoritative copy is an object, and only the store knows how a
        version is materialized locally.
        """
        return {
            entry["path"]: self.store.read_bytes(
                tenant_id, name, content_hash, entry["path"], owner_user_id=owner_user_id
            )
            for entry in self.store.list_files(tenant_id, name, content_hash, owner_user_id=owner_user_id)
        }

    async def _discard_unpublished(self, tenant_id: int, name: str, content_hash: str, owner_user_id: int = 0) -> None:
        """A lost insert must not leave an object the saved row does not point at."""
        current = await LinsightSkillDao.get_by_name(name, owner_user_id=owner_user_id)
        if current is not None and current.content_hash == content_hash:
            return
        self.store.delete_version(tenant_id, name, content_hash, owner_user_id=owner_user_id)

    async def _create(
        self,
        tenant_id: int,
        user_id: int,
        name: str,
        display_name: str,
        description: str,
        files: dict[str, bytes],
    ) -> SkillDetail:
        self._validate_fields(name, display_name, description)
        await self._check_duplicate(name, display_name)
        ref = self.store.write_bundle(tenant_id, name, files)
        skill = LinsightSkill(
            tenant_id=tenant_id,
            name=name,
            display_name=display_name,
            description=description,
            enabled=True,
            source="personal" if self.personal_owner is not None else SKILL_SOURCE_MANUAL,
            object_path=ref.object_key,
            content_hash=ref.content_hash,
            size=ref.size,
            created_by=user_id,
        )
        try:
            skill = await LinsightSkillDao.create(skill)
        except IntegrityError:
            await self._discard_unpublished(tenant_id, name, ref.content_hash)
            raise SkillNameDuplicateError() from None
        await self._owner_projection.authorize_created(
            tenant_id=tenant_id,
            resource_type=SKILL_OBJECT_TYPE,
            resource_id=str(skill.id),
            owner_user_id=user_id,
            resource_version=0,
            context_version=f"{SKILL_OBJECT_TYPE}:{skill.id}:v0",
            idempotency_key=(f"{SKILL_OBJECT_TYPE}:create:{tenant_id}:{skill.id}"),
            shared_with_tenant=self.personal_owner is None,
        )
        return await self.get_detail(tenant_id, name)
