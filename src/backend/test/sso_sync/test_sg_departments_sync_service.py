"""Tests for ``SgDepartmentsSyncService`` — SG organization sync."""

from __future__ import annotations

from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.sso_sync.domain.schemas.sg_payloads import (
    SgDepartmentFieldItem,
    SgDepartmentSyncRequest,
)

MODULE = "bisheng.sso_sync.domain.services.sg_departments_sync_service"


def _dept(*, dept_id: int = 100, path: str = "/1/100/"):
    return SimpleNamespace(id=dept_id, path=path)


def _request(*fields: SgDepartmentFieldItem, mdm_id: int = 42, uuid: str = "batch-uuid"):
    return SgDepartmentSyncRequest(
        mdmId=mdm_id,
        BusinessSystem=1,
        uuid=uuid,
        Field=list(fields),
    )


def _enter_dao_patches(stack: ExitStack, **overrides):
    defaults = {
        f"{MODULE}.DepartmentDao.aget_by_source_external_id": AsyncMock(return_value=None),
        f"{MODULE}.DepartmentDao.aget_by_external_id": AsyncMock(return_value=None),
        f"{MODULE}.DepartmentDao.alist_by_sync_parent_external_id": AsyncMock(return_value=[]),
        "bisheng.department.domain.services.department_change_handler.DepartmentChangeHandler.execute_async": AsyncMock(),
        "bisheng.department.domain.services.department_archive_cleanup_service.DepartmentArchiveCleanupService.arun_for_archived_department": AsyncMock(),
    }
    normalized_overrides = {
        (key if key.startswith(MODULE) or key.startswith("bisheng.") else f"{MODULE}.{key}"): value
        for key, value in overrides.items()
    }
    defaults.update(normalized_overrides)
    for target, mock in defaults.items():
        stack.enter_context(patch(target, mock))


@pytest.mark.asyncio
class TestSgDepartmentsSyncService:
    async def test_root_department_upsert_success(self):
        from bisheng.sso_sync.domain.services.sg_departments_sync_service import (
            SgDepartmentsSyncService,
        )

        payload = _request(
            SgDepartmentFieldItem(uuid="u1", code="D1", remark="Engineering", state="0"),
        )
        with ExitStack() as stack:
            _enter_dao_patches(stack)
            upsert = stack.enter_context(
                patch(
                    f"{MODULE}.DepartmentDao.aupsert_by_external_id",
                    new_callable=AsyncMock,
                )
            )
            archive = stack.enter_context(
                patch(
                    f"{MODULE}.DepartmentDao.aarchive_by_external_id",
                    new_callable=AsyncMock,
                )
            )
            response = await SgDepartmentsSyncService.execute(payload)

        assert response.esb.code == "0"
        assert response.esb.desc == "success"
        infos = response.esb.data.data_infos.data_info
        assert len(infos) == 1
        assert infos[0].status == "0"
        assert infos[0].code == "D1"
        assert infos[0].version == "42"
        upsert.assert_awaited_once()
        archive.assert_not_awaited()

    async def test_child_department_resolves_parent_in_same_batch(self):
        from bisheng.sso_sync.domain.services.sg_departments_sync_service import (
            SgDepartmentsSyncService,
        )

        payload = _request(
            SgDepartmentFieldItem(uuid="u1", code="P1", remark="Parent", state="0"),
            SgDepartmentFieldItem(
                uuid="u2",
                code="C1",
                pid="P1",
                remark="Child",
                state="0",
            ),
        )
        parent = _dept(dept_id=10, path="/1/10/")
        child = SimpleNamespace(id=11, path="/1/10/11/", parent_id=10, sort_order=0)

        async def _upsert(**kwargs):
            if kwargs["external_id"] == "P1":
                return parent
            return child

        async def _get_by_source(_src, ext):
            if ext == "P1":
                return parent
            if ext == "C1":
                return child
            return None

        with ExitStack() as stack:
            _enter_dao_patches(
                stack,
                **{
                    "DepartmentDao.aget_by_source_external_id": AsyncMock(
                        side_effect=_get_by_source,
                    ),
                },
            )
            stack.enter_context(
                patch(
                    f"{MODULE}.DepartmentDao.aget_by_external_id",
                    new_callable=AsyncMock,
                    side_effect=lambda ext, _tid: parent if ext == "P1" else None,
                )
            )
            stack.enter_context(
                patch(
                    f"{MODULE}.DepartmentDao.aupsert_by_external_id",
                    new_callable=AsyncMock,
                    side_effect=_upsert,
                )
            )
            response = await SgDepartmentsSyncService.execute(payload)

        assert response.esb.code == "0"
        infos = response.esb.data.data_infos.data_info
        assert [one.code for one in infos] == ["P1", "C1"]
        assert all(one.status == "0" for one in infos)

    async def test_sg_state_01_treated_as_enabled(self):
        from bisheng.sso_sync.domain.services.sg_departments_sync_service import (
            SgDepartmentsSyncService,
        )

        payload = _request(
            SgDepartmentFieldItem(uuid="u1", code="D1", remark="Active", state="01"),
        )
        with ExitStack() as stack:
            _enter_dao_patches(stack)
            stack.enter_context(
                patch(
                    f"{MODULE}.DepartmentDao.aupsert_by_external_id",
                    new_callable=AsyncMock,
                )
            )
            archive = stack.enter_context(
                patch(
                    f"{MODULE}.DepartmentDao.aarchive_by_external_id",
                    new_callable=AsyncMock,
                )
            )
            response = await SgDepartmentsSyncService.execute(payload)

        assert response.esb.code == "0"
        archive.assert_not_awaited()

    async def test_sg_state_00_triggers_archive(self):
        from bisheng.sso_sync.domain.services.sg_departments_sync_service import (
            SgDepartmentsSyncService,
        )

        payload = _request(
            SgDepartmentFieldItem(uuid="u1", code="D1", remark="Archived", state="00"),
        )
        with ExitStack() as stack:
            _enter_dao_patches(stack)
            stack.enter_context(
                patch(
                    f"{MODULE}.DepartmentDao.aupsert_by_external_id",
                    new_callable=AsyncMock,
                )
            )
            archive = stack.enter_context(
                patch(
                    f"{MODULE}.DepartmentDao.aarchive_by_external_id",
                    new_callable=AsyncMock,
                )
            )
            response = await SgDepartmentsSyncService.execute(payload)

        assert response.esb.code == "0"
        archive.assert_awaited_once()

    async def test_disabled_department_triggers_archive(self):
        from bisheng.sso_sync.domain.services.sg_departments_sync_service import (
            SgDepartmentsSyncService,
        )

        payload = _request(
            SgDepartmentFieldItem(uuid="u1", code="D1", remark="Archived", state="1"),
        )
        with ExitStack() as stack:
            _enter_dao_patches(stack)
            stack.enter_context(
                patch(
                    f"{MODULE}.DepartmentDao.aupsert_by_external_id",
                    new_callable=AsyncMock,
                )
            )
            archive = stack.enter_context(
                patch(
                    f"{MODULE}.DepartmentDao.aarchive_by_external_id",
                    new_callable=AsyncMock,
                )
            )
            response = await SgDepartmentsSyncService.execute(payload)

        assert response.esb.code == "0"
        archive.assert_awaited_once()
        assert archive.await_args.args[:2] == ("sg", "D1")

    async def test_missing_code_returns_row_failure(self):
        from bisheng.sso_sync.domain.services.sg_departments_sync_service import (
            SgDepartmentsSyncService,
        )

        payload = _request(SgDepartmentFieldItem(uuid="u1", code=""))
        response = await SgDepartmentsSyncService.execute(payload)

        assert response.esb.code == "1"
        info = response.esb.data.data_infos.data_info[0]
        assert info.status == "1"
        assert "code is required" in info.error_text

    async def test_invalid_state_returns_row_failure(self):
        from bisheng.sso_sync.domain.services.sg_departments_sync_service import (
            SgDepartmentsSyncService,
        )

        payload = _request(
            SgDepartmentFieldItem(uuid="u1", code="D1", state="9"),
        )
        response = await SgDepartmentsSyncService.execute(payload)

        assert response.esb.code == "1"
        info = response.esb.data.data_infos.data_info[0]
        assert info.status == "1"
        assert "state must be 0/01(enabled) or 1/00(disabled)" in info.error_text

    async def test_child_inserted_before_parent_exists(self):
        from bisheng.sso_sync.domain.services.sg_departments_sync_service import (
            SgDepartmentsSyncService,
        )

        payload = _request(
            SgDepartmentFieldItem(
                uuid="u1",
                code="C1",
                pid="MISSING",
                remark="Child",
                state="0",
            ),
        )
        with ExitStack() as stack:
            _enter_dao_patches(stack)
            stack.enter_context(
                patch(
                    f"{MODULE}.DepartmentDao.aget_by_external_id",
                    new_callable=AsyncMock,
                    return_value=None,
                )
            )
            upsert = stack.enter_context(
                patch(
                    f"{MODULE}.DepartmentDao.aupsert_by_external_id",
                    new_callable=AsyncMock,
                )
            )
            response = await SgDepartmentsSyncService.execute(payload)

        assert response.esb.code == "0"
        info = response.esb.data.data_infos.data_info[0]
        assert info.status == "0"
        upsert.assert_awaited_once()
        assert upsert.await_args.kwargs["sync_parent_external_id"] == "MISSING"
        assert upsert.await_args.kwargs["parent_id"] is None

    async def test_child_relinked_when_parent_arrives_in_later_batch(self):
        from bisheng.sso_sync.domain.services.sg_departments_sync_service import (
            SgDepartmentsSyncService,
        )

        parent = _dept(dept_id=10, path="/1/10/")
        child = SimpleNamespace(
            id=11,
            external_id="C1",
            name="Child",
            parent_id=None,
            path="/11/",
            sort_order=0,
            sync_parent_external_id="P1",
        )
        payload = _request(
            SgDepartmentFieldItem(uuid="u1", code="P1", remark="Parent", state="0"),
        )

        with ExitStack() as stack:
            _enter_dao_patches(
                stack,
                **{
                    "DepartmentDao.aget_by_source_external_id": AsyncMock(
                        side_effect=lambda _src, ext: parent if ext == "P1" else None,
                    ),
                    "DepartmentDao.alist_by_sync_parent_external_id": AsyncMock(
                        return_value=[child],
                    ),
                },
            )
            stack.enter_context(
                patch(
                    f"{MODULE}.DepartmentDao.aget_by_external_id",
                    new_callable=AsyncMock,
                    side_effect=lambda ext, _tid: parent if ext == "P1" else None,
                )
            )
            upsert = stack.enter_context(
                patch(
                    f"{MODULE}.DepartmentDao.aupsert_by_external_id",
                    new_callable=AsyncMock,
                    return_value=parent,
                )
            )
            response = await SgDepartmentsSyncService.execute(payload)

        assert response.esb.code == "0"
        relink_calls = [call for call in upsert.await_args_list if call.kwargs.get("external_id") == "C1"]
        assert len(relink_calls) == 1
        assert relink_calls[0].kwargs["parent_id"] == 10
        assert relink_calls[0].kwargs["sync_parent_external_id"] is None

    async def test_new_child_writes_fga_parent_tuple(self):
        from bisheng.department.domain.services.department_change_handler import (
            DepartmentChangeHandler,
        )
        from bisheng.sso_sync.domain.services.sg_departments_sync_service import (
            SgDepartmentsSyncService,
        )

        payload = _request(
            SgDepartmentFieldItem(uuid="u1", code="P1", remark="Parent", state="0"),
            SgDepartmentFieldItem(
                uuid="u2",
                code="C1",
                pid="P1",
                remark="Child",
                state="0",
            ),
        )
        parent = _dept(dept_id=10, path="/1/10/")
        child = SimpleNamespace(id=11, path="/1/10/11/", parent_id=10, sort_order=0)
        child_created = {"value": False}

        async def _upsert(**kwargs):
            if kwargs["external_id"] == "P1":
                return parent
            child_created["value"] = True
            return child

        async def _get_by_source(_src, ext):
            if ext == "P1":
                return parent
            if ext == "C1" and child_created["value"]:
                return child
            return None

        with ExitStack() as stack:
            _enter_dao_patches(
                stack,
                **{
                    "DepartmentDao.aget_by_source_external_id": AsyncMock(
                        side_effect=_get_by_source,
                    ),
                },
            )
            stack.enter_context(
                patch(
                    f"{MODULE}.DepartmentDao.aget_by_external_id",
                    new_callable=AsyncMock,
                    side_effect=lambda ext, _tid: parent if ext == "P1" else None,
                )
            )
            stack.enter_context(
                patch(
                    f"{MODULE}.DepartmentDao.aupsert_by_external_id",
                    new_callable=AsyncMock,
                    side_effect=_upsert,
                )
            )
            on_created = stack.enter_context(
                patch.object(DepartmentChangeHandler, "on_created", return_value=["created-op"])
            )
            execute = stack.enter_context(
                patch(
                    "bisheng.department.domain.services.department_change_handler.DepartmentChangeHandler.execute_async",
                    new_callable=AsyncMock,
                )
            )
            await SgDepartmentsSyncService.execute(payload)

        on_created.assert_any_call(11, 10)
        assert execute.await_count >= 1

    async def test_archive_triggers_fga_cleanup(self):
        from bisheng.sso_sync.domain.services.sg_departments_sync_service import (
            SgDepartmentsSyncService,
        )

        payload = _request(
            SgDepartmentFieldItem(uuid="u1", code="D1", remark="Archived", state="00"),
        )
        archived = SimpleNamespace(id=99, parent_id=10)
        with ExitStack() as stack:
            _enter_dao_patches(stack)
            stack.enter_context(
                patch(
                    f"{MODULE}.DepartmentDao.aupsert_by_external_id",
                    new_callable=AsyncMock,
                    return_value=archived,
                )
            )
            stack.enter_context(
                patch(
                    f"{MODULE}.DepartmentDao.aarchive_by_external_id",
                    new_callable=AsyncMock,
                    return_value=archived,
                )
            )
            cleanup = stack.enter_context(
                patch(
                    "bisheng.department.domain.services.department_archive_cleanup_service.DepartmentArchiveCleanupService.arun_for_archived_department",
                    new_callable=AsyncMock,
                )
            )
            await SgDepartmentsSyncService.execute(payload)

        cleanup.assert_awaited_once_with(99, reason="sg_department_archive")

    async def test_relink_writes_fga_on_created_when_parent_was_pending(self):
        from bisheng.department.domain.services.department_change_handler import (
            DepartmentChangeHandler,
        )
        from bisheng.sso_sync.domain.services.sg_departments_sync_service import (
            SgDepartmentsSyncService,
        )

        parent = _dept(dept_id=10, path="/1/10/")
        child = SimpleNamespace(
            id=11,
            external_id="C1",
            name="Child",
            parent_id=None,
            path="/11/",
            sort_order=0,
            sync_parent_external_id="P1",
        )
        relinked = SimpleNamespace(id=11, parent_id=10, path="/1/10/11/")
        payload = _request(
            SgDepartmentFieldItem(uuid="u1", code="P1", remark="Parent", state="0"),
        )

        with ExitStack() as stack:
            _enter_dao_patches(
                stack,
                **{
                    "DepartmentDao.aget_by_source_external_id": AsyncMock(
                        side_effect=lambda _src, ext: parent if ext == "P1" else None,
                    ),
                    "DepartmentDao.alist_by_sync_parent_external_id": AsyncMock(
                        return_value=[child],
                    ),
                },
            )
            stack.enter_context(
                patch(
                    f"{MODULE}.DepartmentDao.aget_by_external_id",
                    new_callable=AsyncMock,
                    side_effect=lambda ext, _tid: parent if ext == "P1" else None,
                )
            )
            stack.enter_context(
                patch(
                    f"{MODULE}.DepartmentDao.aupsert_by_external_id",
                    new_callable=AsyncMock,
                    side_effect=lambda **kwargs: relinked if kwargs.get("external_id") == "C1" else parent,
                )
            )
            on_created = stack.enter_context(
                patch.object(DepartmentChangeHandler, "on_created", return_value=["created-op"])
            )
            stack.enter_context(
                patch(
                    "bisheng.department.domain.services.department_change_handler.DepartmentChangeHandler.execute_async",
                    new_callable=AsyncMock,
                )
            )
            await SgDepartmentsSyncService.execute(payload)

        on_created.assert_any_call(11, 10)
