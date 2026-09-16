"""Routers of the publish pipeline — two of them, because they authenticate differently.

* :data:`v2_router` serves the CLI over ``Bearer bs-sak-…``. It carries **no**
  dependency of its own: ``bisheng/api/router.py`` mounts it under
  ``router_rpc``, whose single router-level ``verify_open_api_access`` is the
  whole of ``/api/v2`` authentication (F053 design K14); each endpoint says
  what it needs through its ``@open_api_scope("app:manage")`` marker.
* :data:`v1_router` serves the platform SPA over the session cookie.

They are exported separately rather than merged because ``bisheng/api/router.py``
mounts ``/api/v1`` and ``/api/v2`` as two aggregators, and because merging them
would put a session-authenticated endpoint one typo away from being reachable
with a service-account key — or, the other way round, a marker-less v2
endpoint that the pipeline refuses outright.
"""

from fastapi import APIRouter

from bisheng.app_publish.api.endpoints.deploy import router as deploy_router
from bisheng.app_publish.api.endpoints.publish_status import router as publish_status_router
from bisheng.app_publish.api.endpoints.snapshot import router as snapshot_router
from bisheng.app_publish.api.endpoints.version_diff import router as version_diff_router

#: Mounted under ``/api/v2`` → ``/api/v2/apps/**``.
v2_router = APIRouter()
v2_router.include_router(deploy_router)

#: Mounted under ``/api/v1`` → ``/api/v1/apps/**``.
v1_router = APIRouter()
v1_router.include_router(publish_status_router)
v1_router.include_router(snapshot_router)
v1_router.include_router(version_diff_router)
