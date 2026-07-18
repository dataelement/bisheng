"""DingTalk Provider — stub implementation.

API Reference: https://open.dingtalk.com/document/orgapp/obtain-the-department-list-v2
Authentication: app_key + app_secret → access_token
Departments: POST /topapi/v2/department/listsub
Members: POST /topapi/v2/user/list

Full implementation deferred to a future release.
"""

from typing import Optional

from bisheng.common.errcode.org_sync import OrgSyncProviderError
from bisheng.org_sync.domain.providers.base import OrgSyncProvider
from bisheng.org_sync.domain.schemas.remote_dto import RemoteDepartmentDTO, RemoteMemberDTO


class DingTalkProvider(OrgSyncProvider):
    """DingTalk provider — not yet implemented."""

    async def authenticate(self) -> bool:
        raise OrgSyncProviderError(msg='DingTalk provider not implemented')

    async def fetch_departments(
        self, root_dept_ids: Optional[list[str]] = None,
    ) -> list[RemoteDepartmentDTO]:
        raise OrgSyncProviderError(msg='DingTalk provider not implemented')

    async def fetch_members(
        self, department_ids: Optional[list[str]] = None,
    ) -> list[RemoteMemberDTO]:
        raise OrgSyncProviderError(msg='DingTalk provider not implemented')

    async def test_connection(self) -> dict:
        raise OrgSyncProviderError(msg='DingTalk provider not implemented')
