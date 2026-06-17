"""Service for SG (首钢) organization sync payloads."""

from __future__ import annotations

import time
from dataclasses import dataclass
import logging

from bisheng.core.context.tenant import (
    bypass_tenant_filter,
    current_tenant_id,
    set_current_tenant_id,
)
from bisheng.database.models.department import Department, DepartmentDao
from bisheng.database.models.tenant import ROOT_TENANT_ID
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
        cls, payload: SgDepartmentSyncRequest,
    ) -> SgDepartmentSyncResponse:
        normalized: list[_NormalizedItem] = []
        info_map: dict[int, SgDataInfoItem] = {}
        unresolved: set[int] = set()

        for idx, item in enumerate(payload.fields):
            try:
                code = (item.code or '').strip()
                if not code:
                    raise ValueError('code is required')
                status = cls._parse_status(item.state)
                normalized_item = _NormalizedItem(
                    index=idx,
                    payload=item,
                    code=code,
                    parent_code=(item.pid or '').strip(),
                    name=(item.remark or '').strip() or code,
                    status=status,
                )
                normalized.append(normalized_item)
                unresolved.add(idx)
            except Exception as exc:  # noqa: BLE001
                info_map[idx] = cls._failed_info(
                    item=item,
                    code=(item.code or '').strip(),
                    mdm_id=payload.mdm_id,
                    message=str(exc),
                )

        max_round = len(normalized) + 1
        with bypass_tenant_filter():
            token = set_current_tenant_id(ROOT_TENANT_ID)
            try:
                for _ in range(max_round):
                    progressed = False
                    for row in normalized:
                        if row.index not in unresolved:
                            continue
                        if row.parent_code and cls._parent_still_pending(
                            row.parent_code, normalized, unresolved,
                        ):
                            continue
                        info_map[row.index] = await cls._apply_one(row, payload.mdm_id)
                        unresolved.remove(row.index)
                        progressed = True
                    if not unresolved or not progressed:
                        break
            finally:
                current_tenant_id.reset(token)

        if unresolved:
            idx_to_row = {row.index: row for row in normalized}
            for idx in sorted(unresolved):
                row = idx_to_row[idx]
                msg = (
                    f'parent external_id={row.parent_code} not found or unresolved'
                    if row.parent_code else 'item unresolved'
                )
                info_map[idx] = cls._failed_info(
                    item=row.payload,
                    code=row.code,
                    mdm_id=payload.mdm_id,
                    message=msg,
                )

        ordered_infos = [info_map[i] for i in sorted(info_map.keys())]
        all_success = all(one.status == '0' for one in ordered_infos)
        response = SgDepartmentSyncResponse(
            ESB=SgEsbPayload(
                CODE='0' if all_success else '1',
                DESC='success' if all_success else 'partial_failure',
                DATA=SgDataPayload(
                    UUID=payload.uuid,
                    DATAINFOS=SgDataInfos(DATAINFO=ordered_infos),
                ),
            ),
        )
        return response

    @classmethod
    async def _apply_one(
        cls, row: _NormalizedItem, mdm_id: int,
    ) -> SgDataInfoItem:
        try:
            parent: Department | None = None
            if row.parent_code:
                parent = await DepartmentDao.aget_by_external_id(
                    row.parent_code, ROOT_TENANT_ID,
                )
                if parent is None:
                    raise ValueError(
                        f'parent external_id={row.parent_code} not found',
                    )

            ts = int(time.time())
            parent_id = (
                int(parent.id)
                if parent is not None and parent.id is not None
                else None
            )
            parent_path = parent.path if parent is not None else ''
            await DepartmentDao.aupsert_by_external_id(
                source=cls.SOURCE,
                external_id=row.code,
                name=row.name,
                parent_id=parent_id,
                path=parent_path,
                sort_order=0,
                last_sync_ts=ts,
                tenant_id=ROOT_TENANT_ID,
            )
            if row.status == 1:
                await DepartmentDao.aarchive_by_external_id(
                    cls.SOURCE, row.code, ts,
                )
            return SgDataInfoItem(
                uuid=row.payload.uuid,
                code=row.code,
                status='0',
                version=str(mdm_id),
                errorText='',
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                'SG department sync failed for code=%s: %s', row.code, exc,
            )
            return cls._failed_info(
                item=row.payload,
                code=row.code,
                mdm_id=mdm_id,
                message=str(exc),
            )

    @staticmethod
    def _parse_status(value: str) -> int:
        raw = (value or '').strip()
        if raw not in {'0', '1'}:
            raise ValueError('state must be 0(enabled) or 1(disabled)')
        return int(raw)

    @staticmethod
    def _parent_still_pending(
        parent_code: str,
        normalized: list[_NormalizedItem],
        unresolved: set[int],
    ) -> bool:
        for row in normalized:
            if row.code == parent_code and row.index in unresolved:
                return True
        return False

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
            status='1',
            version=str(mdm_id),
            errorText=message,
        )

