"""Deployment must repair SA inheritance even when the model is unchanged."""

from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bisheng.core.openfga.authorization_model_f048 import (
    authorization_model_checksum,
    build_authorization_model_f048,
)
from bisheng.permission.domain.models import ResourcePermissionMode
from scripts import publish_authorization_model_change as cli
from scripts import reconcile_f048_visible_projection as reconcile
from test.permission.test_f048_authorization_model import (
    ModelEvaluator,
    _active_model_tuples,
    _resource_grant_tuples,
)


def _legacy_space():
    nodes = (
        ("knowledge_space:137", None, "CUSTOM"),
        ("folder:742", "knowledge_space:137", "INHERIT"),
        ("folder:744", "folder:742", "INHERIT"),
        ("knowledge_file:783", "folder:744", "INHERIT"),
        ("folder:745", "folder:742", "CUSTOM"),
        ("knowledge_file:784", "folder:745", "INHERIT"),
    )
    rows = tuple(
        ResourcePermissionMode(
            tenant_id=1,
            resource_type=key.split(":")[0],
            resource_id=key.split(":")[1],
            parent_type=parent.split(":")[0] if parent else None,
            parent_id=parent.split(":")[1] if parent else None,
            mode=mode,
            projection_state="CURRENT",
        )
        for key, parent, mode in nodes
    )
    tuples = _active_model_tuples(actions=("edit", "rename", "upload_file"), marker_subject="service_account:*")
    tuples |= _resource_grant_tuples(
        resource="knowledge_space:137",
        grant="permission_grant:space-editor",
        model_key="editor",
        subject="service_account:2",
    )
    for key, parent, mode in nodes:
        tuples.add(("user:*", "permission_enabled", key))
        tuples.add(("user:*", f"{mode.lower()}_mode", key))
        if parent:
            tuples.add((parent, "parent", key))
    return rows, tuples


@pytest.fixture
def publication(monkeypatch):
    model = build_authorization_model_f048()
    checksum = authorization_model_checksum(model)
    rows, tuples = _legacy_space()
    markers = reconcile._compile_service_account_resource_markers(rows)
    current = cli.CurrentRelease(
        catalog_id=37,
        catalog_key="catalog-37",
        environment="production",
        store_id="test-store",
        model_id="current-model",
        model_release_id=4,
        model_checksum=checksum,
        write_fenced=False,
    )
    state = SimpleNamespace(
        current=current,
        tuples=tuples,
        markers=markers,
        initial_tuples=set(tuples),
        events=[],
        writes=[],
        fail_write=False,
        fail_verify=False,
        remote_model_id="current-model",
        publisher=AsyncMock(return_value="new-model"),
    )

    class Client:
        def __init__(self, *, model_id, **_kwargs):
            self.model_id = model_id

        def for_model(self, model_id):
            return Client(model_id=model_id)

        @staticmethod
        def validate_business_mutation_size(count):
            assert count <= 90

        async def write_tuples(self, *, writes, ignore_duplicate_writes):
            assert ignore_duplicate_writes is True
            state.events.append("write")
            state.writes.append((self.model_id, writes))
            if state.fail_write:
                raise RuntimeError("marker write unavailable")
            state.tuples.update((row["user"], row["relation"], row["object"]) for row in writes)

        async def batch_check(self, checks, *, consistency):
            assert consistency == "HIGHER_CONSISTENCY"
            state.events.append("verify")
            evaluator = ModelEvaluator(model, state.tuples)
            return [
                not state.fail_verify and evaluator.check(row["user"], row["relation"], row["object"]) for row in checks
            ]

        async def iter_tuples(self, *, consistency):
            assert consistency == "HIGHER_CONSISTENCY"
            for user, relation, obj in state.tuples:
                yield {"user": user, "relation": relation, "object": obj}

        async def close(self):
            state.events.append("client_closed")

    async def discover(*_args, **_kwargs):
        return SimpleNamespace(model_id=state.current.model_id, model_checksum=state.current.model_checksum)

    async def cutover(**kwargs):
        assert state.markers <= state.tuples
        assert "verify" in state.events
        state.events.append("cutover")
        state.current = replace(
            state.current,
            catalog_id=38,
            model_id=kwargs["target_client"].model_id,
            model_checksum=checksum,
        )
        return state.current.catalog_id

    state.cutover = AsyncMock(side_effect=cutover)
    state.activate = AsyncMock()
    state.window = AsyncMock(side_effect=lambda: state.events.append("maintenance_verified"))
    monkeypatch.setattr(cli, "initialize_app_context", AsyncMock())
    monkeypatch.setattr(cli, "close_app_context", AsyncMock())
    monkeypatch.setattr(cli, "_load_current_release", AsyncMock(side_effect=lambda: state.current))
    monkeypatch.setattr(cli, "discover_openfga_runtime", discover)
    monkeypatch.setattr(cli, "FGAClient", Client)
    monkeypatch.setattr(cli, "_find_remote_model_id", AsyncMock(side_effect=lambda *_args: state.remote_model_id))
    monkeypatch.setattr(cli, "load_service_account_resource_markers", AsyncMock(return_value=markers))
    monkeypatch.setattr(cli, "_assert_apply_window", state.window)
    monkeypatch.setattr(cli, "_authorization_release_id", AsyncMock(return_value=5))
    monkeypatch.setattr(cli, "_activate_model_release", state.activate)
    monkeypatch.setattr(cli, "_publish_noop_catalog_cutover", state.cutover)
    monkeypatch.setattr(cli, "_retire_other_active_models", AsyncMock())
    monkeypatch.setattr(
        cli, "OpenFGAMigrationModelPublisher", lambda **_kwargs: SimpleNamespace(aget_or_publish=state.publisher)
    )
    state.args = cli.parse_args(
        [
            "--apply",
            "--confirm-store-id",
            current.store_id,
            "--confirm-target-model-checksum",
            checksum,
            "--operator-id",
            "1",
        ]
    )
    state.settings = SimpleNamespace(
        environment="production", openfga=SimpleNamespace(api_url="http://unused", timeout=5)
    )
    return state


async def test_dry_run_reports_expected_markers_without_writes(publication, capsys):
    state = publication
    assert await cli.execute(cli.parse_args([]), live_settings=state.settings) == 0

    report = json.loads(capsys.readouterr().out.splitlines()[0])
    assert report["needs_catalog_cutover"] is False
    assert report["service_account_marker_tuple_count"] == len(state.markers)
    assert state.tuples == state.initial_tuples
    assert state.writes == []
    state.activate.assert_not_awaited()
    state.cutover.assert_not_awaited()


async def test_current_model_repairs_inheritance_and_is_repeatable(publication, capsys):
    state = publication
    before = ModelEvaluator(build_authorization_model_f048(), state.tuples)
    assert before.check("service_account:2", "visible", "knowledge_space:137")
    assert not before.check("service_account:2", "visible", "knowledge_file:783")

    assert await cli.execute(state.args, live_settings=state.settings) == 0

    assert state.tuples == state.initial_tuples | state.markers
    after = ModelEvaluator(build_authorization_model_f048(), state.tuples)
    for key in ("folder:742", "folder:744", "knowledge_file:783"):
        assert after.check("service_account:2", "visible", key)
        assert after.check("service_account:2", "can_rename", key)
        assert not after.check("service_account:3", "visible", key)
    assert after.check("service_account:2", "can_upload_file", "folder:744")
    for key in ("folder:745", "knowledge_file:784"):
        assert not after.check("service_account:2", "visible", key)
        assert not after.check("service_account:2", "can_edit", key)
    assert state.events.index("maintenance_verified") < state.events.index("write")
    assert state.events.index("write") < state.events.index("verify")
    result = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert result["event"] == "already_current"
    assert result["service_account_marker_tuples_verified"] == len(state.markers)

    snapshot = set(state.tuples)
    assert await cli.execute(state.args, live_settings=state.settings) == 0
    assert state.tuples == snapshot
    state.publisher.assert_not_awaited()
    state.activate.assert_not_awaited()
    state.cutover.assert_not_awaited()


@pytest.mark.parametrize("existing_model", [None, "new-model"])
async def test_model_upgrade_repairs_on_target_model_before_catalog_cutover(publication, existing_model):
    state = publication
    state.current = replace(state.current, model_checksum="old-checksum")
    state.remote_model_id = existing_model

    assert await cli.execute(state.args, live_settings=state.settings) == 0

    assert state.tuples == state.initial_tuples | state.markers
    assert all(model_id == "new-model" for model_id, _ in state.writes)
    assert state.events.index("verify") < state.events.index("cutover")
    assert state.publisher.await_count == (0 if existing_model else 1)
    state.cutover.assert_awaited_once()


@pytest.mark.parametrize("changed_model", [False, True])
@pytest.mark.parametrize("failure", ["write", "verify"])
async def test_repair_failure_never_reports_success_or_cuts_over(publication, changed_model, failure, capsys):
    state = publication
    if changed_model:
        state.current = replace(state.current, model_checksum="old-checksum")
        state.remote_model_id = "new-model"
    state.fail_write = failure == "write"
    state.fail_verify = failure == "verify"

    error = RuntimeError if failure == "write" else reconcile.VisibleReconcileBlockedError
    with pytest.raises(error):
        await cli.execute(state.args, live_settings=state.settings)

    assert '"event"' not in capsys.readouterr().out
    state.activate.assert_not_awaited()
    state.cutover.assert_not_awaited()
    cli.close_app_context.assert_awaited_once()


@pytest.mark.parametrize("block", ["store", "checksum", "catalog_fence", "runtime_heartbeat", "projection_operation"])
async def test_apply_preconditions_block_marker_writes(publication, block):
    state = publication
    if block == "store":
        state.args.confirm_store_id = "other-store"
    elif block == "checksum":
        state.args.confirm_target_model_checksum = "other-checksum"
    elif block == "catalog_fence":
        state.current = replace(state.current, write_fenced=True)
    else:
        state.window.side_effect = cli.AuthorizationModelPublishBlockedError(block)

    with pytest.raises(cli.AuthorizationModelPublishBlockedError):
        await cli.execute(state.args, live_settings=state.settings)

    assert state.writes == []
    assert state.tuples == state.initial_tuples
    state.publisher.assert_not_awaited()
    state.cutover.assert_not_awaited()


async def test_resource_markers_are_repaired_in_bounded_batches(publication, monkeypatch):
    state = publication
    state.markers = frozenset(
        ("service_account:*", relation, f"folder:{index}")
        for index in range(100)
        for relation in ("permission_enabled", "inherit_mode")
    )
    monkeypatch.setattr(cli, "load_service_account_resource_markers", AsyncMock(return_value=state.markers))

    assert await cli.execute(state.args, live_settings=state.settings) == 0

    assert [len(batch) for _, batch in state.writes] == [80, 80, 40]
    assert state.tuples == state.initial_tuples | state.markers


def test_cli_propagates_marker_verification_failure(monkeypatch):
    monkeypatch.setattr(
        cli, "execute", AsyncMock(side_effect=reconcile.VisibleReconcileBlockedError("marker verification failed"))
    )
    assert cli.main([]) == cli.EXIT_BLOCKED


@pytest.mark.parametrize("operator_args", [[], ["--operator-id", "0"], ["--operator-id", "-1"]])
def test_apply_requires_an_audit_operator(operator_args):
    with pytest.raises(SystemExit) as error:
        cli.parse_args(
            [
                "--apply",
                "--confirm-store-id",
                "test-store",
                "--confirm-target-model-checksum",
                "checksum",
                *operator_args,
            ]
        )
    assert error.value.code == 2
