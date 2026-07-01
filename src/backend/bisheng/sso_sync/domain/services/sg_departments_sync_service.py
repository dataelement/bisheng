"""Service for SG (首钢) organization sync payloads."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from bisheng.core.context.tenant import (
    bypass_tenant_filter,
    current_tenant_id,
    set_current_tenant_id,
)
from bisheng.database.models.department import Department, DepartmentDao
from bisheng.database.models.tenant import ROOT_TENANT_ID
from bisheng.department.domain.services.department_archive_cleanup_service import (
    DepartmentArchiveCleanupService,
)
from bisheng.department.domain.services.department_change_handler import (
    DepartmentChangeHandler,
)
from bisheng.sso_sync.domain.constants import SG_SOURCE
from bisheng.sso_sync.domain.schemas.sg_payloads import (
    SgDataInfoItem,
    SgDataInfos,
    SgDataPayload,
    SgDepartmentFieldItem,
    SgDepartmentSyncRequest,
    SgDepartmentSyncResponse,
    SgEsbPayload,
)

logger = logging.getLogger(__name__)


@dataclass
class _NormalizedItem:
    index: int
    payload: SgDepartmentFieldItem
    code: str
    parent_code: str
    name: str
    status: int


class SgDepartmentsSyncService:
    """Apply SG department sync to ``department`` table by ``external_id``."""

    SOURCE = SG_SOURCE

    @classmethod
    async def execute(
        cls,
        payload: SgDepartmentSyncRequest,
    ) -> SgDepartmentSyncResponse:
        normalized: list[_NormalizedItem] = []
        info_map: dict[int, SgDataInfoItem] = {}

        for idx, item in enumerate(payload.fields):
            try:
                code = (item.code or "").strip()
                if not code:
                    raise ValueError("code is required")
                status = cls._parse_status(item.state)
                normalized_item = _NormalizedItem(
                    index=idx,
                    payload=item,
                    code=code,
                    parent_code=cls._normalize_parent_code(item.pid),
                    name=(item.remark or "").strip() or code,
                    status=status,
                )
                normalized.append(normalized_item)
            except Exception as exc:
                info_map[idx] = cls._failed_info(
                    item=item,
                    code=(item.code or "").strip(),
                    mdm_id=payload.mdm_id,
                    message=str(exc),
                )

        parent_cache: dict[str, Department] = {}
        with bypass_tenant_filter():
            token = set_current_tenant_id(ROOT_TENANT_ID)
            try:
                for row in normalized:
                    if row.index in info_map:
                        continue
                    info_map[row.index] = await cls._apply_one(
                        row,
                        payload.mdm_id,
                        parent_cache,
                    )
                    fresh = await DepartmentDao.aget_by_source_external_id(
                        cls.SOURCE,
                        row.code,
                    )
                    if fresh is not None:
                        parent_cache[row.code] = fresh

                await cls._relink_batch_children(normalized, payload.mdm_id, parent_cache)

                for row in normalized:
                    info = info_map.get(row.index)
                    if info is None or info.status != "0":
                        continue
                    await cls._relink_db_children_waiting_for_parent(
                        row.code,
                        payload.mdm_id,
                    )
            finally:
                current_tenant_id.reset(token)

        ordered_infos = [info_map[i] for i in sorted(info_map.keys())]
        all_success = all(one.status == "0" for one in ordered_infos)
        return SgDepartmentSyncResponse(
            ESB=SgEsbPayload(
                CODE="0" if all_success else "1",
                DESC="success" if all_success else "partial_failure",
                DATA=SgDataPayload(
                    UUID=payload.uuid,
                    DATAINFOS=SgDataInfos(DATAINFO=ordered_infos),
                ),
            ),
        )

    @classmethod
    async def _apply_one(
        cls,
        row: _NormalizedItem,
        mdm_id: int,
        parent_cache: dict[str, Department],
    ) -> SgDataInfoItem:
        try:
            existing = await DepartmentDao.aget_by_source_external_id(
                cls.SOURCE,
                row.code,
            )
            old_parent_id = None
            if existing is not None:
                raw_old_parent_id = getattr(existing, "parent_id", None)
                old_parent_id = int(raw_old_parent_id) if raw_old_parent_id is not None else None
            was_archived = existing is not None and (
                getattr(existing, "status", "") == "archived" or getattr(existing, "is_deleted", 0) == 1
            )
            is_new = existing is None

            parent, pending_parent_code = await cls._resolve_parent(
                row.parent_code,
                parent_cache,
            )
            ts = int(time.time())
            parent_id = int(parent.id) if parent is not None and parent.id is not None else None
            parent_path = parent.path if parent is not None else ""
            dept = await DepartmentDao.aupsert_by_external_id(
                source=cls.SOURCE,
                external_id=row.code,
                name=row.name,
                parent_id=parent_id,
                path=parent_path,
                sort_order=0,
                last_sync_ts=ts,
                tenant_id=ROOT_TENANT_ID,
                sync_parent_external_id=pending_parent_code,
            )
            if row.status == 1:
                archived = await DepartmentDao.aarchive_by_external_id(
                    cls.SOURCE,
                    row.code,
                    ts,
                )
                if archived is not None and archived.id is not None:
                    await DepartmentArchiveCleanupService.arun_for_archived_department(
                        int(archived.id),
                        reason="sg_department_archive",
                    )
            elif dept is not None and dept.id is not None:
                raw_parent_id = getattr(dept, "parent_id", None)
                new_parent_id = int(raw_parent_id) if raw_parent_id is not None else None
                await cls._sync_department_tree_fga(
                    int(dept.id),
                    old_parent_id=old_parent_id,
                    new_parent_id=new_parent_id,
                    is_new=is_new,
                    was_archived=was_archived,
                )
            return SgDataInfoItem(
                uuid=row.payload.uuid,
                code=row.code,
                status="0",
                version=str(mdm_id),
                errorText="",
            )
        except Exception as exc:
            logger.warning(
                "SG department sync failed for code=%s: %s",
                row.code,
                exc,
            )
            return cls._failed_info(
                item=row.payload,
                code=row.code,
                mdm_id=mdm_id,
                message=str(exc),
            )

    @classmethod
    async def _relink_batch_children(
        cls,
        normalized: list[_NormalizedItem],
        mdm_id: int,
        parent_cache: dict[str, Department],
    ) -> None:
        max_round = len(normalized) + 1
        for _ in range(max_round):
            progressed = False
            for row in normalized:
                if not row.parent_code:
                    continue
                parent = parent_cache.get(row.parent_code)
                if parent is None:
                    parent = await DepartmentDao.aget_by_external_id(
                        row.parent_code,
                        ROOT_TENANT_ID,
                    )
                if parent is None:
                    continue
                parent_cache[row.parent_code] = parent
                child = await DepartmentDao.aget_by_source_external_id(
                    cls.SOURCE,
                    row.code,
                )
                if child is None:
                    continue
                if cls._needs_relink(child, parent):
                    await cls._relink_child_to_parent(child, parent, mdm_id)
                    progressed = True
            if not progressed:
                break

    @classmethod
    async def _relink_db_children_waiting_for_parent(
        cls,
        parent_code: str,
        mdm_id: int,
    ) -> None:
        parent = await DepartmentDao.aget_by_external_id(
            parent_code,
            ROOT_TENANT_ID,
        )
        if parent is None or parent.id is None:
            return
        children = await DepartmentDao.alist_by_sync_parent_external_id(
            cls.SOURCE,
            parent_code,
            ROOT_TENANT_ID,
        )
        for child in children:
            if cls._needs_relink(child, parent):
                await cls._relink_child_to_parent(child, parent, mdm_id)

    @classmethod
    async def _resolve_parent(
        cls,
        parent_code: str,
        parent_cache: dict[str, Department],
    ) -> tuple[Department | None, str | None]:
        if not parent_code:
            return None, None
        parent = parent_cache.get(parent_code)
        if parent is None:
            parent = await DepartmentDao.aget_by_external_id(
                parent_code,
                ROOT_TENANT_ID,
            )
        if parent is not None:
            parent_cache[parent_code] = parent
            return parent, None
        return None, parent_code

    @staticmethod
    def _needs_relink(child: Department, parent: Department) -> bool:
        if getattr(child, "sync_parent_external_id", None):
            return True
        return (getattr(child, "parent_id", None) or 0) != (getattr(parent, "id", None) or 0)

    @classmethod
    async def _relink_child_to_parent(
        cls,
        child: Department,
        parent: Department,
        mdm_id: int,
    ) -> None:
        old_parent_id = int(child.parent_id) if getattr(child, "parent_id", None) is not None else None
        ts = int(time.time())
        dept = await DepartmentDao.aupsert_by_external_id(
            source=cls.SOURCE,
            external_id=str(child.external_id),
            name=child.name,
            parent_id=int(parent.id),
            path=parent.path or "",
            sort_order=child.sort_order or 0,
            last_sync_ts=ts,
            tenant_id=ROOT_TENANT_ID,
            sync_parent_external_id=None,
        )
        if dept is not None and dept.id is not None:
            raw_parent_id = getattr(dept, "parent_id", None)
            new_parent_id = int(raw_parent_id) if raw_parent_id is not None else None
            await cls._sync_department_tree_fga(
                int(dept.id),
                old_parent_id=old_parent_id,
                new_parent_id=new_parent_id,
                is_new=False,
                was_archived=False,
            )

    @classmethod
    async def _sync_department_tree_fga(
        cls,
        dept_id: int,
        *,
        old_parent_id: int | None,
        new_parent_id: int | None,
        is_new: bool,
        was_archived: bool,
    ) -> None:
        """Keep OpenFGA department parent edges aligned with MySQL tree changes."""
        if new_parent_id is None:
            if old_parent_id is not None and not is_new and not was_archived:
                ops = DepartmentChangeHandler.on_archived(dept_id, old_parent_id)
                await DepartmentChangeHandler.execute_async(ops)
            return

        if is_new or was_archived:
            ops = DepartmentChangeHandler.on_created(dept_id, new_parent_id)
        elif old_parent_id != new_parent_id:
            if old_parent_id is None:
                ops = DepartmentChangeHandler.on_created(dept_id, new_parent_id)
            else:
                ops = DepartmentChangeHandler.on_moved(
                    dept_id,
                    old_parent_id,
                    new_parent_id,
                )
        else:
            return

        await DepartmentChangeHandler.execute_async(ops)

    @staticmethod
    def _normalize_parent_code(value: str) -> str:
        raw = (value or "").strip()
        if not raw or raw == "0":
            return ""
        return raw

    @staticmethod
    def _parse_status(value: str) -> int:
        raw = (value or "").strip()
        if raw == "01":
            return 0
        if raw == "02":
            return 1
        raise ValueError(
            "state must be 01(enabled) or 02(disabled)",
        )

    @staticmethod
    def _failed_info(
        *,
        item: SgDepartmentFieldItem,
        code: str,
        mdm_id: int,
        message: str,
    ) -> SgDataInfoItem:
        return SgDataInfoItem(
            uuid=item.uuid,
            code=code,
            status="1",
            version=str(mdm_id),
            errorText=message,
        )
