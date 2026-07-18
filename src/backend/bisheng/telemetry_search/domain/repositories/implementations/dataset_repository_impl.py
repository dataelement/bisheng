from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.common.repositories.implementations.base_repository_impl import BaseRepositoryImpl
from bisheng.telemetry_search.domain.models.dashboard_dataset import DashboardDataset
from bisheng.telemetry_search.domain.repositories.interfaces.dataset_repository import DashboardDatasetRepository


class DashboardDatasetRepositoryImpl(BaseRepositoryImpl[DashboardDataset, int], DashboardDatasetRepository):
    """
    Dashboard Dataset Repository Implementation
    Responsible for handling DashboardDataset Entity database operations
    """

    def __init__(self, session: AsyncSession):
        super().__init__(session, DashboardDataset)
