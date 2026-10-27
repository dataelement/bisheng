from fastapi import APIRouter

from bisheng.open_api.api.endpoints.auth import router as auth_router
from bisheng.open_api.api.endpoints.model_gateway import router as model_gateway_router
from bisheng.open_api.api.endpoints.personal_token_admin import router as personal_token_admin_router
from bisheng.open_api.api.endpoints.personal_token_self import router as personal_token_self_router
from bisheng.open_api.api.endpoints.service_account import router as service_account_crud_router
from bisheng.open_api.api.endpoints.service_account_keys import router as service_account_keys_router
from bisheng.open_api.api.endpoints.service_account_keys import scopes_router
from bisheng.open_api.api.endpoints.skill_pack import router as skill_pack_router

management_router = APIRouter()
management_router.include_router(skill_pack_router)
management_router.include_router(personal_token_self_router)
management_router.include_router(personal_token_admin_router)
management_router.include_router(scopes_router)
management_router.include_router(service_account_keys_router)
management_router.include_router(service_account_crud_router)

rpc_router = APIRouter()
rpc_router.include_router(auth_router)

# F051 is exported separately and deliberately NOT folded into ``rpc_router``:
# it is the one v2 sub-router mounted conditionally, because AC-28 asks that the
# face look non-existent where the open capability layer is not deployed. Adding
# it here would mount it unconditionally and defeat that.
__all__ = ["management_router", "model_gateway_router", "rpc_router"]
