"""Exercise real SQL checkpoints with injected infrastructure, not DAO mocks."""

import ast
import hashlib
import importlib.util
import json
import sys
import types
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import create_engine
from sqlmodel import Session

from bisheng.knowledge.docflow.client import DocFlowBusy


class Lock:
    def __init__(self, active, key):
        self.active, self.key, self.mine = active, key, False

    def acquire(self):
        if self.key in self.active:
            return False
        self.active.add(self.key)
        self.mine = True
        return True

    def owned(self):
        return self.mine and self.key in self.active

    def release(self):
        self.active.remove(self.key)
        self.mine = False


class Redis:
    def __init__(self):
        self.active = set()

    def lock(self, key, **kwargs):
        return Lock(self.active, key)


def test_real_sql_state_is_tenant_scoped_and_capacity_is_account_scoped(monkeypatch):
    backend = Path(__file__).parents[3]
    # The connection-manager package bootstraps production configuration; only
    # replace that bootstrap. Use the real dialect helpers, SQLModel and Session.
    package = types.ModuleType("bisheng.core.database")
    package.__path__ = [str(backend / "bisheng/core/database")]
    monkeypatch.setitem(sys.modules, package.__name__, package)
    path = backend / "bisheng/knowledge/domain/services/docflow_state.py"
    spec = importlib.util.spec_from_file_location("tested_docflow_state", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    model = module.DocFlowJob
    engine = create_engine("sqlite://")
    model.__table__.create(engine)

    @contextmanager
    def session_factory():
        with Session(engine) as session:
            yield session

    redis = Redis()
    one = module.DocFlowState(1, session_factory=session_factory, redis=redis)
    two = module.DocFlowState(2, session_factory=session_factory, redis=redis)
    one.write("a" * 64, {"stage": "submitted", "remote": {"files": [{"id": "123"}]}})
    assert one.read("a" * 64)["stage"] == "submitted"
    assert two.read("a" * 64) == {}
    one.write("a" * 64, {"stage": "ready"})
    assert one.read("a" * 64) == {"stage": "ready"}
    with one.capacity("same-account", 1):
        with pytest.raises(DocFlowBusy):
            with two.capacity("same-account", 1):
                pytest.fail("Capacity must be shared across tenants")
    with two.capacity("same-account", 1):
        assert redis.active
    assert not redis.active


def test_provider_configuration_does_not_advertise_partial_credentials():
    source = Path(__file__).parents[3] / "bisheng/core/config/settings.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    names = {"Etl4lmConf", "MineruConf", "PaddleOcrConf", "VersionManagementConf", "DocFlowConf", "KnowledgeConf"}
    definitions = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name in names]
    import os

    namespace = {"BaseModel": BaseModel, "Field": Field, "field_validator": field_validator, "os": os}
    exec(compile(ast.Module(body=definitions, type_ignores=[]), str(source), "exec"), namespace)
    knowledge = namespace["KnowledgeConf"](loader_provider="docflow", docflow={"url": "http://mk.test"})
    assert knowledge.image_parser_enabled is False
    knowledge.docflow.app_key = "test"
    knowledge.docflow.app_secret = "test-secret"
    knowledge.docflow.docflow_app_id = "test"
    knowledge.docflow.docflow_secret_code = "test-secret"
    knowledge.docflow.workspace_id = "space"
    assert knowledge.image_parser_enabled is True
    assert "test-secret" not in repr(knowledge.docflow)


def test_preview_cache_scope_changes_with_tenant_and_parser_revision(monkeypatch):
    path = Path(__file__).parents[3] / "bisheng/knowledge/domain/services/knowledge_utils.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "KnowledgeUtils")
    cls.bases = []
    cls.body = [
        node
        for node in cls.body
        if isinstance(node, ast.FunctionDef)
        and node.name in ("preview_provider_scope", "get_preview_cache_key", "_preview_active_key_index")
    ]
    namespace = {"hashlib": hashlib, "json": json, "md5_hash": lambda value: hashlib.md5(value.encode()).hexdigest()}
    exec(compile(ast.Module(body=[cls], type_ignores=[]), str(path), "exec"), namespace)
    settings = types.ModuleType("bisheng.common.services.config_service")
    configuration = {"workspace_id": "space", "parser_revision": "1"}
    knowledge = SimpleNamespace(loader_provider="docflow", docflow=SimpleNamespace(model_dump=lambda: configuration))
    settings.settings = SimpleNamespace(get_knowledge=lambda: knowledge)
    tenant_module = types.ModuleType("bisheng.core.context.tenant")
    tenant = [1]
    tenant_module.get_current_tenant_id = lambda: tenant[0]
    monkeypatch.setitem(sys.modules, settings.__name__, settings)
    monkeypatch.setitem(sys.modules, tenant_module.__name__, tenant_module)
    utils = namespace["KnowledgeUtils"]
    first = utils.get_preview_cache_key(1, "file")
    configuration["parser_revision"] = "2"
    second = utils.get_preview_cache_key(1, "file")
    tenant[0] = 2
    third = utils.get_preview_cache_key(1, "file")
    knowledge.loader_provider = "etl4lm"
    legacy = utils.get_preview_cache_key(1, "file")
    assert len({first, second, third, legacy}) == 4
    assert legacy.startswith("preview_file_chunk:1:")
