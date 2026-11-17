"""F016 upgrade script: dry run, apply, idempotence, never overwrite, and the opening gate."""

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlmodel import Session

from bisheng.dsh.domain.models.credit_setting import DshCreditSetting
from bisheng.dsh.domain.models.model_call import DshModelCall
from bisheng.llm.domain.models.llm_server import LLMModel, LLMServer

SCRIPT = Path(__file__).resolve().parents[2] / "scripts/backfill_model_pricing.py"
MANUAL = {"currency": "CNY", "input": "6", "cache_read": "1", "output": "30", "source": "MANUAL", "revision": 2}
# A damaged record: billing treats it as free, so the script must not count it as priced.
BROKEN = {**MANUAL, "input": "-1"}


@pytest.fixture(scope="module")
def script():
    spec = importlib.util.spec_from_file_location("backfill_model_pricing", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'backfill.db'}")
    for model in (LLMServer, LLMModel, DshModelCall, DshCreditSetting):
        model.__table__.create(engine)
    with Session(engine) as session, session.begin():
        session.add_all(
            [
                LLMServer(id=1, tenant_id=1, name="百炼", type="qwen", config={}, user_id=1),
                LLMServer(id=2, tenant_id=2, name="自部署", type="vllm", config={}, user_id=1),
                LLMModel(
                    id=10,
                    tenant_id=1,
                    server_id=1,
                    name="qwen-max",
                    model_name="qwen-max",
                    model_type="llm",
                    config={"max_tokens": 8},
                    user_id=1,
                ),
                LLMModel(
                    id=11,
                    tenant_id=1,
                    server_id=1,
                    name="kept",
                    model_name="qwen-plus",
                    model_type="llm",
                    config={"pricing": MANUAL},
                    user_id=1,
                ),
                LLMModel(
                    id=12,
                    tenant_id=1,
                    server_id=1,
                    name="emb",
                    model_name="text-embedding-v4",
                    model_type="embedding",
                    config={},
                    user_id=1,
                ),
                LLMModel(
                    id=20,
                    tenant_id=2,
                    server_id=2,
                    name="local",
                    model_name="my-qwen",
                    model_type="llm",
                    config=None,
                    user_id=1,
                ),
            ]
        )
    return engine


def test_dry_run_lists_every_llm_model_and_writes_nothing(script, engine):
    with Session(engine) as session:
        lines = {line["model_id"]: line for line in script.plan(session)}
    assert set(lines) == {10, 11, 20}  # embeddings are not billed
    assert (lines[10]["action"], lines[10]["result"]) == ("fill", "catalog qwen/qwen-max")
    assert (lines[11]["action"], lines[11]["result"]) == ("keep", "manual")
    assert (lines[20]["action"], lines[20]["result"]) == ("fill", "default 0 (free)")
    with Session(engine) as session:
        assert session.get(LLMModel, 10).config == {"max_tokens": 8}


def test_apply_fills_missing_prices_across_tenants_and_keeps_others(script, engine):
    with Session(engine) as session, session.begin():
        assert script.apply(session) == 2
    with Session(engine) as session:
        assert session.get(LLMModel, 10).config["max_tokens"] == 8
        assert session.get(LLMModel, 10).config["pricing"]["catalog_key"] == "qwen/qwen-max"
        assert session.get(LLMModel, 11).config["pricing"] == MANUAL
        assert session.get(LLMModel, 20).config["pricing"]["source"] == "DEFAULT"
        assert session.get(LLMModel, 12).config == {}


def test_apply_is_idempotent(script, engine):
    with Session(engine) as session, session.begin():
        script.apply(session)
    with Session(engine) as session, session.begin():
        assert script.apply(session) == 0


def test_gate_fails_until_prices_are_filled(script, engine):
    with Session(engine) as session:
        problems = script.check(session)
    assert [p for p in problems if p.startswith("model without price")] == [
        "model without price: tenant=1 server=百炼 model=qwen-max id=10",
        "model without price: tenant=2 server=自部署 model=my-qwen id=20",
    ]
    with Session(engine) as session, session.begin():
        script.apply(session)
    with Session(engine) as session:
        assert script.check(session) == []


@pytest.fixture
def broken(engine):
    with Session(engine) as session, session.begin():
        session.add(
            LLMModel(
                id=13,
                tenant_id=1,
                server_id=1,
                name="broken",
                model_name="qwen-flash",
                model_type="llm",
                config={"max_tokens": 4, "pricing": BROKEN},
                user_id=1,
            )
        )
    return engine


def test_an_invalid_price_is_shown_replaced_and_then_passes_the_gate(script, broken):
    with Session(broken) as session:
        line = next(line for line in script.plan(session) if line["model_id"] == 13)
        problems = script.check(session)
    assert (line["action"], line["result"]) == ("replace invalid", "catalog qwen/qwen-flash")
    assert '"input": "-1"' in line["was"]
    assert [p for p in problems if "id=13" in p] == [
        "model with invalid price: tenant=1 server=百炼 model=qwen-flash id=13 "
        "(billed as free; run --apply to replace it from the catalog, or set a price in the admin table)"
    ]
    with Session(broken) as session, session.begin():
        assert script.apply(session) == 3
    with Session(broken) as session:
        config = session.get(LLMModel, 13).config
        assert config["pricing"]["catalog_key"] == "qwen/qwen-flash" and config["max_tokens"] == 4
        assert session.get(LLMModel, 11).config["pricing"] == MANUAL  # valid prices are never touched
        assert script.check(session) == []


def test_gate_reports_missing_schema(script, engine):
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE dsh_credit_setting"))
    with Session(engine) as session, session.begin():
        script.apply(session)
    with Session(engine) as session:
        assert script.check(session) == ["missing table dsh_credit_setting"]


def test_cli_exit_codes(script, engine, monkeypatch, capsys):
    import bisheng.core.database as database

    monkeypatch.setattr(database, "get_sync_db_session", lambda: Session(engine))
    assert script.main(["--check"]) == script.GATE_FAILED
    assert script.main([]) == 0
    assert "dry run: nothing was written" in capsys.readouterr().out
    assert script.main(["--apply"]) == 0
    assert script.main(["--check"]) == 0
    with pytest.raises(SystemExit):
        script.main(["--apply", "--check"])
