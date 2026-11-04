"""T052 — metadata edits change the description of an app, never its behaviour."""

from __future__ import annotations

import inspect

import pytest

from bisheng.app_runtime.domain.constants import AppAuditAction, AppState
from bisheng.common.errcode.app_factory import AppManageForbiddenError

pytestmark = pytest.mark.usefixtures("app_db")


async def _row(app_db, app_id):
    from bisheng.database.models.app import AppDao

    async with app_db() as session:
        return await AppDao.aget(session, app_id)


class TestUpdateMeta:
    async def test_update_meta_does_not_change_state(self, app_db, app_factory, app_owner):
        """AC-06 — renaming an online app leaves it online (and running)."""
        from bisheng.app_runtime.domain.services.app_meta_service import AppMetaService

        app, _ = await app_factory(state=AppState.ONLINE.value)

        await AppMetaService.update_meta(
            app_id=app.id,
            name="New name",
            description="New description",
            logo="apps/x/logo.png",
            actor=app_owner.payload,
        )

        row = await _row(app_db, app.id)
        assert (row.name, row.description, row.logo) == ("New name", "New description", "apps/x/logo.png")
        assert row.state == AppState.ONLINE.value
        assert row.current_version_id == app.current_version_id

    async def test_update_meta_creates_no_version_record(self, app_db, app_factory, app_owner):
        """AC-06 — metadata is not a capability declaration, so it produces no version."""
        from bisheng.app_runtime.domain.services.app_meta_service import AppMetaService
        from bisheng.database.models.app_version import AppVersionDao

        app, _ = await app_factory()
        async with app_db() as session:
            before = len(await AppVersionDao.alist_by_app(session, app.id))

        await AppMetaService.update_meta(app_id=app.id, name="Renamed", actor=app_owner.payload)

        async with app_db() as session:
            after = len(await AppVersionDao.alist_by_app(session, app.id))
        assert after == before

    async def test_update_meta_audited(self, app_db, app_factory, app_owner, audit_sink):
        """AC-06 — ``app.meta_update``, naming which fields moved."""
        from bisheng.app_runtime.domain.services.app_meta_service import AppMetaService

        app, _ = await app_factory()
        await AppMetaService.update_meta(app_id=app.id, name="Renamed", logo="apps/x/logo.png", actor=app_owner.payload)

        rows = [row for row in audit_sink if row["action"] == AppAuditAction.META_UPDATE.value]
        assert len(rows) == 1
        assert rows[0]["target_type"] == "app" and rows[0]["target_id"] == app.id
        assert rows[0]["metadata"]["fields"] == ["logo", "name"]

    async def test_no_op_patch_writes_nothing(self, app_db, app_factory, app_owner, audit_sink):
        """An unchanged patch is not an event: a "系统操作" page full of no-op
        renames is how a real change gets missed."""
        from bisheng.app_runtime.domain.services.app_meta_service import AppMetaService

        app, _ = await app_factory(name="Stable")
        await AppMetaService.update_meta(app_id=app.id, name="Stable", actor=app_owner.payload)
        assert audit_sink == []

    async def test_slug_not_updatable(self, app_db, app_factory, app_owner):
        """AC-08 — the entry identity is already printed on links and QR codes."""
        from bisheng.app_runtime.domain.services.app_meta_service import EDITABLE_FIELDS, AppMetaService

        assert "slug" not in EDITABLE_FIELDS
        assert "slug" not in inspect.signature(AppMetaService.update_meta).parameters

        app, _ = await app_factory(slug="fixed-slug")
        await AppMetaService.update_meta(app_id=app.id, name="Renamed", actor=app_owner.payload)
        assert (await _row(app_db, app.id)).slug == "fixed-slug"

    async def test_non_owner_non_admin_rejected(self, app_db, app_factory, normal_user, tenant_admins):
        from bisheng.app_runtime.domain.services.app_meta_service import AppMetaService

        app, _ = await app_factory()
        with pytest.raises(AppManageForbiddenError):
            await AppMetaService.update_meta(app_id=app.id, name="Hijacked", actor=normal_user.payload)


class TestSingleImplementation:
    async def test_same_implementation_used_by_pipeline(self, app_db, app_factory):
        """AC-06 — F055's "metadata lands with the deploy" calls *this* method.

        Asserted two ways, because either alone is weak: the pipeline's source
        must name the service (a second implementation would not), and the
        service must accept exactly the keyword set the pipeline passes (a
        signature drift would only surface at runtime, on a worker).
        """
        from bisheng.app_publish.domain.services import publish_pipeline_service
        from bisheng.app_runtime.domain.services.app_meta_service import AppMetaService

        source = inspect.getsource(publish_pipeline_service.PublishPipelineService._update_meta)
        assert "AppMetaService.update_meta(" in source

        parameters = inspect.signature(AppMetaService.update_meta).parameters
        for keyword in ("app_id", "name", "description", "logo"):
            assert keyword in parameters, f"F055 passes {keyword}= and would break"

        # And it really writes through that path, with the logo stored as the
        # object name it was given — a presigned URL would expire in a day.
        app, _ = await app_factory()
        await AppMetaService.update_meta(app_id=app.id, name="From pipeline", description="d", logo="apps/a/icon.png")
        assert (await _row(app_db, app.id)).logo == "apps/a/icon.png"
