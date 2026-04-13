"""Generic REST API Provider — full implementation.

Supports any third-party system that exposes department/member data via REST.
Configuration is entirely in auth_config:
  - departments_url / members_url: endpoint URLs
  - api_key + param_location: for header/query auth
  - server_addr + username + password: for basic auth
  - field_mapping: maps provider-specific field names to standard DTO fields
"""

from typing import Optional

import httpx
from loguru import logger

from bisheng.common.errcode.org_sync import OrgSyncAuthFailedError, OrgSyncFetchError
from bisheng.org_sync.domain.providers.base import OrgSyncProvider
from bisheng.org_sync.domain.schemas.remote_dto import RemoteDepartmentDTO, RemoteMemberDTO

# Default field mapping if not provided
DEFAULT_FIELD_MAPPING = {
    'dept_id': 'id',
    'dept_name': 'name',
    'dept_parent_id': 'parentId',
    'member_id': 'employeeId',
    'member_name': 'fullName',
    'member_email': 'email',
    'member_phone': 'mobile',
    'member_primary_dept': 'mainDepartment',
    'member_secondary_depts': 'otherDepartments',
    'member_status': 'status',
}


class GenericAPIProvider(OrgSyncProvider):

    def __init__(self, auth_config: dict):
        super().__init__(auth_config)
        self._field_mapping = {
            **DEFAULT_FIELD_MAPPING,
            **auth_config.get('field_mapping', {}),
        }

    # ------------------------------------------------------------------
    # HTTP helper
    # ------------------------------------------------------------------

    def _build_auth(self) -> tuple[dict, httpx.BasicAuth | None]:
        """Build auth headers/params and optional BasicAuth from config."""
        headers: dict = {}
        params: dict = {}
        basic_auth: httpx.BasicAuth | None = None

        api_key = self.auth_config.get('api_key')
        if api_key:
            location = self.auth_config.get('param_location', 'header')
            if location == 'query':
                params['api_key'] = api_key
            else:
                headers['Authorization'] = f'Bearer {api_key}'
        else:
            username = self.auth_config.get('username', '')
            password = self.auth_config.get('password', '')
            if username:
                basic_auth = httpx.BasicAuth(username, password)

        return headers, basic_auth

    async def _fetch_json(self, client: httpx.AsyncClient, url: str) -> dict:
        """Fetch JSON from a URL with configured auth."""
        headers, basic_auth = self._build_auth()
        try:
            resp = await client.get(url, headers=headers, auth=basic_auth)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            raise OrgSyncFetchError(
                msg=f'Generic API HTTP error {e.response.status_code}: {url}',
            )
        except Exception as e:
            raise OrgSyncFetchError(msg=f'Generic API request failed: {e}')

    def _get_field(self, item: dict, mapping_key: str, default=None):
        """Extract a field from item using the configured field mapping."""
        field_name = self._field_mapping.get(mapping_key, '')
        return item.get(field_name, default)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def authenticate(self) -> bool:
        """Validate that we can reach at least one configured URL."""
        test_url = (
            self.auth_config.get('departments_url')
            or self.auth_config.get('members_url')
            or self.auth_config.get('server_addr')
            or self.auth_config.get('endpoint_url')
        )
        if not test_url:
            raise OrgSyncAuthFailedError(msg='No endpoint URL configured')

        async with httpx.AsyncClient(timeout=30) as client:
            headers, basic_auth = self._build_auth()
            try:
                resp = await client.get(test_url, headers=headers, auth=basic_auth)
                resp.raise_for_status()
            except Exception as e:
                raise OrgSyncAuthFailedError(msg=f'Authentication failed: {e}')
        return True

    async def fetch_departments(
        self, root_dept_ids: Optional[list[str]] = None,
    ) -> list[RemoteDepartmentDTO]:
        url = self.auth_config.get('departments_url')
        if not url:
            raise OrgSyncFetchError(msg='departments_url not configured')

        async with httpx.AsyncClient(timeout=60) as client:
            data = await self._fetch_json(client, url)

        # Accept {"departments": [...]} or top-level list
        items = data if isinstance(data, list) else data.get('departments', [])
        if not isinstance(items, list):
            raise OrgSyncFetchError(
                msg=f'Unexpected departments response format: {type(items).__name__}',
            )

        results = []
        for item in items:
            ext_id = str(self._get_field(item, 'dept_id', ''))
            if not ext_id:
                logger.warning(f'Skipping department with missing ID: {item}')
                continue

            parent_id = self._get_field(item, 'dept_parent_id')
            if parent_id is not None:
                parent_id = str(parent_id) if parent_id else None

            # Apply root scope filter if provided
            if root_dept_ids and ext_id not in root_dept_ids and parent_id not in root_dept_ids:
                continue

            results.append(RemoteDepartmentDTO(
                external_id=ext_id,
                name=str(self._get_field(item, 'dept_name', '')),
                parent_external_id=parent_id,
                sort_order=int(self._get_field(item, 'sort_order', 0) or 0),
            ))

        return results

    async def fetch_members(
        self, department_ids: Optional[list[str]] = None,
    ) -> list[RemoteMemberDTO]:
        url = self.auth_config.get('members_url')
        if not url:
            raise OrgSyncFetchError(msg='members_url not configured')

        async with httpx.AsyncClient(timeout=60) as client:
            data = await self._fetch_json(client, url)

        # Accept {"members": [...]} or top-level list
        items = data if isinstance(data, list) else data.get('members', [])
        if not isinstance(items, list):
            raise OrgSyncFetchError(
                msg=f'Unexpected members response format: {type(items).__name__}',
            )

        results = []
        for item in items:
            ext_id = str(self._get_field(item, 'member_id', ''))
            if not ext_id:
                logger.warning(f'Skipping member with missing ID: {item}')
                continue

            primary_dept = str(self._get_field(item, 'member_primary_dept', '') or '')
            secondary = self._get_field(item, 'member_secondary_depts', []) or []
            if isinstance(secondary, str):
                secondary = [s.strip() for s in secondary.split(',') if s.strip()]
            secondary = [str(s) for s in secondary]

            status_val = str(self._get_field(item, 'member_status', 'active') or 'active')

            results.append(RemoteMemberDTO(
                external_id=ext_id,
                name=str(self._get_field(item, 'member_name', '')),
                email=self._get_field(item, 'member_email'),
                phone=self._get_field(item, 'member_phone'),
                primary_dept_external_id=primary_dept,
                secondary_dept_external_ids=secondary,
                status=status_val,
            ))

        return results

    async def test_connection(self) -> dict:
        async with httpx.AsyncClient(timeout=30) as client:
            depts = await self.fetch_departments()
            members = await self.fetch_members()
            return {
                'connected': True,
                'org_name': 'Generic API',
                'total_depts': len(depts),
                'total_members': len(members),
            }
