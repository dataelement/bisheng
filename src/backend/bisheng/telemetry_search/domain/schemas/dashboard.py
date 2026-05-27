from typing import List

from bisheng.telemetry_search.domain.models.dashboard import DashboardBase, DashboardComponent


class DashboardRead(DashboardBase):
    id: int
    write: bool = False
    is_default: bool = False
    components: List[DashboardComponent] = []
    user_name: str = None


class DashboardCreate(DashboardBase):
    title: str = "Unnamed Dashboard"
