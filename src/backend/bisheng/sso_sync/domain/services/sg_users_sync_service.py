"""Service for SG (首钢) user sync payloads."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from bisheng.core.context.tenant import (
    bypass_tenant_filter,
    current_tenant_id,
    set_current_tenant_id,
)
from bisheng.database.models.department import DepartmentDao, UserDepartmentDao
from bisheng.database.models.tenant import ROOT_TENANT_ID
from bisheng.department.domain.services.department_change_handler import (
    DepartmentChangeHandler,
)
from bisheng.sso_sync.domain.constants import SG_SOURCE
from bisheng.sso_sync.domain.schemas.sg_payloads import (
    SgDataInfoItem,
    SgDataInfos,
    SgDataPayload,
    SgDepartmentSyncResponse,
    SgEsbPayload,
    SgUserFieldItem,
    SgUserSyncRequest,
)
from bisheng.user.domain.models.user import User, UserDao

logger = logging.getLogger(__name__)


@dataclass
class _NormalizedUserItem:
    index: int
    payload: SgUserFieldItem
    external_id: str
    dept_external_id: str
    remark: str
    delete_flag: int


class SgUsersSyncService:
    """Apply SG user sync to ``user`` table."""

    SOURCE = SG_SOURCE
    DISABLE_SOURCE = "sg_sync"

    @classmethod
    async def execute(
        cls,
        payload: SgUserSyncRequest,
    ) -> SgDepartmentSyncResponse:
        normalized: list[_NormalizedUserItem] = []
        info_map: dict[int, SgDataInfoItem] = {}

        for idx, item in enumerate(payload.fields):
            try:
                external_id = (item.code or "").strip()
                if not external_id:
                    raise ValueError("code is required")
                dept_external_id = (item.desc34 or "").strip()
                if not dept_external_id:
                    raise ValueError("desc34 is required")
                normalized.append(
                    _NormalizedUserItem(
                        index=idx,
                        payload=item,
                        external_id=external_id,
                        dept_external_id=dept_external_id,
                        remark=(item.desc1 or "").strip(),
                        delete_flag=cls._parse_delete_flag(item.desc93),
                    )
                )
            except Exception as exc:
                info_map[idx] = cls._failed_info(
                    item=item,
                    code=(item.code or "").strip(),
                    mdm_id=payload.mdm_id,
                    message=str(exc),
                )

        with bypass_tenant_filter():
            token = set_current_tenant_id(ROOT_TENANT_ID)
            try:
                for row in normalized:
                    info_map[row.index] = await cls._apply_one(row, payload.mdm_id)
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
        row: _NormalizedUserItem,
        mdm_id: int,
    ) -> SgDataInfoItem:
        try:
            dept = await DepartmentDao.aget_by_source_external_id(
                cls.SOURCE,
                row.dept_external_id,
            )
            if dept is None:
                # Fallback for historical rows without source tagging.
                dept = await DepartmentDao.aget_by_external_id(
                    row.dept_external_id,
                    ROOT_TENANT_ID,
                )
            if dept is None or dept.id is None:
                raise ValueError(
                    f"department external_id={row.dept_external_id} not found",
                )

            user = await UserDao.aget_by_source_external_id(
                cls.SOURCE,
                row.external_id,
            )
            if user is None:
                user = User(
                    user_name=row.remark or row.external_id,
                    email=None,
                    phone_number=None,
                    dept_id=str(int(dept.id)),
                    remark=row.remark or None,
                    source=cls.SOURCE,
                    external_id=row.external_id,
                    password="",
                    delete=row.delete_flag,
                    disable_source=(cls.DISABLE_SOURCE if row.delete_flag == 1 else None),
                )
                user = await UserDao.add_user_and_default_role(user)
            else:
                user.dept_id = str(int(dept.id))
                user.remark = row.remark or None
                user.delete = row.delete_flag
                user.disable_source = cls.DISABLE_SOURCE if row.delete_flag == 1 else None
                await UserDao.aupdate_user(user)

            if user.user_id is None:
                raise ValueError("user_id missing after user upsert")
            await cls._ensure_primary_membership(int(user.user_id), int(dept.id))

            return SgDataInfoItem(
                uuid=row.payload.uuid,
                code=row.external_id,
                status="0",
                version=str(mdm_id),
                errorText="",
            )
        except Exception as exc:
            logger.warning(
                "SG user sync failed for code=%s: %s",
                row.external_id,
                exc,
            )
            return cls._failed_info(
                item=row.payload,
                code=row.external_id,
                mdm_id=mdm_id,
                message=str(exc),
            )

    @classmethod
    async def _ensure_primary_membership(
        cls,
        user_id: int,
        dept_id: int,
    ) -> None:
        """Ensure ``user_department`` row exists so department members API works."""
        current = await UserDepartmentDao.aget_user_primary_department(user_id)
        if current is not None and current.department_id == dept_id:
            await cls._sync_department_member_tuples(user_id, [dept_id])
            return
        if current is not None:
            await UserDepartmentDao.aset_primary_flag(
                user_id,
                current.department_id,
                is_primary=0,
            )
        existing = await UserDepartmentDao.aget_membership(user_id, dept_id)
        if existing is not None:
            await UserDepartmentDao.aset_primary_flag(
                user_id,
                dept_id,
                is_primary=1,
            )
        else:
            await UserDepartmentDao.aadd_member(
                user_id,
                dept_id,
                is_primary=1,
                source=cls.SOURCE,
            )
        await cls._sync_department_member_tuples(user_id, [dept_id])

    @classmethod
    async def _sync_department_member_tuples(
        cls,
        user_id: int,
        dept_ids: list[int],
    ) -> None:
        """Best-effort OpenFGA ``department#member`` tuple sync (idempotent)."""
        if not dept_ids:
            return
        ops = []
        for dept_id in dict.fromkeys(int(did) for did in dept_ids):
            ops.extend(DepartmentChangeHandler.on_members_added(dept_id, [user_id]))
        await DepartmentChangeHandler.execute_async(ops)

    @staticmethod
    def _parse_delete_flag(status: str) -> int:
        raw = (status or "").strip()
        if raw == "01":
            return 0
        if raw == "02":
            return 1
        raise ValueError("desc93 must be 01(on-job) or 02(off-job)")

    @staticmethod
    def _failed_info(
        *,
        item: SgUserFieldItem,
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
