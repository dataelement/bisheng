"""Guards for convention-based SQLModel discovery used by DB bootstrap."""

import ast
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import pytest

from bisheng.core.database import model_discovery
from bisheng.core.database.model_discovery import discover_sqlmodel_module_names, import_all_sqlmodel_models

_BISHENG_ROOT = Path(__file__).resolve().parents[2] / "bisheng"


def _declares_sqlmodel_table(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return any(
        isinstance(node, ast.ClassDef)
        and any(
            keyword.arg == "table" and isinstance(keyword.value, ast.Constant) and keyword.value.value is True
            for keyword in node.keywords
        )
        for node in ast.walk(tree)
    )


def _module_name(path: Path) -> str:
    module_parts = list(path.relative_to(_BISHENG_ROOT.parent).with_suffix("").parts)
    if module_parts[-1] == "__init__":
        module_parts.pop()
    return ".".join(module_parts)


def test_discovery_covers_every_literal_sqlmodel_table_module():
    discovered_modules = {_module_name(path) for path in _BISHENG_ROOT.rglob("*.py") if _declares_sqlmodel_table(path)}
    convention_modules = set(discover_sqlmodel_module_names())

    missing_modules = discovered_modules - convention_modules

    assert not missing_modules, (
        f"SQLModel table modules outside the model-directory conventions: {sorted(missing_modules)}"
    )


def test_strict_model_loading_registers_space_channel_member():
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from sqlmodel import SQLModel; "
            "from bisheng.core.database.model_discovery import import_all_sqlmodel_models; "
            "import_all_sqlmodel_models(); "
            "assert 'space_channel_member' in SQLModel.metadata.tables",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_strict_model_loading_raises_when_a_discovered_module_cannot_import(monkeypatch):
    missing_module = "bisheng.common.models.does_not_exist"
    monkeypatch.setattr(model_discovery, "discover_sqlmodel_module_names", lambda: (missing_module,))

    with pytest.raises(RuntimeError, match=missing_module):
        import_all_sqlmodel_models()


def test_strict_model_loading_rejects_empty_discovery(monkeypatch):
    monkeypatch.setattr(model_discovery, "discover_sqlmodel_module_names", tuple)

    with pytest.raises(RuntimeError, match="No SQLModel table modules"):
        import_all_sqlmodel_models()


def test_sharing_intent_tables_are_registered_and_isolated_in_a_cold_process():
    """Exercise actual registration, autofill, and SELECT events without test-global metadata."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            dedent("""
                from sqlalchemy import create_engine
                from sqlmodel import Session, SQLModel, select
                from bisheng.core.context.tenant import bypass_tenant_filter, tenant_execution_scope
                from bisheng.core.database import tenant_filter
                from bisheng.core.database.model_discovery import discover_sqlmodel_module_names

                module = 'bisheng.llm.domain.models.model_sharing_intent'
                assert module in tenant_filter._TENANT_AWARE_MODEL_MODULES
                assert module in discover_sqlmodel_module_names()
                tenant_filter.register_tenant_filter_events()
                from bisheng.llm.domain.models.model_sharing_intent import ModelSharingIntent, ModelSharingInitialization
                models = (ModelSharingIntent, ModelSharingInitialization)
                assert {model.__tablename__ for model in models} <= tenant_filter._tenant_aware_tables
                engine = create_engine('sqlite://')
                SQLModel.metadata.create_all(engine, tables=[model.__table__ for model in models])
                for tenant in (1, 101):
                    with tenant_execution_scope(tenant), Session(engine) as session:
                        intent = ModelSharingIntent(server_id=tenant, enabled=True, plan_id=f'plan-{tenant}')
                        receipt = ModelSharingInitialization(plan_id=f'plan-{tenant}', server_id=tenant)
                        assert intent.tenant_id is None and receipt.tenant_id is None
                        session.add_all([intent, receipt])
                        session.commit()
                        assert intent.tenant_id == tenant and receipt.tenant_id == tenant
                for tenant in (1, 101):
                    with tenant_execution_scope(tenant), Session(engine) as session:
                        for model in models:
                            rows = session.exec(select(model)).all()
                            assert len(rows) == 1 and rows[0].tenant_id == tenant
                with bypass_tenant_filter(), Session(engine) as session:
                    for model in models:
                        assert len(session.exec(select(model)).all()) == 2
                engine.dispose()
            """),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
