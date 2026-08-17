"""Routers of the publish pipeline — two of them, because they authenticate differently.

* :data:`v2_router` serves the CLI over ``Bearer bs-sak-…`` and carries its
  ``app:manage`` credential dependency on every endpoint.
* :data:`v1_router` serves the platform SPA over the session cookie.

They are exported separately rather than merged because ``bisheng/api/router.py``
mounts ``/api/v1`` and ``/api/v2`` as two aggregators, and because merging them
would put a session-authenticated endpoint one typo away from being reachable
with a service-account key.
"""

from fastapi import APIRouter

from bisheng.app_publish.api.endpoints.deploy import router as deploy_router
from bisheng.app_publish.api.endpoints.publish_status import router as publish_status_router

#: Mounted under ``/api/v2`` → ``/api/v2/apps/**``.
v2_router = APIRouter()
v2_router.include_router(deploy_router)

#: Mounted under ``/api/v1`` → ``/api/v1/apps/**``.
v1_router = APIRouter()
v1_router.include_router(publish_status_router)
