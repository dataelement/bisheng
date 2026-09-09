"""DSH test data; no production configuration or application startup imports."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

CONTRACT_DIRECTORY = (
    Path(__file__).resolve().parents[4] / "features/v3.0.0-beta2/062-dsh-desktop-model-access/contracts"
)


@dataclass
class DshTestClock:
    """Explicit UTC clock advanced by tests, never by wall-clock sleeps."""

    current: datetime = datetime(2026, 9, 9, 2, tzinfo=UTC)

    def now(self) -> datetime:
        return self.current

    def advance(self, seconds: int) -> None:
        self.current += timedelta(seconds=seconds)


def identity_scenarios() -> dict:
    return {
        "root_tenant": 1,
        "tenant_one": 2,
        "tenant_two": 3,
        "users": (
            {"id": 1001, "tenant_id": 2, "active": True, "role": "user"},
            {"id": 1002, "tenant_id": 2, "active": False, "role": "user"},
            {"id": 1003, "tenant_id": 3, "active": True, "role": "user"},
            {"id": 1004, "tenant_id": 2, "active": True, "role": "tenant_admin"},
            {"id": 1005, "tenant_id": 2, "active": False, "deleted": True},
            {"id": 1006, "tenant_id": 2, "active": True, "service_account": True},
        ),
        "models": (
            {"id": 41, "tenant_id": 2, "online": True, "shared_with": []},
            {"id": 42, "tenant_id": 1, "online": True, "shared_with": [2]},
            {"id": 43, "tenant_id": 3, "online": True, "shared_with": []},
            {"id": 44, "tenant_id": 2, "online": False, "shared_with": []},
        ),
    }
