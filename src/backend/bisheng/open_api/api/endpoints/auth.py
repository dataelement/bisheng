"""``GET /api/v2/auth/whoami`` — what the presented credential is (F049 design §4.2 / §6.1).

The one ``/api/v2`` endpoint that requires **no** scope: it is how F053's ``login``
verifies a pasted key, and how a human verifies a deployment with ``curl``. It
still carries ``@open_api_scope(None)`` — "no scope required" and "somebody
forgot the marker" must stay distinguishable (D3: an unmarked endpoint is 26031).
"""

from fastapi import APIRouter, Depends

from bisheng.common.schemas.api import UnifiedResponseModel, resp_200
from bisheng.open_api.api.dependencies import verify_open_api_access
from bisheng.open_api.domain.context import PRINCIPAL_KIND_SERVICE_ACCOUNT
from bisheng.open_api.domain.schemas.credential import WhoamiResponse, WhoamiServiceAccount
from bisheng.open_api.domain.scopes import open_api_scope
from bisheng.open_api.domain.services.credential_service import CredentialService
from bisheng.open_api.domain.services.credential_validator import ValidatedCredential

router = APIRouter(prefix="/auth", tags=["OpenAPI", "Auth"])


@router.get("/whoami", response_model=UnifiedResponseModel[WhoamiResponse])
@open_api_scope(None)
async def whoami(credential: ValidatedCredential = Depends(verify_open_api_access)):
    """Identity behind the presented credential: subject, tenant, scopes, key mask, expiry."""
    principal = credential.principal
    key = None
    if principal.credential_id is not None:
        # Reads the key's own row for the mask + expiry. The tenant context has
        # just been seeded from that very row, so the automatic filter matches.
        key = await CredentialService.get_row(
            principal.subject_kind,
            str(principal.subject_user_id),
            principal.credential_id,
        )

    service_account = None
    if principal.subject_kind == PRINCIPAL_KIND_SERVICE_ACCOUNT:
        service_account = WhoamiServiceAccount(id=principal.subject_user_id, name=credential.user.user_name)

    return resp_200(
        data=WhoamiResponse(
            subject_kind=principal.subject_kind,
            service_account=service_account,
            tenant_id=credential.user.tenant_id,
            scopes=list(principal.scopes),
            key_mask=key.key_mask if key else "",
            expires_at=key.expires_at if key else None,
        )
    )
