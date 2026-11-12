"""F015 upgrade step: give every existing LLM model a price, then gate the opening of service.

Run from src/backend/ after `alembic upgrade head`, while the service is still stopped
(features/v3.1.0-beta1/015-credit-pricing/runbook.md):

    python scripts/backfill_model_pricing.py            # dry run: list what each model would get
    python scripts/backfill_model_pricing.py --apply    # write prices for models that have none
    python scripts/backfill_model_pricing.py --check    # gate: exit 0 only when nothing is missing

Models are priced with the same rule as saving a model in the admin UI: the built-in catalog
price when the provider type and model name match, otherwise 0 (free). Existing prices are
never touched, so the script is safe to rerun.

Exit codes: 0 success / gate passed, 2 gate failed, 1 unexpected error.
"""

import argparse
import os
import sys

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from sqlalchemy import inspect  # noqa: E402
from sqlmodel import Session, select  # noqa: E402

from bisheng.core.context.tenant import bypass_tenant_filter  # noqa: E402
from bisheng.llm.domain.const import LLMModelType  # noqa: E402
from bisheng.llm.domain.models.llm_server import LLMModel, LLMServer  # noqa: E402
from bisheng.llm.domain.pricing.service import default_pricing  # noqa: E402

GATE_FAILED = 2
REQUIRED_COLUMNS = {"dsh_model_call": {"pricing", "cost_micro", "currency"}}
REQUIRED_TABLES = {"dsh_credit_setting"}


def _llm_models(session: Session) -> list[tuple[LLMModel, LLMServer]]:
    with bypass_tenant_filter():
        rows = session.exec(
            select(LLMModel, LLMServer)
            .join(LLMServer, LLMServer.id == LLMModel.server_id)
            .where(LLMModel.model_type == LLMModelType.LLM.value)
            .order_by(LLMModel.tenant_id, LLMModel.server_id, LLMModel.id)
        ).all()
    return list(rows)


def _has_price(model: LLMModel) -> bool:
    return isinstance((model.config or {}).get("pricing"), dict)


def plan(session: Session) -> list[dict]:
    """One line per LLM model: what it has, or what --apply would give it."""
    lines = []
    for model, server in _llm_models(session):
        line = {
            "tenant_id": model.tenant_id,
            "server": server.name,
            "server_type": server.type,
            "model_id": model.id,
            "model_name": model.model_name,
        }
        if _has_price(model):
            line["action"] = "keep"
            line["result"] = (model.config["pricing"].get("source") or "").lower() or "priced"
        else:
            pricing = default_pricing(server.type, model.model_name)
            line["action"] = "fill"
            line["result"] = f"catalog {pricing.catalog_key}" if pricing.source == "CATALOG" else "default 0 (free)"
        lines.append(line)
    return lines


def apply(session: Session) -> int:
    """Write prices for LLM models that have none. Returns how many models were filled."""
    filled = 0
    for model, server in _llm_models(session):
        if _has_price(model):
            continue
        config = dict(model.config or {})
        config["pricing"] = default_pricing(server.type, model.model_name).model_dump()
        model.config = config
        with bypass_tenant_filter():
            session.add(model)
        filled += 1
    session.flush()
    return filled


def check(session: Session) -> list[str]:
    """Problems that must block opening the service; empty when the upgrade is complete."""
    problems = []
    inspector = inspect(session.get_bind())
    for table in sorted(REQUIRED_TABLES):
        if not inspector.has_table(table):
            problems.append(f"missing table {table}")
    for table, columns in REQUIRED_COLUMNS.items():
        present = {column["name"] for column in inspector.get_columns(table)} if inspector.has_table(table) else set()
        problems.extend(f"missing column {table}.{name}" for name in sorted(columns - present))
    for model, server in _llm_models(session):
        if not _has_price(model):
            problems.append(
                f"model without price: tenant={model.tenant_id} server={server.name} model={model.model_name} id={model.id}"
            )
    return problems


def _print_plan(lines: list[dict]) -> None:
    for line in lines:
        print(
            "tenant={tenant_id}\tserver={server}\ttype={server_type}\tmodel={model_name}\tid={model_id}\t"
            "{action}: {result}".format(**line)
        )
    fill = [line for line in lines if line["action"] == "fill"]
    free = [line for line in fill if line["result"].startswith("default")]
    print(f"LLM models: {len(lines)}; to fill: {len(fill)} (catalog {len(fill) - len(free)}, default 0: {len(free)})")
    if free:
        print("Check the 'default 0' models: paid cloud models listed there stay free until an admin sets a price.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="F015: fill missing LLM model prices and gate the upgrade.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="write prices for models that have none")
    mode.add_argument("--check", action="store_true", help="exit 2 when any upgrade step is incomplete")
    args = parser.parse_args(argv)

    from bisheng.core.database import get_sync_db_session

    with get_sync_db_session() as session:
        if args.check:
            problems = check(session)
            for problem in problems:
                print(problem)
            print("upgrade gate: " + ("FAILED" if problems else "passed"))
            return GATE_FAILED if problems else 0
        _print_plan(plan(session))
        if args.apply:
            filled = apply(session)
            session.commit()
            print(f"filled {filled} model prices")
        else:
            print("dry run: nothing was written (use --apply)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
