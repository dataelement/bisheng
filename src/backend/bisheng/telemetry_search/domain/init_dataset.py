"""遥测看板默认数据集初始化（与 common.init_data 中的调用约定一致）。"""

from loguru import logger


async def init_dashboard_datasets() -> None:
    """Best-effort seed of default dashboard datasets; failures are logged only."""
    try:
        from bisheng.telemetry_search.domain.services.dashboard import DashboardService
    except Exception as exc:
        logger.warning('init_dashboard_datasets: skip (DashboardService import failed: %s)', exc)
        return
    try:
        init_fn = getattr(DashboardService, 'init_datasets', None) or getattr(
            DashboardService, 'init_default_datasets', None,
        )
        if callable(init_fn):
            await init_fn()
        else:
            logger.debug('init_dashboard_datasets: no known init hook on DashboardService, skip')
    except Exception as exc:
        logger.warning('init_dashboard_datasets: failed (ignored): %s', exc)
