"""流程管理隐藏「专家问答转公开」：列表/预置不返回，管理员不可新建或改结构。无 DDL。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.approval.domain.services.approval_scenario_admin_service import (
    ApprovalScenarioAdminService,
)
from bisheng.common.errcode.approval import ApprovalFixedScenarioStructureLockedError


def _row(scenario_code: str, *, scenario_id: int = 1, name: str = "") -> SimpleNamespace:
    payload = {
        "id": scenario_id,
        "tenant_id": 1,
        "scenario_code": scenario_code,
        "scenario_name": name or scenario_code,
        "enabled": True,
    }
    return SimpleNamespace(
        id=scenario_id,
        tenant_id=1,
        scenario_code=scenario_code,
        scenario_name=payload["scenario_name"],
        enabled=True,
        model_dump=lambda: payload.copy(),
    )


@pytest.mark.asyncio
async def test_admin_presets_hide_qa_question_publish() -> None:
    """预置列表不含转公开；registry 里仍有该码，运行时可用。"""
    presets = await ApprovalScenarioAdminService.list_presets()
    codes = {item["scenario_code"] for item in presets}
    assert "qa_question_publish" not in codes
    assert "menu_access_request" in codes


@pytest.mark.asyncio
async def test_admin_scenario_list_hides_qa_question_publish_but_keeps_row() -> None:
    """库内仍有 qa_question_publish 行时，流程管理列表不返回。"""
    visible = _row("menu_access_request", scenario_id=1, name="菜单权限申请")
    hidden = _row("qa_question_publish", scenario_id=88, name="专家问答转公开")
    with patch(
        "bisheng.approval.domain.services.approval_scenario_admin_service.ApprovalScenarioRepository.list_scenarios",
        new=AsyncMock(return_value=[visible, hidden]),
    ):
        listed = await ApprovalScenarioAdminService.list_scenarios(tenant_id=1)

    codes = [item["scenario_code"] for item in listed]
    assert codes == ["menu_access_request"]
    assert hidden.scenario_code == "qa_question_publish"
    assert hidden.enabled is True


@pytest.mark.asyncio
async def test_admin_cannot_create_or_mutate_qa_question_publish() -> None:
    """管理员不能通过流程管理新建、改启停或删转公开场景。"""
    hidden = _row("qa_question_publish", scenario_id=88, name="专家问答转公开")
    with pytest.raises(ApprovalFixedScenarioStructureLockedError):
        await ApprovalScenarioAdminService.create_scenario(
            tenant_id=1,
            payload={
                "scenario_code": "qa_question_publish",
                "scenario_name": "专家问答转公开",
                "enabled": True,
            },
        )

    with patch(
        "bisheng.approval.domain.services.approval_scenario_admin_service.ApprovalScenarioRepository.get_scenario",
        new=AsyncMock(return_value=hidden),
    ):
        with pytest.raises(ApprovalFixedScenarioStructureLockedError):
            await ApprovalScenarioAdminService.update_scenario(
                tenant_id=1,
                scenario_id=88,
                payload={"enabled": False},
            )
        with pytest.raises(ApprovalFixedScenarioStructureLockedError):
            await ApprovalScenarioAdminService.delete_scenario(
                tenant_id=1,
                scenario_id=88,
            )
