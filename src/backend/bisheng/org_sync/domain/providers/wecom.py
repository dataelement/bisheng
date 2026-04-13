"""WeChat Work (WeCom) Provider — stub implementation.

API Reference: https://developer.work.weixin.qq.com/document/path/90208
Authentication: corp_id + corp_secret → access_token
Departments: GET /cgi-bin/department/list
Members: GET /cgi-bin/user/list?department_id=X

Full implementation deferred to a future release.
"""

from typing import Optional

from bisheng.common.errcode.org_sync import OrgSyncProviderError
from bisheng.org_sync.domain.providers.base import OrgSyncProvider
from bisheng.org_sync.domain.schemas.remote_dto import RemoteDepartmentDTO, RemoteMemberDTO


class WeComProvider(OrgSyncProvider):
    """WeChat Work provider — not yet implemented."""

    async def authenticate(self) -> bool:
        raise OrgSyncProviderError(msg='WeChat Work provider not implemented')

    async def fetch_departments(
        self, root_dept_ids: Optional[list[str]] = None,
    ) -> list[RemoteDepartmentDTO]:
        raise OrgSyncProviderError(msg='WeChat Work provider not implemented')

    async def fetch_members(
        self, department_ids: Optional[list[str]] = None,
    ) -> list[RemoteMemberDTO]:
        raise OrgSyncProviderError(msg='WeChat Work provider not implemented')

    async def test_connection(self) -> dict:
        raise OrgSyncProviderError(msg='WeChat Work provider not implemented')
