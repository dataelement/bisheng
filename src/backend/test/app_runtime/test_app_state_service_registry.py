"""T048 — an application exists, has one identity, and its versions never change.

Covers the creation half of the domain (``AppProvisionService.create_draft``,
``AppStateService.stage_version`` and the version-selection rule) plus the
``app_version`` write discipline. The five state actions are
``test_app_state_actions.py``.
"""

from __future__ import annotations

import pytest

from bisheng.app_runtime.domain.constants import AppState
from bisheng.common.errcode.app_factory import AppSlugConflictError

pytestmark = pytest.mark.usefixtures("app_db")


async def _load(app_db, app_id):
    from bisheng.database.models.app import AppDao

    async with app_db() as session:
        return await AppDao.aget(session, app_id)


class TestCreateDraft:
    async def test_create_app_persists_as_third_type_with_owner_and_state_draft(
        self, app_db, app_owner, fake_permission_projection
    ):
        """AC-01 / AC-11: identity, name, description, owner, tenant, state — and the owner grant."""
        from bisheng.app_runtime.domain.services.app_provision_service import AppProvisionService

        app_id = await AppProvisionService.create_draft(
            name="Sales Copilot",
            slug=None,
            description="an internal tool",
            owner_user_id=app_owner.user_id,
            tenant_id=1,
        )

        row = await _load(app_db, app_id)
        assert row is not None
        assert (row.name, row.description, row.owner_user_id, row.tenant_id) == (
            "Sales Copilot",
            "an internal tool",
            app_owner.user_id,
            1,
        )
        assert row.state == AppState.DRAFT.value
        assert row.slug == "sales-copilot"
        # AC-11 "visible to its owner only" *is* the CUSTOM owner projection —
        # creating a row without it yields an app nobody can see or manage.
        assert "authorize_created" in fake_permission_projection.actions()

    async def test_slug_from_manifest_or_generated_from_name(self, app_db, app_owner, fake_permission_projection):
        """AC-08 — a declared slug wins; otherwise the display name is slugified."""
        from bisheng.app_runtime.domain.services.app_provision_service import AppProvisionService

        declared = await AppProvisionService.create_draft(
            name="Anything At All", slug="my-tool", description=None, owner_user_id=app_owner.user_id, tenant_id=1
        )
        generated = await AppProvisionService.create_draft(
            name="Weekly  Report_v2", slug=None, description=None, owner_user_id=app_owner.user_id, tenant_id=1
        )

        assert (await _load(app_db, declared)).slug == "my-tool"
        assert (await _load(app_db, generated)).slug == "weekly-report-v2"

    async def test_chinese_name_still_yields_a_usable_slug(self, app_db, app_owner, fake_permission_projection):
        """A Chinese display name leaves no ASCII behind — the entry path still needs one."""
        from bisheng.app_runtime.domain.services.app_provision_service import AppProvisionService

        app_id = await AppProvisionService.create_draft(
            name="销售助手", slug=None, description=None, owner_user_id=app_owner.user_id, tenant_id=1
        )
        slug = (await _load(app_db, app_id)).slug
        assert slug.startswith("app-") and slug.isascii()

    async def test_slug_global_unique_across_tenants_rejects_16103(
        self, app_db, app_owner, sub_tenant, fake_permission_projection
    ):
        """AC-08 — the entry segment is resolved before any tenant context exists,
        so a collision with *any* tenant's app is a refusal, not a rename."""
        from bisheng.app_runtime.domain.services.app_provision_service import AppProvisionService

        await AppProvisionService.create_draft(
            name="Shared Name", slug="taken-slug", description=None, owner_user_id=app_owner.user_id, tenant_id=1
        )

        with pytest.raises(AppSlugConflictError) as excinfo:
            await AppProvisionService.create_draft(
                name="Other tenant app",
                slug="taken-slug",
                description=None,
                owner_user_id=sub_tenant.admin_user_id,
                tenant_id=sub_tenant.tenant_id,
            )
        assert excinfo.value.code == 16103

    async def test_generated_slug_is_disambiguated_not_refused(self, app_db, app_owner, fake_permission_projection):
        """Two people naming an app the same must not deadlock each other: only a
        *declared* slug is a promise the platform refuses to break."""
        from bisheng.app_runtime.domain.services.app_provision_service import AppProvisionService

        first = await AppProvisionService.create_draft(
            name="Report Tool", slug=None, description=None, owner_user_id=app_owner.user_id, tenant_id=1
        )
        second = await AppProvisionService.create_draft(
            name="Report Tool", slug=None, description=None, owner_user_id=app_owner.user_id, tenant_id=1
        )
        assert (await _load(app_db, first)).slug == "report-tool"
        assert (await _load(app_db, second)).slug == "report-tool-2"

    async def test_slug_immutable_name_mutable_and_duplicable(self, app_db, app_factory, app_owner, tenant_admins):
        """AC-01 / AC-08 — renaming never moves the entry URL, and names may repeat."""
        from bisheng.app_runtime.domain.services.app_meta_service import EDITABLE_FIELDS, AppMetaService

        assert "slug" not in EDITABLE_FIELDS

        first, _ = await app_factory(name="Same Name", slug="stable-slug")
        second, _ = await app_factory(name="Same Name", slug="other-slug")
        assert first.name == second.name

        await AppMetaService.update_meta(app_id=first.id, name="Renamed", actor=app_owner.payload)
        row = await _load(app_db, first.id)
        assert (row.name, row.slug) == ("Renamed", "stable-slug")

    async def test_owner_single_and_not_retroactive(self, app_db, app_factory, normal_user, fake_permission_projection):
        """AC-07 — one owner per app, fixed at creation; later ownership changes
        elsewhere do not reach back into apps that already exist."""
        from bisheng.app_runtime.domain.services.app_provision_service import AppProvisionService

        existing, _ = await app_factory()
        original_owner = existing.owner_user_id

        later = await AppProvisionService.create_draft(
            name="Later app", slug=None, description=None, owner_user_id=normal_user.user_id, tenant_id=1
        )

        assert (await _load(app_db, existing.id)).owner_user_id == original_owner
        assert (await _load(app_db, later)).owner_user_id == normal_user.user_id

    async def test_failed_owner_projection_leaves_no_row(self, app_db, app_owner, monkeypatch):
        """A row with no owner grant is invisible to everyone including its owner —
        and it would hold the globally unique slug hostage."""
        from bisheng.app_runtime.domain.services import app_provision_service
        from bisheng.app_runtime.domain.services.app_provision_service import AppProvisionService
        from bisheng.database.models.app import AppDao

        async def _boom(resource_type: str):
            raise RuntimeError("openfga is down")

        monkeypatch.setattr(app_provision_service, "get_f048_resource_adapter", _boom)

        with pytest.raises(RuntimeError):
            await AppProvisionService.create_draft(
                name="Doomed", slug="doomed-slug", description=None, owner_user_id=app_owner.user_id, tenant_id=1
            )

        async with app_db() as session:
            assert await AppDao.aget_by_slug(session, "doomed-slug") is None


class TestVersionRecords:
    async def test_version_insert_only_no_update_method(self, app_db, app_factory):
        """AC-02 — code snapshot, capabilities, injections and tier are one record.

        Enforced structurally: the DAO offers no generic UPDATE, so no writer
        *can* change one of the four in isolation. ``amark_terminal`` is the one
        single-column latch (the approval outcome) and is asserted as such.
        """
        from bisheng.database.models.app_version import AppVersionDao

        writers = [name for name in vars(AppVersionDao) if not name.startswith("_")]
        assert set(writers) == {"ainsert", "aget", "alist_by_app", "amax_version_no", "amark_terminal"}

        _app, version = await app_factory()
        assert version.code_object_key and version.tier_id and version.runtime
        assert version.capabilities == {} and version.injections == {}

    async def test_version_read_by_version_id_requires_app_scope(self, app_db, app_factory, sub_tenant):
        """Pit 31 — ``app_version`` has no tenant column, so a read that starts
        from a bare ``version_id`` leaks another tenant's ``code_object_key``
        (the object key of their source snapshot). Every DAO read takes ``app_id``."""
        import inspect

        from bisheng.database.models.app_version import AppVersionDao

        for name in ("aget", "alist_by_app", "amax_version_no", "amark_terminal"):
            assert "app_id" in inspect.signature(getattr(AppVersionDao, name)).parameters, name

        mine, my_version = await app_factory(tenant_id=1)
        _theirs, their_version = await app_factory(tenant_id=sub_tenant.tenant_id)
        async with app_db() as session:
            # Same version id, wrong app scope → nothing, not the other row.
            assert await AppVersionDao.aget(session, mine.id, their_version.id) is None
            assert await AppVersionDao.aget(session, mine.id, my_version.id) is not None

    async def test_rejected_or_withdrawn_never_writes_pending(self, app_db, app_factory):
        """AC-05 — a rejected iteration only latches ``terminal_state``; the running
        version keeps serving because nothing else was touched."""
        from bisheng.database.models.app_version import TERMINAL_STATE_REJECTED, AppVersionDao

        app, version = await app_factory(state=AppState.ONLINE.value)
        async with app_db() as session:
            await AppVersionDao.amark_terminal(session, app.id, version.id, TERMINAL_STATE_REJECTED)
            await session.commit()

        row = await _load(app_db, app.id)
        assert row.state == AppState.ONLINE.value
        assert row.pending_version_id is None
        assert row.current_version_id == version.id


class TestStagingAndSelection:
    async def test_stage_version_writes_pending_without_state_change(self, app_db, app_factory):
        """AC-04 — approval while stopped records the version and leaves the app stopped."""
        from bisheng.app_runtime.domain.services.app_state_service import AppStateService

        app, version = await app_factory(state=AppState.STOPPED.value)

        await AppStateService.stage_version(app.id, "next-version-id")

        row = await _load(app_db, app.id)
        assert row.state == AppState.STOPPED.value, "staging a version must not re-enable a stopped app"
        assert row.pending_version_id == "next-version-id"
        assert row.current_version_id == version.id

    async def test_resume_publish_pick_pending_then_current(self, app_db, app_factory):
        """The one 取版 rule: ``pending_version_id ?? current_version_id``."""
        from bisheng.app_runtime.domain.services.app_state_service import AppStateService

        app, version = await app_factory(state=AppState.STOPPED.value)
        assert AppStateService._pick_version(app) == version.id

        await AppStateService.stage_version(app.id, "next-version-id")
        staged = await _load(app_db, app.id)
        assert AppStateService._pick_version(staged) == "next-version-id"
