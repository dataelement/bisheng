"""ORM models of the app_publish module.

``app_deployment`` physically carries ``tenant_id`` and is registered in
``core/database/tenant_filter._TENANT_AWARE_MODEL_MODULES`` so the automatic
tenant SELECT filter covers it (design K6).

``app_preview_session`` carries ``tenant_id`` too — an approval-time preview
belongs to the application's tenant, and the timeout sweep reads it back under
``bypass_tenant_filter`` on a Celery tick that has no tenant context.

``hosted_app_subject`` has **no** ``tenant_id``: it is a pure identity mapping
whose isolation is derived from the ``app`` row (see its module docstring).
Listing it here only puts the table into ``SQLModel.metadata``.

``resource_tier`` is **not** here on purpose — it is owned by F055 but read by
F054, so its model sits in ``bisheng/database/models/resource_tier.py`` to keep
``app_runtime`` from importing ``app_publish`` (design D11 / D16).
"""

from bisheng.app_publish.domain.models.app_deployment import AppDeployment, AppDeploymentDao
from bisheng.app_publish.domain.models.app_preview_session import AppPreviewSession, AppPreviewSessionDao
from bisheng.app_publish.domain.models.hosted_app_subject import HostedAppSubject, HostedAppSubjectDao

__all__ = [
    "AppDeployment",
    "AppDeploymentDao",
    "AppPreviewSession",
    "AppPreviewSessionDao",
    "HostedAppSubject",
    "HostedAppSubjectDao",
]
