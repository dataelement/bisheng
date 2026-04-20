"""Feishu (Lark) Provider — full implementation.

Uses Feishu Open Platform Contact API v3:
  - Auth: POST /auth/v3/tenant_access_token/internal
  - Departments: GET /contact/v3/departments/{dept_id}/children (BFS)
  - Members: GET /contact/v3/users?department_id=X (page_token pagination)

Rate limit: asyncio.Semaphore(5) + 429 exponential backoff (1s/2s/4s).
Token cache: 2-hour TTL (Feishu token validity).
"""

import asyncio
import time
from typing import Optional

import httpx
from loguru import logger

from bisheng.common.errcode.org_sync import OrgSyncAuthFailedError, OrgSyncFetchError
from bisheng.org_sync.domain.providers.base import OrgSyncProvider
from bisheng.org_sync.domain.schemas.remote_dto import RemoteDepartmentDTO, RemoteMemberDTO

FEISHU_BASE_URL = 'https://open.feishu.cn/open-apis'
TOKEN_TTL_SECONDS = 7200  # 2 hours
MAX_RETRIES = 3
BACKOFF_BASE = 1  # seconds


class FeishuProvider(OrgSyncProvider):

    def __init__(self, auth_config: dict):
        super().__init__(auth_config)
        self._token: Optional[str] = None
        self._token_expires_at: float = 0
        self._semaphore = asyncio.Semaphore(5)

    # ------------------------------------------------------------------
    # HTTP helper with rate-limit retry
    # ------------------------------------------------------------------

    async def _request(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        **kwargs,
    ) -> dict:
        """Send an HTTP request with semaphore throttling and 429 backoff."""
        async with self._semaphore:
            for attempt in range(MAX_RETRIES + 1):
                resp = await client.request(method, url, **kwargs)
                if resp.status_code == 429:
                    if attempt < MAX_RETRIES:
                        wait = BACKOFF_BASE * (2 ** attempt)
                        logger.warning(f'Feishu 429 rate-limited, retrying in {wait}s')
                        await asyncio.sleep(wait)
                        continue
                    raise OrgSyncFetchError(msg='Feishu API rate limit exceeded after retries')
                resp.raise_for_status()
                data = resp.json()
                if data.get('code', 0) != 0:
                    raise OrgSyncFetchError(
                        msg=f"Feishu API error: {data.get('msg', 'unknown')} (code={data.get('code')})",
                    )
                return data
        # Should not reach here
        raise OrgSyncFetchError(msg='Feishu request failed')

    # ------------------------------------------------------------------
    # Token management
    # ------------------------------------------------------------------

    async def _ensure_token(self, client: httpx.AsyncClient) -> str:
        """Return a valid tenant_access_token, refreshing if expired."""
        if self._token and time.time() < self._token_expires_at:
            return self._token

        app_id = self.auth_config.get('app_id', '')
        app_secret = self.auth_config.get('app_secret', '')
        if not app_id or not app_secret:
            raise OrgSyncAuthFailedError(msg='Missing app_id or app_secret in auth_config')

        resp = await client.post(
            f'{FEISHU_BASE_URL}/auth/v3/tenant_access_token/internal',
            json={'app_id': app_id, 'app_secret': app_secret},
        )
        resp.raise_for_status()
        body = resp.json()
        if body.get('code', -1) != 0:
            raise OrgSyncAuthFailedError(
                msg=f"Feishu auth failed: {body.get('msg', 'unknown')}",
            )

        self._token = body['tenant_access_token']
        expire = body.get('expire', TOKEN_TTL_SECONDS)
        self._token_expires_at = time.time() + expire - 60  # refresh 1 min early
        return self._token

    def _auth_headers(self, token: str) -> dict:
        return {'Authorization': f'Bearer {token}'}

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def authenticate(self) -> bool:
        async with httpx.AsyncClient(timeout=30) as client:
            await self._ensure_token(client)
            return True

    async def fetch_departments(
        self, root_dept_ids: Optional[list[str]] = None,
    ) -> list[RemoteDepartmentDTO]:
        """BFS traversal of the Feishu department tree."""
        results: list[RemoteDepartmentDTO] = []
        async with httpx.AsyncClient(timeout=30) as client:
            token = await self._ensure_token(client)
            headers = self._auth_headers(token)

            # Starting points: provided root IDs or Feishu root "0"
            queue = list(root_dept_ids) if root_dept_ids else ['0']
            visited: set[str] = set()

            while queue:
                parent_id = queue.pop(0)
                if parent_id in visited:
                    continue
                visited.add(parent_id)

                page_token: Optional[str] = None
                while True:
                    params = {
                        'department_id_type': 'open_department_id',
                        'parent_department_id': parent_id,
                        'page_size': 50,
                    }
                    if page_token:
                        params['page_token'] = page_token

                    data = await self._request(
                        client, 'GET',
                        f'{FEISHU_BASE_URL}/contact/v3/departments/{parent_id}/children',
                        headers=headers,
                        params=params,
                    )
                    items = data.get('data', {}).get('items', [])
                    for item in items:
                        dept_id = item.get('open_department_id', '')
                        results.append(RemoteDepartmentDTO(
                            external_id=dept_id,
                            name=item.get('name', ''),
                            parent_external_id=parent_id if parent_id != '0' else None,
                            sort_order=int(item.get('order', '0') or '0'),
                        ))
                        queue.append(dept_id)

                    has_more = data.get('data', {}).get('has_more', False)
                    page_token = data.get('data', {}).get('page_token')
                    if not has_more or not page_token:
                        break

        return results

    async def fetch_members(
        self, department_ids: Optional[list[str]] = None,
    ) -> list[RemoteMemberDTO]:
        """Fetch members from specified departments (or all)."""
        results: list[RemoteMemberDTO] = []
        seen_user_ids: set[str] = set()

        async with httpx.AsyncClient(timeout=30) as client:
            token = await self._ensure_token(client)
            headers = self._auth_headers(token)

            if not department_ids:
                department_ids = ['0']

            for dept_id in department_ids:
                page_token: Optional[str] = None
                while True:
                    params = {
                        'department_id_type': 'open_department_id',
                        'department_id': dept_id,
                        'page_size': 50,
                    }
                    if page_token:
                        params['page_token'] = page_token

                    data = await self._request(
                        client, 'GET',
                        f'{FEISHU_BASE_URL}/contact/v3/users',
                        headers=headers,
                        params=params,
                    )
                    items = data.get('data', {}).get('items', [])
                    for item in items:
                        user_id = item.get('open_id', '') or item.get('user_id', '')
                        if user_id in seen_user_ids:
                            continue
                        seen_user_ids.add(user_id)

                        dept_ids_list = item.get('department_ids', [])
                        primary_dept = dept_ids_list[0] if dept_ids_list else dept_id
                        secondary_depts = [d for d in dept_ids_list[1:] if d != primary_dept]

                        status = 'active'
                        if item.get('status', {}).get('is_frozen', False):
                            status = 'disabled'
                        if item.get('status', {}).get('is_resigned', False):
                            status = 'disabled'

                        results.append(RemoteMemberDTO(
                            external_id=user_id,
                            name=item.get('name', ''),
                            email=item.get('email'),
                            phone=item.get('mobile'),
                            primary_dept_external_id=primary_dept,
                            secondary_dept_external_ids=secondary_depts,
                            status=status,
                        ))

                    has_more = data.get('data', {}).get('has_more', False)
                    page_token = data.get('data', {}).get('page_token')
                    if not has_more or not page_token:
                        break

        return results

    async def test_connection(self) -> dict:
        """Test connectivity: authenticate + fetch root department info."""
        async with httpx.AsyncClient(timeout=30) as client:
            token = await self._ensure_token(client)
            headers = self._auth_headers(token)

            data = await self._request(
                client, 'GET',
                f'{FEISHU_BASE_URL}/contact/v3/departments/0',
                headers=headers,
                params={'department_id_type': 'open_department_id'},
            )
            dept_info = data.get('data', {}).get('department', {})

            # Get a count of child departments for summary
            children_data = await self._request(
                client, 'GET',
                f'{FEISHU_BASE_URL}/contact/v3/departments/0/children',
                headers=headers,
                params={
                    'department_id_type': 'open_department_id',
                    'parent_department_id': '0',
                    'page_size': 1,
                },
            )

            return {
                'connected': True,
                'org_name': dept_info.get('name', 'Unknown'),
                'total_depts': children_data.get('data', {}).get('total', 0),
                'total_members': dept_info.get('member_count', 0),
            }
