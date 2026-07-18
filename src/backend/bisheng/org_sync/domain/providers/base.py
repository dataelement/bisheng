"""OrgSyncProvider abstract base class and factory."""

import importlib
from abc import ABC, abstractmethod
from typing import Optional

from bisheng.org_sync.domain.schemas.remote_dto import RemoteDepartmentDTO, RemoteMemberDTO


class OrgSyncProvider(ABC):
    """Abstract base for third-party org data providers.

    Subclasses implement four methods to integrate a specific platform
    (Feishu, WeCom, DingTalk, or a generic REST API).
    """

    def __init__(self, auth_config: dict):
        self.auth_config = auth_config

    @abstractmethod
    async def authenticate(self) -> bool:
        """Validate credentials and obtain access token if needed.

        Returns True on success; raises OrgSyncAuthFailedError on failure.
        """
        ...

    @abstractmethod
    async def fetch_departments(
        self, root_dept_ids: Optional[list[str]] = None,
    ) -> list[RemoteDepartmentDTO]:
        """Fetch department tree from the provider.

        Args:
            root_dept_ids: Optional scope filter. None = fetch all.
        """
        ...

    @abstractmethod
    async def fetch_members(
        self, department_ids: Optional[list[str]] = None,
    ) -> list[RemoteMemberDTO]:
        """Fetch members from the provider.

        Args:
            department_ids: Departments to fetch members from. None = all.
        """
        ...

    @abstractmethod
    async def test_connection(self) -> dict:
        """Test connectivity and return summary info.

        Returns dict with keys: connected (bool), org_name (str),
        total_depts (int), total_members (int).
        """
        ...


# Provider registry: lazy imports to avoid loading unused providers
_PROVIDER_REGISTRY = {
    'feishu': 'bisheng.org_sync.domain.providers.feishu.FeishuProvider',
    'wecom': 'bisheng.org_sync.domain.providers.wecom.WeComProvider',
    'dingtalk': 'bisheng.org_sync.domain.providers.dingtalk.DingTalkProvider',
    'generic_api': 'bisheng.org_sync.domain.providers.generic_api.GenericAPIProvider',
}


def get_provider(provider: str, auth_config: dict) -> OrgSyncProvider:
    """Factory: instantiate the correct provider by name.

    Raises OrgSyncProviderError for unknown/unimplemented providers.
    """
    from bisheng.common.errcode.org_sync import OrgSyncProviderError

    dotted_path = _PROVIDER_REGISTRY.get(provider)
    if not dotted_path:
        raise OrgSyncProviderError(msg=f'Unknown provider: {provider}')

    module_path, class_name = dotted_path.rsplit('.', 1)
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)
    return cls(auth_config)
