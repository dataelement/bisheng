"""Router aggregation of the ``open_api`` module (F049 design §4.3).

Two faces, two prefixes, two auth models:

* ``service_account_router`` → mounted under ``/api/v1`` by
  ``bisheng/api/router.py``. Session-authenticated management surface; every
  endpoint carries ``Depends(get_service_account_admin)``. Its path is also
  listed in ``MANAGEMENT_API_PREFIXES`` so a super admin's ScopeBar (F019)
  actually switches the tenant a service account is created in (pit 23).
* ``open_api_v2_router`` → mounted under ``/api/v2``. Carries the credential
  dependency **at router level** (design D2/D3). In this wave only ``/auth``
  lives here; T040 moves the dependency up onto ``router_rpc`` itself so it also
  covers the 38 existing v2 endpoints — doing that before those endpoints carry
  their ``@open_api_scope`` markers would answer every one of them with 26031.

**Include order inside ``service_account_router`` is load-bearing**: FastAPI
matches routes in registration order, so ``GET /scopes`` must be registered
before ``GET /{service_account_id}`` — otherwise "scopes" is parsed as an int
path parameter and the request dies as a 422.
"""

from fastapi import APIRouter, Depends

from bisheng.open_api.api.dependencies import verify_open_api_access
from bisheng.open_api.api.endpoints.auth import router as auth_router
from bisheng.open_api.api.endpoints.service_account import router as service_account_crud_router
from bisheng.open_api.api.endpoints.service_account_keys import router as service_account_keys_router
from bisheng.open_api.api.endpoints.service_account_keys import scopes_router

# --- management face (/api/v1/service-accounts/**) --------------------------
# Each sub-router carries the ``/service-accounts`` prefix itself, so this
# aggregate has none; ``bisheng/api/router.py`` mounts it under ``/api/v1``.
service_account_router = APIRouter()
# Registration order is the match order: the static ``/scopes`` path goes in
# before ``/{service_account_id}``, or "scopes" is parsed as an int and 422s.
service_account_router.include_router(scopes_router)
service_account_router.include_router(service_account_keys_router)
service_account_router.include_router(service_account_crud_router)

# --- open face (/api/v2/**) -------------------------------------------------

open_api_v2_router = APIRouter(dependencies=[Depends(verify_open_api_access)])
open_api_v2_router.include_router(auth_router)

__all__ = ["open_api_v2_router", "service_account_router"]
