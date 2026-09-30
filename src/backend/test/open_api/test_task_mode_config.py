"""F073 configuration query (spec AC-04, AC-05, AC-06, AC-07)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.common.errcode import open_api as errors
from bisheng.common.errcode.permission import PermissionServiceUnavailableError
from bisheng.common.schemas.api import PageInfiniteCursorData
from bisheng.open_api.domain.schemas.task_mode import OpenTaskSubmitReq
from bisheng.open_api.domain.services.task_mode_service import OpenTaskModeService
from test.open_api.task_mode_support import CONFIG, LOGIN_USER, delegated_principal, sa_principal


@pytest.fixture
def workbench(monkeypatch):
    monkeypatch.setattr(
        "bisheng.llm.domain.services.LLMService.get_workbench_llm",
        AsyncMock(return_value=SimpleNamespace(linsight_default_model_id="7")),
    )


async def test_task_config_lists_models_default_tools_and_skills(task_mode_seams, workbench):
    config = await OpenTaskModeService.task_config(sa_principal(), LOGIN_USER)

    assert config["models"] == CONFIG["models"]
    assert config["default_model_id"] == "7"
    assert config["tools"] == CONFIG["tools"]
    assert config["skills"] == [{"name": "contract-review", "display_name": "contract-review", "description": None}]


async def test_default_model_outside_the_list_is_not_advertised(task_mode_seams, monkeypatch):
    monkeypatch.setattr(
        "bisheng.llm.domain.services.LLMService.get_workbench_llm",
        AsyncMock(return_value=SimpleNamespace(linsight_default_model_id="99")),
    )
    config = await OpenTaskModeService.task_config(sa_principal(), LOGIN_USER)
    assert config["default_model_id"] is None


async def test_whatever_the_config_lists_is_accepted_at_submit(task_mode_seams, workbench):
    """AC-05: query and submit share the same checks."""
    config = await OpenTaskModeService.task_config(sa_principal(), LOGIN_USER)
    tool = config["tools"][0]["children"][0]
    req = OpenTaskSubmitReq.model_validate(
        {
            "run_mode": "task",
            "execution": "async",
            "clientTimestamp": "t",
            "text": "go",
            "model": config["models"][0]["id"],
            "skills": [s["name"] for s in config["skills"]],
            "tools": [{"id": tool["id"], "tool_key": tool["tool_key"]}],
        }
    )
    await OpenTaskModeService.submit(sa_principal(), req, LOGIN_USER)
    assert task_mode_seams.submitted is not None


async def test_disabled_skill_disappears_and_is_then_rejected(task_mode_seams, workbench):
    task_mode_seams.skills = set()
    config = await OpenTaskModeService.task_config(sa_principal(), LOGIN_USER)
    assert config["skills"] == []
    req = OpenTaskSubmitReq.model_validate(
        {
            "run_mode": "task",
            "execution": "async",
            "clientTimestamp": "t",
            "text": "go",
            "model": "7",
            "skills": ["contract-review"],
        }
    )
    with pytest.raises(errors.OpenApiTaskSkillUnavailableError):
        await OpenTaskModeService.submit(sa_principal(), req, LOGIN_USER)


async def test_delegated_user_without_task_mode_cannot_query(task_mode_seams, workbench):
    task_mode_seams.menu_ok = False
    with pytest.raises(errors.OpenApiTaskModeForbiddenError):
        await OpenTaskModeService.task_config(delegated_principal(), LOGIN_USER)
    with pytest.raises(errors.OpenApiTaskModeForbiddenError):
        await OpenTaskModeService.list_knowledge(
            None, delegated_principal(), LOGIN_USER, knowledge_type="space", name=None, cursor=None, page_size=10
        )


def _space(space_id, name, ts):
    from datetime import datetime

    return SimpleNamespace(
        id=space_id, name=name, type=3, description=None, update_time=datetime(2026, 9, ts), create_time=None
    )


@pytest.fixture
def visible_spaces(monkeypatch, task_mode_seams):
    task_mode_seams.knowledge = {
        1: _space(1, "合同库", 1),
        2: _space(2, "Policy", 3),
        3: _space(3, "合同模板", 2),
        4: SimpleNamespace(id=4, name="a library", type=0, description=None, update_time=None, create_time=None),
    }
    visible = SimpleNamespace(object_ids=["1", "2", "3", "4"], error=None)
    runtime = SimpleNamespace(list_visible_objects=AsyncMock(return_value=visible))
    monkeypatch.setattr("bisheng.permission.application.access.get_f048_runtime", AsyncMock(return_value=runtime))
    monkeypatch.setattr(
        "bisheng.permission.application.identity.resolve_permission_actor", AsyncMock(return_value=SimpleNamespace())
    )
    return runtime


async def test_spaces_are_the_visible_ones_paged_and_searchable(visible_spaces):
    page = await OpenTaskModeService.list_knowledge(
        None, sa_principal(), LOGIN_USER, knowledge_type="space", name=None, cursor=None, page_size=2
    )
    assert [item["id"] for item in page.data] == [2, 3]  # newest first; library 4 excluded
    assert page.has_more is True
    second = await OpenTaskModeService.list_knowledge(
        None, sa_principal(), LOGIN_USER, knowledge_type="space", name=None, cursor=page.next_cursor, page_size=2
    )
    assert [item["id"] for item in second.data] == [1]
    assert second.has_more is False

    searched = await OpenTaskModeService.list_knowledge(
        None, sa_principal(), LOGIN_USER, knowledge_type="space", name="合同", cursor=None, page_size=10
    )
    assert [item["id"] for item in searched.data] == [3, 1]


async def test_space_enumeration_failure_is_not_an_empty_list(task_mode_seams, monkeypatch):
    runtime = SimpleNamespace(list_visible_objects=AsyncMock(side_effect=PermissionServiceUnavailableError()))
    monkeypatch.setattr("bisheng.permission.application.access.get_f048_runtime", AsyncMock(return_value=runtime))
    monkeypatch.setattr(
        "bisheng.permission.application.identity.resolve_permission_actor", AsyncMock(return_value=SimpleNamespace())
    )
    with pytest.raises(PermissionServiceUnavailableError):
        await OpenTaskModeService.list_knowledge(
            None, sa_principal(), LOGIN_USER, knowledge_type="space", name=None, cursor=None, page_size=10
        )


async def test_libraries_use_the_use_action(task_mode_seams, monkeypatch):
    captured = {}

    async def _get_knowledge(request, login_user, knowledge_type, **kwargs):
        captured.update(kwargs, knowledge_type=knowledge_type)
        row = SimpleNamespace(id=5, name="docs", description="d", update_time=None)
        return PageInfiniteCursorData(data=[row], page_size=10, has_more=False, next_cursor=None)

    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_service.KnowledgeService.get_knowledge", _get_knowledge
    )
    page = await OpenTaskModeService.list_knowledge(
        None, sa_principal(), LOGIN_USER, knowledge_type="library", name="d", cursor=None, page_size=500
    )
    assert captured["action"] == "use"
    assert captured["knowledge_type"].value == 0
    assert captured["page_size"] == 100  # capped
    assert page.data == [{"id": 5, "name": "docs", "description": "d", "update_time": None}]


async def test_unknown_knowledge_type_is_rejected(task_mode_seams):
    from bisheng.common.errcode.knowledge import KnowledgeTypeNotSupportedError

    with pytest.raises(KnowledgeTypeNotSupportedError):
        await OpenTaskModeService.list_knowledge(
            None, sa_principal(), LOGIN_USER, knowledge_type="personal", name=None, cursor=None, page_size=10
        )
