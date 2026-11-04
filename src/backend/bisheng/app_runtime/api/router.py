"""Aggregate router for F054 (hosted application domain + runtime).

Include order matters: ``internal_app_proxy`` owns the static
``/apps/_unavailable`` path, and Starlette matches routes in declaration order —
registered after ``apps``, that path would be swallowed by ``/apps/{app_id}``
and the nginx fallback page would come back as "application not found".
"""

from fastapi import APIRouter

from bisheng.app_runtime.api.endpoints.app_storage import router as app_storage_router
from bisheng.app_runtime.api.endpoints.apps import router as apps_router
from bisheng.app_runtime.api.endpoints.host_isolation import router as host_isolation_router
from bisheng.app_runtime.api.endpoints.internal_app_proxy import router as internal_app_proxy_router
from bisheng.app_runtime.api.endpoints.runtime_delivery import router as runtime_delivery_router
from bisheng.app_runtime.api.endpoints.runtime_kubernetes import router as runtime_kubernetes_router
from bisheng.app_runtime.api.endpoints.runtime_management import router as runtime_management_router

router = APIRouter()
router.include_router(host_isolation_router)

router.include_router(runtime_delivery_router)
router.include_router(runtime_kubernetes_router)
router.include_router(runtime_management_router)
router.include_router(app_storage_router)
router.include_router(internal_app_proxy_router)
router.include_router(apps_router)
