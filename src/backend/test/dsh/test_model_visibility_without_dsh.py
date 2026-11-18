"""Model visibility and the workbench model list when DSH is not deployed.

Without DSH every online chat model is offered by default, an administrator may
narrow a model to departments / roles / users, and no credits apply.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlmodel import Session

from bisheng.api.v1.schemas import WSModel
from bisheng.dsh.domain.repositories.unified_policy import UnifiedPolicyRepository
from bisheng.dsh.domain.schemas.unified_policy import ModelVisibilityInput, PolicySubject
from test.dsh.test_subject_policy import subject_store as subject_store
from test.dsh.test_unified_policy_repository import store as store


def _dsh(monkeypatch, enabled: bool):
    from bisheng.common.services import config_service

    monkeypatch.setattr(config_service, "settings", SimpleNamespace(dsh=SimpleNamespace(enabled=enabled)))


# ---- repository ---------------------------------------------------------------------------


def test_model_without_a_row_is_visible_and_stored_rows_still_apply(store):
    with Session(store) as session, session.begin():
        repo = UnifiedPolicyRepository(session)
        repo.save_visibility(7, 20, ModelVisibilityInput(version=0, subjects=[PolicySubject(kind="DEPARTMENT", id=11)]))
        repo.save_visibility(8, 20, ModelVisibilityInput(version=0, everyone=True))
        repo.save_visibility(9, 20, ModelVisibilityInput(version=0, subjects=[PolicySubject(kind="USER", id=21)]))
        # 5 has no row: visible to everyone.
        assert repo.visible_model_ids(20, [5, 7, 8, 9]) == {5, 7, 8}
        assert repo.visible_model_ids(21, [5, 7, 8, 9]) == {5, 8, 9}
        assert repo.visible_model_ids(21, []) == set()


def test_visibility_payload_default_depends_on_mode(store):
    with Session(store) as session:
        repo = UnifiedPolicyRepository(session)
        assert repo.visibility(5)["everyone"] is False
        assert repo.visibility(5, default_everyone=True)["everyone"] is True
        assert repo.visibility(5, default_everyone=True)["version"] == 0


# ---- catalog --------------------------------------------------------------------------------


def _candidates():
    server = SimpleNamespace(id=7, name="dataelem", type="openai")
    return [
        (SimpleNamespace(id=1, model_name="deepseek-v4", name="ds"), server),
        (SimpleNamespace(id=2, model_name="qwen-max", name="qw"), server),
        (SimpleNamespace(id=3, model_name="hidden", name="h"), server),
    ]


@pytest.fixture
def catalog(monkeypatch):
    from bisheng.dsh.domain.services import model_catalog
    from bisheng.llm.domain.services.llm import LLMService

    _dsh(monkeypatch, False)
    monkeypatch.setattr(LLMService, "aget_online_chat_models", AsyncMock(return_value=_candidates()))
    monkeypatch.setattr(model_catalog, "read_visible_model_ids", AsyncMock(return_value={1, 2}))
    return model_catalog


async def test_every_visible_online_model_is_offered_without_metadata(catalog):
    from bisheng.llm.domain.schemas import WorkbenchModelConfig

    # Only model 2 has metadata; model 1 needs none to be offered.
    config = WorkbenchModelConfig(models=[WSModel(id="2", displayName="Qwen", visual=True)])
    models = await catalog.user_workbench_models(20, config)
    assert [(m.id, m.displayName, m.visual, m.provider_name) for m in models] == [
        ("1", "deepseek-v4", False, "dataelem"),
        ("2", "Qwen", True, "dataelem"),
    ]
    catalog.read_visible_model_ids.assert_awaited_once_with(20, [1, 2, 3])


async def test_projection_moves_an_invisible_default_to_the_first_visible_model(catalog):
    from bisheng.llm.domain.schemas import WorkbenchModelConfig

    config = WorkbenchModelConfig(chat_default_model_id="3", linsight_default_model_id="2")
    projected = await catalog.project_workbench_config(config, 20)
    assert [m.id for m in projected.models] == ["1", "2"]
    assert projected.chat_default_model_id == "1"
    assert projected.linsight_default_model_id == "2"
    assert not config.models  # the stored config is not mutated


async def test_dsh_mode_keeps_the_credit_governed_catalog(monkeypatch):
    from bisheng.dsh.domain.services import model_catalog

    _dsh(monkeypatch, True)
    governed = AsyncMock(return_value=["dsh"])
    visible = AsyncMock(return_value=["platform"])
    monkeypatch.setattr(model_catalog, "authorized_workbench_models", governed)
    monkeypatch.setattr(model_catalog, "visible_workbench_models", visible)
    assert await model_catalog.user_workbench_models(20, "cfg") == ["dsh"]
    visible.assert_not_awaited()


async def test_online_chat_models_skip_offline_and_non_chat_rows(monkeypatch):
    from bisheng.llm.domain.services import llm as llm_module
    from bisheng.llm.domain.services.llm import LLMService

    server = SimpleNamespace(id=7)
    rows = [
        SimpleNamespace(id=3, server_id=7, online=True, model_type="llm"),
        SimpleNamespace(id=1, server_id=7, online=True, model_type="llm"),
        SimpleNamespace(id=2, server_id=7, online=False, model_type="llm"),
        SimpleNamespace(id=4, server_id=7, online=True, model_type="embedding"),
    ]
    monkeypatch.setattr(llm_module, "get_current_tenant_id", lambda: 5)
    monkeypatch.setattr(LLMService, "acollect_visible_servers", AsyncMock(return_value=[server]))
    monkeypatch.setattr(llm_module.LLMDao, "aget_model_by_server_ids", AsyncMock(return_value=rows))
    result = await LLMService.aget_online_chat_models()
    assert [model.id for model, _ in result] == [1, 3]


# ---- admin endpoints ------------------------------------------------------------------------


async def test_visibility_admin_does_not_need_dsh(monkeypatch):
    from bisheng.dsh import admin_runtime
    from bisheng.dsh.api.endpoints import unified_policy

    _dsh(monkeypatch, False)
    authorize = AsyncMock(return_value=({"tenant_id": "1"}, 1))
    monkeypatch.setattr(admin_runtime, "authorize_admin", authorize)
    admin = await unified_policy.get_policy_admin(SimpleNamespace())
    assert await admin.authorize(20, None) == ({"tenant_id": "1"}, 1)
    authorize.assert_awaited_once_with(20, None)
    assert unified_policy._missing_row_visible_to_everyone() is True


async def test_visibility_admin_with_dsh_uses_dsh_management(monkeypatch):
    from bisheng.dsh.api.endpoints import unified_policy

    _dsh(monkeypatch, True)
    monkeypatch.setattr(unified_policy, "get_runtime", AsyncMock(return_value="runtime"))
    monkeypatch.setattr(unified_policy, "get_management", AsyncMock(return_value="management"))
    assert await unified_policy.get_policy_admin(SimpleNamespace()) == "management"
    assert unified_policy._missing_row_visible_to_everyone() is False


# ---- new models get an explicit "everyone" row whenever a tenant is in scope ---------------


def test_new_model_rows_follow_dsh_or_a_valid_tenant_scope():
    from bisheng.core.context.tenant import bypass_tenant_filter, current_tenant_id, set_current_tenant_id
    from bisheng.dsh.domain.repositories.new_model_visibility import should_record_new_model_visibility

    # DSH keeps the strict behaviour: the row is required and a missing tenant fails later.
    assert should_record_new_model_visibility(True) is True
    token = set_current_tenant_id(None)
    try:
        # Without DSH and without a tenant (initialization scripts) creation is unchanged.
        assert should_record_new_model_visibility(False) is False
    finally:
        current_tenant_id.reset(token)
    token = set_current_tenant_id(3)
    try:
        assert should_record_new_model_visibility(False) is True
        with bypass_tenant_filter():
            assert should_record_new_model_visibility(False) is False
    finally:
        current_tenant_id.reset(token)


def test_backfill_script_adds_rows_only_for_models_without_one(store):
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "scripts" / "backfill_model_visibility_everyone.py"
    spec = importlib.util.spec_from_file_location("backfill_model_visibility_everyone", path)
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)

    with Session(store) as session, session.begin():
        UnifiedPolicyRepository(session).save_visibility(
            7, 20, ModelVisibilityInput(version=0, subjects=[PolicySubject(kind="USER", id=21)])
        )

    from unittest.mock import patch

    def sessions():
        from contextlib import contextmanager

        @contextmanager
        def scope():
            with Session(store) as session:
                yield session

        return scope()

    with patch.object(script, "get_sync_db_session", sessions):
        preview = script.backfill([5, 7, 8], actor=20, apply=False)
        assert preview["missing_rows"] == [5, 8]
        script.backfill([5, 7, 8], actor=20, apply=True)
    with Session(store) as session:
        repo = UnifiedPolicyRepository(session)
        assert repo.visibility(5)["everyone"] is True and repo.visibility(8)["everyone"] is True
        # The narrowed model keeps its stored scope.
        assert repo.visibility(7)["everyone"] is False
