"""The 视觉 checkbox has to reach the Linsight guards.

``WSModel.visual`` is set per model in 系统模型设置 → 工作台模型 and was once read
only by the legacy daily chat. Linsight picks its
model from that SAME list, so the flag is resolvable there too — these tests pin the
mapping, because a silent False turns image reads off platform-wide and a silent
True hands a text-only endpoint a payload it answers with a 400.

``asyncio_mode = auto`` — async tests need no decorator.
"""

from unittest.mock import AsyncMock, patch

import pytest

from bisheng.api.v1.schemas import WSModel
from bisheng.linsight.domain.services import agent_factory
from bisheng.llm.domain.schemas import WorkbenchModelConfig


def session(tenant_id=1, user_id=1):
    return type("S", (), {"id": "svid", "tenant_id": tenant_id, "user_id": user_id})()


def workbench(models, default_id=None):
    return WorkbenchModelConfig(
        models=[WSModel(id=str(mid), visual=visual) for mid, visual in models],
        linsight_default_model_id=default_id,
    )


async def resolve(conf, model_id):
    """Use the projected user catalog and the authoritative vision reader."""
    from types import SimpleNamespace

    from bisheng.dsh.domain.services import model_catalog, vision

    flags = {int(entry.id): entry.visual for entry in conf.models or []}
    with (
        patch.object(agent_factory.LLMService, "get_workbench_llm_candidates", AsyncMock(return_value=conf)),
        patch.object(model_catalog, "project_workbench_config", AsyncMock(return_value=conf)),
        patch.object(
            vision,
            "read_vision",
            AsyncMock(side_effect=lambda model_id: SimpleNamespace(vision=flags.get(model_id, False))),
        ),
        patch.object(agent_factory.LLMService, "get_bisheng_linsight_llm", AsyncMock(return_value="LLM")),
        patch.object(
            type(agent_factory.settings), "get_linsight_conf", return_value=type("C", (), {"default_temperature": 0})()
        ),
    ):
        return await agent_factory._resolve_model(session(), model_id)


async def test_ticked_model_reports_vision():
    model, supports_vision = await resolve(workbench([("7", True), ("8", False)]), "7")
    assert model == "LLM"
    assert supports_vision is True


async def test_unticked_model_reports_no_vision():
    _, supports_vision = await resolve(workbench([("7", True), ("8", False)]), "8")
    assert supports_vision is False


async def test_default_model_is_looked_up_too():
    """Per-task model omitted -> the tenant default id, whose OWN flag decides."""
    conf = workbench([("7", True), ("8", False)], default_id="7")
    _, supports_vision = await resolve(conf, None)
    assert supports_vision is True


async def test_unknown_selected_model_is_refused_without_silent_replacement():
    with pytest.raises(ValueError, match="not currently available"):
        await resolve(workbench([("7", True)]), "99")


async def test_empty_user_catalog_cannot_execute_a_frozen_selection():
    with pytest.raises(ValueError, match="not currently available"):
        await resolve(WorkbenchModelConfig(models=None, linsight_default_model_id="7"), "7")


async def test_id_comparison_survives_int_vs_str():
    """``WSModel.id`` is a str while callers pass the per-task model id straight
    through; an int on either side must still match its row."""
    _, supports_vision = await resolve(workbench([("7", True)]), 7)
    assert supports_vision is True
