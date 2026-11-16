"""F022 extends the authorization-model publication script for new resource types.

覆盖 AC: AC-04, AC-19, AC-20.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.permission.domain.services.catalog_policy import ACTION_RESOURCE_SCOPES, CatalogAction
from bisheng.permission.domain.services.model_policy import DerivedPermissionModel
from scripts import publish_authorization_model_change as cli

MARKET_TYPES = {"dsh_market_plugin", "dsh_market_workbench"}


def _action(code, types, *, level=3, active=True):
    return CatalogAction(code=code, name=code, level=level, active=active, resource_types=frozenset(types))


def _catalog_before_f022():
    """Every action scoped as the code defines it, minus the two market types."""
    return tuple(_action(code, types - MARKET_TYPES) for code, types in ACTION_RESOURCE_SCOPES.items())


def test_target_actions_add_scopes_only_for_types_new_to_the_catalog():
    before = _catalog_before_f022()
    # An administrator-visible difference on an existing type must survive.
    before = tuple(
        action if action.code != "share" else _action("share", action.resource_types - {"workflow"})
        for action in before
    )
    after = {action.code: action.resource_types for action in cli._target_actions(before)}
    assert after["manage_permission"] == ACTION_RESOURCE_SCOPES["manage_permission"]
    assert after["delete"] == ACTION_RESOURCE_SCOPES["delete"]
    assert MARKET_TYPES.isdisjoint(after["edit"])
    assert "workflow" not in after["share"]
    for action in before:
        assert action.resource_types <= after[action.code]


def test_target_actions_never_scope_retired_or_unknown_actions():
    before = (*_catalog_before_f022(), _action("use", {"tool", "linsight_skill"}, level=1, active=False))
    after = {action.code: action for action in cli._target_actions(before)}
    assert after["use"].resource_types == frozenset({"tool", "linsight_skill"})
    assert after["use"].active is False


def test_target_actions_are_unchanged_when_the_catalog_already_has_every_type():
    current = tuple(_action(code, types) for code, types in ACTION_RESOURCE_SCOPES.items())
    assert cli._target_actions(current) == current


def _model(kind, key, **fields):
    defaults = {
        "name": key,
        "config_scope": "PLATFORM",
        "derived_level": 1,
        "active": True,
        "allow_same_level": False,
        "selected_action_codes": (),
        "action_codes": (),
    }
    return DerivedPermissionModel(model_key=key, kind=kind, **{**defaults, **fields})


def test_custom_selections_keep_f118_visibility_provenance():
    models = SimpleNamespace(
        models=(
            _model("STANDARD", "viewer"),
            _model(
                "CUSTOM",
                "f118-use-viewer",
                visibility_only_resource_types=("tool", "workflow"),
                visibility_level=2,
                retired_use_level_floor=2,
                derived_level=2,
            ),
            _model("CUSTOM", "reviewer", selected_action_codes=("edit",), action_codes=("edit",), derived_level=2),
        )
    )
    selections = {selection.model_key: selection for selection in cli._custom_selections(models)}
    assert set(selections) == {"f118-use-viewer", "reviewer"}
    kept = selections["f118-use-viewer"]
    assert (kept.visibility_only_resource_types, kept.visibility_level, kept.retired_use_level_floor) == (
        ("tool", "workflow"),
        2,
        2,
    )
    assert selections["reviewer"].action_codes == ("edit",)


def _runtime_catalog(scopes, checksum="target"):
    return SimpleNamespace(
        model_checksum=checksum,
        action_resource_scopes=tuple((code, tuple(sorted(types))) for code, types in scopes.items()),
    )


def test_verification_passes_for_a_complete_upgrade():
    catalog = _runtime_catalog(ACTION_RESOURCE_SCOPES)
    assert cli._verification_problems(catalog, "target") == []


def test_verification_reports_missing_scopes_and_a_stale_model():
    scopes = {code: types - MARKET_TYPES for code, types in ACTION_RESOURCE_SCOPES.items()}
    problems = cli._verification_problems(_runtime_catalog(scopes, checksum="old"), "target")
    assert any("checksum" in problem for problem in problems)
    assert any("manage_permission:dsh_market_plugin" in problem for problem in problems)
    assert any("delete:dsh_market_workbench" in problem for problem in problems)


@pytest.mark.parametrize("extra", [[], ["--apply", "--confirm-store-id", "s", "--confirm-target-model-checksum", "c"]])
def test_verify_is_read_only_and_exclusive(extra):
    if extra:
        with pytest.raises(SystemExit):
            cli.parse_args(["--verify", *extra, "--operator-id", "1"])
    else:
        assert cli.parse_args(["--verify"]).verify is True


async def test_verify_reads_the_runtime_catalog_and_writes_nothing(monkeypatch, capsys):
    monkeypatch.setattr(cli, "initialize_app_context", AsyncMock())
    monkeypatch.setattr(cli, "close_app_context", AsyncMock())
    catalog = _runtime_catalog(
        ACTION_RESOURCE_SCOPES, checksum=cli.authorization_model_checksum(cli.get_authorization_model_f048())
    )
    monkeypatch.setattr(
        cli, "SqlPermissionControlState", lambda: SimpleNamespace(current_catalog=AsyncMock(return_value=catalog))
    )
    publish = AsyncMock()
    monkeypatch.setattr(cli, "_publish_catalog_cutover", publish)
    monkeypatch.setattr(cli, "_activate_model_release", publish)
    assert await cli.execute(cli.parse_args(["--verify"]), live_settings=SimpleNamespace()) == cli.EXIT_OK
    assert '"verified": true' in capsys.readouterr().out
    publish.assert_not_awaited()


async def test_verify_blocks_when_the_runtime_catalog_is_inconsistent(monkeypatch, capsys):
    from bisheng.common.errcode.permission import PermissionPublishNotReadyError

    monkeypatch.setattr(cli, "initialize_app_context", AsyncMock())
    monkeypatch.setattr(cli, "close_app_context", AsyncMock())
    failing = AsyncMock(side_effect=PermissionPublishNotReadyError(msg="stored model differs"))
    monkeypatch.setattr(cli, "SqlPermissionControlState", lambda: SimpleNamespace(current_catalog=failing))
    assert await cli.execute(cli.parse_args(["--verify"]), live_settings=SimpleNamespace()) == cli.EXIT_BLOCKED
    assert '"verified": false' in capsys.readouterr().out
