"""CLI contract for the unique F048 data-migration entry point."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from bisheng.common.errcode.permission import PermissionMigrationBlockedError
from bisheng.core.openfga.authorization_model_f048 import (
    authorization_model_checksum,
    get_authorization_model_f048,
)
from bisheng.core.openfga.discovery import OpenFGARuntimePin
from scripts import migrate_f048_permission_data as cli
from scripts.f048_migration_runtime import _require_predecessor_source

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def test_migrate_requires_apply_before_runtime_initialization():
    with pytest.raises(SystemExit) as exc_info:
        cli.parse_args(["migrate"])

    assert exc_info.value.code == 2


@pytest.mark.parametrize("command", ["dry-run", "rollback", "inventory", "cleanup"])
def test_unsupported_preview_or_rollback_commands_are_rejected(command):
    with pytest.raises(SystemExit) as exc_info:
        cli.parse_args([command])

    assert exc_info.value.code == 2


@pytest.mark.parametrize(
    "arguments",
    [
        ["migrate", "--apply", "--store-id", "replacement"],
        ["migrate", "--apply", "--model-id", "intermediate-model"],
        ["migrate", "--apply", "--visible-slot", "b"],
        ["migrate", "--apply", "--dual-model-mode"],
        ["verify", "--run-id", "7", "--legacy-model-id", "legacy"],
    ],
)
def test_store_model_and_ab_override_parameters_are_rejected(arguments):
    with pytest.raises(SystemExit) as exc_info:
        cli.parse_args(arguments)

    assert exc_info.value.code == 2


def test_new_migration_is_rejected_when_store_already_uses_final_f048_model():
    pin = OpenFGARuntimePin(
        store_id="durable-store",
        model_id="final-model",
        model_checksum=authorization_model_checksum(get_authorization_model_f048()),
    )

    with pytest.raises(PermissionMigrationBlockedError, match="F048_MIGRATION_ALREADY_COMPLETED"):
        _require_predecessor_source(pin=pin, run_id=None)

    _require_predecessor_source(pin=pin, run_id=7)


def test_formal_migration_is_not_called_from_api_or_celery_startup():
    entrypoint = "migrate_f048_permission_data"
    startup_files = (
        BACKEND_ROOT / "bisheng/main.py",
        BACKEND_ROOT / "bisheng/run_celery.py",
        BACKEND_ROOT / "bisheng/worker/main.py",
    )

    assert all(entrypoint not in path.read_text(encoding="utf-8") for path in startup_files)


@dataclass
class FakeRuntime:
    coordinator: object
    verifier: object
    source_client: object
    closed: bool = False

    async def aclose(self):
        self.closed = True


class FakeCoordinator:
    def __init__(self):
        self.calls = []

    async def migrate(self, **kwargs):
        self.calls.append(kwargs)
        return type(
            "Result",
            (),
            {
                "run_id": 7,
                "phase": "VERIFYING",
                "store_id": "store-live",
                "source_model_id": "legacy-model",
                "target_model_id": "new-model",
                "source_checksum": "s" * 64,
                "target_checksum": "t" * 64,
            },
        )()

    async def reset_source(self, **kwargs):
        self.calls.append(kwargs)
        return type(
            "Run",
            (),
            {
                "id": 7,
                "phase": "SOURCE_VALIDATING",
                "status": "BLOCKED",
                "checkpoint": "source-reset-requested",
            },
        )()


class FakeVerifier:
    def __init__(self):
        self.calls = []

    async def verify(self, **kwargs):
        self.calls.append(kwargs)
        return type(
            "Run",
            (),
            {"id": 7, "phase": "READY_TO_START"},
        )()


@dataclass(frozen=True)
class _CopyableOpenFGA:
    enabled: bool = True

    def model_copy(self, *, update):
        return _CopyableOpenFGA(**{**self.__dict__, **update})


@dataclass(frozen=True)
class _CopyableSettings:
    openfga: _CopyableOpenFGA = _CopyableOpenFGA()

    def model_copy(self, *, update):
        return _CopyableSettings(**{**self.__dict__, **update})


def test_migration_context_does_not_initialize_online_model_pin() -> None:
    live = _CopyableSettings()

    migration = cli._migration_context_settings(live)

    assert live.openfga.enabled is True
    assert migration.openfga.enabled is False


async def test_migrate_initializes_and_closes_full_app_context():
    events = []
    coordinator = FakeCoordinator()
    verifier = FakeVerifier()
    runtime = FakeRuntime(
        coordinator,
        verifier,
        type("SourceClient", (), {"store_id": "store-live"})(),
    )

    async def initialize_context(*, config):
        events.append(("initialize", config))

    async def close_context():
        events.append(("close",))

    args = cli.parse_args(
        [
            "migrate",
            "--apply",
            "--lock-token",
            "operator-1",
        ]
    )
    exit_code = await cli.execute(
        args,
        runtime_factory=lambda **_: runtime,
        initialize_context=initialize_context,
        close_context=close_context,
        live_settings="live-settings",
    )

    assert exit_code == cli.EXIT_OK
    assert events == [
        ("initialize", "live-settings"),
        ("close",),
    ]
    assert coordinator.calls == [
        {
            "expected_store_id": "store-live",
            "lock_token": "operator-1",
            "run_id": None,
        }
    ]
    assert verifier.calls == []
    assert runtime.closed is True


async def test_verify_only_reads_existing_formal_run_and_always_closes():
    events = []
    runtime_run_ids = []
    coordinator = FakeCoordinator()
    verifier = FakeVerifier()
    runtime = FakeRuntime(
        coordinator,
        verifier,
        type("SourceClient", (), {"store_id": "store-live"})(),
    )

    async def initialize_context(*, config):
        events.append("initialize")

    async def close_context():
        events.append("close")

    args = cli.parse_args(["verify", "--run-id", "7"])
    exit_code = await cli.execute(
        args,
        runtime_factory=lambda **kwargs: runtime_run_ids.append(kwargs["run_id"]) or runtime,
        initialize_context=initialize_context,
        close_context=close_context,
        live_settings="live-settings",
    )

    assert exit_code == cli.EXIT_OK
    assert verifier.calls == [{"run_id": 7}]
    assert coordinator.calls == []
    assert runtime_run_ids == [7]
    assert events == ["initialize", "close"]
    assert runtime.closed is True


async def test_migrate_resume_passes_the_existing_run_id():
    coordinator = FakeCoordinator()
    verifier = FakeVerifier()

    async def initialize_context(*, config):
        return None

    async def close_context():
        return None

    args = cli.parse_args(
        [
            "migrate",
            "--apply",
            "--run-id",
            "9",
        ]
    )
    await cli.execute(
        args,
        runtime_factory=lambda **_: FakeRuntime(
            coordinator,
            verifier,
            type("SourceClient", (), {"store_id": "store-live"})(),
        ),
        initialize_context=initialize_context,
        close_context=close_context,
        live_settings="live-settings",
    )

    assert coordinator.calls[0]["run_id"] == 9


async def test_reset_source_requires_apply_and_calls_pre_target_reset():
    with pytest.raises(SystemExit) as exc_info:
        cli.parse_args(["reset-source", "--run-id", "7"])
    assert exc_info.value.code == 2

    coordinator = FakeCoordinator()

    async def initialize_context(*, config):
        return None

    async def close_context():
        return None

    args = cli.parse_args(
        [
            "reset-source",
            "--run-id",
            "7",
            "--lock-token",
            "operator-reset",
            "--apply",
        ]
    )
    exit_code = await cli.execute(
        args,
        runtime_factory=lambda **_: FakeRuntime(
            coordinator,
            FakeVerifier(),
            type("SourceClient", (), {"store_id": "store-live"})(),
        ),
        initialize_context=initialize_context,
        close_context=close_context,
        live_settings="live-settings",
    )

    assert exit_code == cli.EXIT_OK
    assert coordinator.calls == [
        {
            "expected_store_id": "store-live",
            "lock_token": "operator-reset",
            "run_id": 7,
        }
    ]


def test_runtime_resume_pins_durable_store_and_source_model():
    source = (BACKEND_ROOT / "scripts/f048_migration_runtime.py").read_text(encoding="utf-8")

    assert "required_store_id=run.store_id if run else None" in source
    assert "required_model_id=run.source_model_id if run else None" in source
