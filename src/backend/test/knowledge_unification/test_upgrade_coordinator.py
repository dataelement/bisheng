"""Public CLI result contract; full Owner transactions are exercised in E2E."""

import importlib

import pytest


def entry():
    return importlib.import_module("scripts.unify_knowledge_spaces")


def test_two_command_parser_discovers_environment_and_requires_positive_apply_actor():
    parser = entry().parser()
    preview = parser.parse_args(["--run-id", "upgrade-1", "--dry-run"])
    assert preview.environment is None and not preview.apply and preview.dry_run
    apply = parser.parse_args(["--run-id", "upgrade-1", "--apply", "--operator-id", "7"])
    assert apply.apply and apply.operator_id == 7 and not apply.resume
    for extra in (["--dry-run", "--apply"], ["--operator-id", "0"], ["--operator-id", "-1"]):
        with pytest.raises(SystemExit):
            parser.parse_args(["--run-id", "upgrade-1", *extra])


@pytest.mark.parametrize("stage", ["--permissions-only", "--register-references-only"])
async def test_verify_cannot_be_ignored_by_a_legacy_stage(stage):
    from contextlib import asynccontextmanager

    from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError

    @asynccontextmanager
    async def unopened(_args):
        raise AssertionError("conflicting verification must reject before opening a runtime")
        yield

    module = entry()
    args = module.parser().parse_args(
        ["--run-id", "verify-conflict", "--apply", "--operator-id", "7", "--verify", stage]
    )
    with pytest.raises(KnowledgeOperationPlanConflictError) as caught:
        await module.arun(args, runtime_factory=unopened)
    assert caught.value.kwargs["reason"] == "migration_cli_verify_conflicting_stage"


@pytest.mark.parametrize("can_apply,expected", [(True, 0), (False, 2)])
def test_dry_run_exit_code_uses_can_apply_without_falsely_claiming_coverage(monkeypatch, capsys, can_apply, expected):
    module = entry()

    async def run(args):
        return {"mode": "dry-run", "run_id": args.run_id, "ready": False, "can_apply": can_apply}

    monkeypatch.setattr(module, "arun", run)
    assert module.main(["--run-id", "upgrade-1", "--dry-run"]) == expected
    assert '"ready": false' in capsys.readouterr().out
