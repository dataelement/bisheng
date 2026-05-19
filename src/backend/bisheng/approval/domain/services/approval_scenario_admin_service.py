from __future__ import annotations

from bisheng.approval.domain.services.approval_registry import ApprovalRegistry


class ApprovalScenarioAdminService:
    @classmethod
    async def list_presets(cls):
        return [item.model_dump() for item in ApprovalRegistry.with_default_presets().list_presets()]

    @classmethod
    async def list_scenarios(cls, *, tenant_id: int):
        raise NotImplementedError

    @classmethod
    async def create_scenario(cls, *, tenant_id: int, payload: dict):
        raise NotImplementedError

    @classmethod
    async def list_routes(cls, *, tenant_id: int, scenario_id: int):
        raise NotImplementedError

    @classmethod
    async def list_open_exceptions(cls, *, tenant_id: int):
        raise NotImplementedError
