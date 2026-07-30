"""CLI contract for the unique F048 data-migration entry point."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from scripts import migrate_f048_permission_data as cli


def test_migrate_requires_apply_before_runtime_initialization():
    with pytest.raises(SystemExit) as exc_info:
        cli.parse_args(["migrate", "--expected-store-id", "store-live"])

    assert exc_info.value.code == 2


@pytest.mark.parametrize("command", ["dry-run", "rollback", "inventory", "cleanup"])
def test_unsupported_preview_or_rollback_commands_are_rejected(command):
    with pytest.raises(SystemExit) as exc_info:
        cli.parse_args([command])

    assert exc_info.value.code == 2


@dataclass
class FakeRuntime:
    coordinator: object
    verifier: object
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
    runtime = FakeRuntime(coordinator, verifier)

    async def initialize_context(*, config):
        events.append(("initialize", config))

    async def close_context():
        events.append(("close",))

    args = cli.parse_args(
        [
            "migrate",
            "--apply",
            "--expected-store-id",
            "store-live",
            "--lock-token",
            "operator-1",
        ]
    )
    exit_code = await cli.execute(
        args,
        runtime_factory=lambda: runtime,
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
    coordinator = FakeCoordinator()
    verifier = FakeVerifier()
    runtime = FakeRuntime(coordinator, verifier)

    async def initialize_context(*, config):
        events.append("initialize")

    async def close_context():
        events.append("close")

    args = cli.parse_args(["verify", "--run-id", "7"])
    exit_code = await cli.execute(
        args,
        runtime_factory=lambda: runtime,
        initialize_context=initialize_context,
        close_context=close_context,
        live_settings="live-settings",
    )

    assert exit_code == cli.EXIT_OK
    assert verifier.calls == [{"run_id": 7}]
    assert coordinator.calls == []
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
            "--expected-store-id",
            "store-live",
            "--run-id",
            "9",
        ]
    )
    await cli.execute(
        args,
        runtime_factory=lambda: FakeRuntime(coordinator, verifier),
        initialize_context=initialize_context,
        close_context=close_context,
        live_settings="live-settings",
    )

    assert coordinator.calls[0]["run_id"] == 9
