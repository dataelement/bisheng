"""Aggregate router for F053's distribution face.

Mounted conditionally by ``bisheng/api/router.py``: with
``open_platform.enabled`` false the router is never included and FastAPI answers
404 on its own (AC-05, design D10).
"""

from fastapi import APIRouter

from bisheng.dev_toolkit.api.endpoints.distribution import router as distribution_router

router = APIRouter()
router.include_router(distribution_router)
