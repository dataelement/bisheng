"""ORM models of the app_publish module.

``app_deployment`` physically carries ``tenant_id`` and is registered in
``core/database/tenant_filter._TENANT_AWARE_MODEL_MODULES`` so the automatic
tenant SELECT filter covers it (design K6).

``resource_tier`` is **not** here on purpose — it is owned by F055 but read by
F054, so its model sits in ``bisheng/database/models/resource_tier.py`` to keep
``app_runtime`` from importing ``app_publish`` (design D11 / D16).
"""

from bisheng.app_publish.domain.models.app_deployment import AppDeployment, AppDeploymentDao

__all__ = ["AppDeployment", "AppDeploymentDao"]
