"""The 视觉 checkbox has to reach the Linsight guards.

``WSModel.visual`` is set per model in 系统模型设置 → 工作台模型 and was, until now,
read only by daily chat (``chat_service._process_agent_files``). Linsight picks its
model from that SAME list, so the flag is resolvable there too — these tests pin the
mapping, because a silent False turns image reads off platform-wide and a silent
True hands a text-only endpoint a payload it answers with a 400.

``asyncio_mode = auto`` — async tests need no decorator.
"""

from unittest.mock import AsyncMock, patch

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
    """Run ``_resolve_model`` with only the two external services faked out."""
    with (
        patch.object(agent_factory.LLMService, "get_workbench_llm", AsyncMock(return_value=conf)),
        patch.object(agent_factory.LLMService, "get_bisheng_linsight_llm", AsyncMock(return_value="LLM")),
        # settings is a pydantic model -> patch the CLASS method, not the instance
        # attribute (pydantic rejects the assignment).
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


async def test_unknown_model_id_fails_closed():
    """A model id absent from the list (config drift) must read as "no vision",
    matching the field's own default — never as "assume it can see"."""
    _, supports_vision = await resolve(workbench([("7", True)]), "99")
    assert supports_vision is False


async def test_empty_model_list_fails_closed():
    _, supports_vision = await resolve(WorkbenchModelConfig(models=None, linsight_default_model_id="7"), "7")
    assert supports_vision is False


async def test_id_comparison_survives_int_vs_str():
    """``WSModel.id`` is a str while callers pass the per-task model id straight
    through; an int on either side must still match its row."""
    _, supports_vision = await resolve(workbench([("7", True)]), 7)
    assert supports_vision is True
