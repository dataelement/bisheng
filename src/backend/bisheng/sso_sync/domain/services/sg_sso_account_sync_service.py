"""Service for SG SSO account info sync."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import uuid

from bisheng.sso_sync.domain.schemas.sg_payloads import (
    SgSsoAccountSyncRequest,
    SgSsoAccountSyncResponse,
    SgSsoAccountSyncResultItem,
    SgSsoRowItem,
)
from bisheng.user.domain.models.user import User, UserDao

logger = logging.getLogger(__name__)


@dataclass
class _NormalizedRow:
    row: SgSsoRowItem
    person_no: str
    user_name: str
    guid: str


class SgSsoAccountSyncService:
    """Sync SG SSO account fields to ``user`` table."""

    @classmethod
    async def execute(
        cls, payload: SgSsoAccountSyncRequest,
    ) -> SgSsoAccountSyncResponse:
        results: list[SgSsoAccountSyncResultItem] = []

        for raw in payload.rows:
            try:
                row = cls._normalize_row(raw)
                user = await cls._resolve_target_user(row)
                if user is None:
                    raise ValueError('user not found by PersonNO or Guid')

                target_guid = row.guid or await cls._generate_unique_guid()
                await cls._assert_guid_bindable(target_guid, user)

                user.user_name = row.user_name
                user.guid = target_guid
                await UserDao.aupdate_user(user)

                results.append(
                    SgSsoAccountSyncResultItem(
                        Result='0',
                        UserName=user.user_name,
                        Description='success',
                        Guid=user.guid or '',
                    )
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning('SG SSO account sync row failed: %s', exc)
                results.append(
                    SgSsoAccountSyncResultItem(
                        Result='1',
                        UserName=(raw.user_name or '').strip(),
                        Description=str(exc),
                        Guid=(raw.guid or '').strip(),
                    )
                )

        return SgSsoAccountSyncResponse(TIEM=results)

    @classmethod
    async def _resolve_target_user(cls, row: _NormalizedRow) -> User | None:
        user = await UserDao.aget_by_external_id(row.person_no)
        if user is not None:
            return user
        if row.guid:
            return await UserDao.aget_by_guid(row.guid)
        return None

    @staticmethod
    def _normalize_row(raw: SgSsoRowItem) -> _NormalizedRow:
        person_no = (raw.person_no or '').strip()
        if not person_no:
            raise ValueError('PersonNO is required')
        user_name = (raw.user_name or '').strip()
        if not user_name:
            raise ValueError('UserName is required')
        guid = (raw.guid or '').strip()
        return _NormalizedRow(
            row=raw,
            person_no=person_no,
            user_name=user_name,
            guid=guid,
        )

    @classmethod
    async def _generate_unique_guid(cls) -> str:
        for _ in range(8):
            candidate = str(uuid.uuid4())
            exists = await UserDao.aget_by_guid(candidate)
            if exists is None:
                return candidate
        raise ValueError('failed to generate unique guid')

    @classmethod
    async def _assert_guid_bindable(cls, guid: str, target_user: User) -> None:
        owner = await UserDao.aget_by_guid(guid)
        if owner is None:
            return
        if int(owner.user_id or 0) == int(target_user.user_id or 0):
            return
        raise ValueError('Guid already bound to another user')

