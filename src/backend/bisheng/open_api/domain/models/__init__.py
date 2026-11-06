"""Open API persistence models.

``core/database/tenant_filter.py`` registers this **package** (not each module)
as tenant-aware, and model discovery only imports the package ``__init__`` — so
a table whose module is not imported here is invisible twice over: ``create_all``
never creates it, and the tenant filter never covers it. Both failures are
silent until the first write. Add new model modules to the imports below.
"""

from bisheng.open_api.domain.models.api_credential import ApiCredential
from bisheng.open_api.domain.models.credential_delegate_scope import ApiCredentialDelegateScope
from bisheng.open_api.domain.models.model_call_record import ModelCallRecord
from bisheng.open_api.domain.models.open_api_tenant_setting import OpenApiTenantSetting
from bisheng.open_api.domain.models.service_account import ServiceAccount

__all__ = [
    "ApiCredential",
    "ApiCredentialDelegateScope",
    "ModelCallRecord",
    "OpenApiTenantSetting",
    "ServiceAccount",
]
