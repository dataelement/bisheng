from abc import ABC

from bisheng.common.repositories.interfaces.base_repository import BaseRepository
from bisheng.telemetry_search.domain.models.dashboard_dataset import DashboardDataset


class DashboardDatasetRepository(BaseRepository[DashboardDataset, str], ABC):
    """
    Dashboard Dataset Repository Interface
    Responsible for definition DashboardDataset Entity's database operations interface
    """
    pass
