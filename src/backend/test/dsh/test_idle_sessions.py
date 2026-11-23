"""AC-IDLE-01..08: real SQL/crypto lifecycle, per-device isolation and legacy transition."""

import hashlib
import importlib.util
import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from pydantic import ValidationError
from sqlmodel import Session, select

from bisheng.common.errcode.dsh import DshSessionExpiredError, DshSessionRevokedError, DshUserDisabledError
from bisheng.core.config.dsh import DshSettings
from bisheng.dsh.domain.models.local_session import (
    ABSOLUTE_SESSION_POLICY,
    SLIDING_SESSION_POLICY,
    DshRefreshToken,
    DshSession,
)
from bisheng.dsh.domain.repositories.local_session import DshSessionRepository
from bisheng.dsh.domain.services.access import DshPrincipal, principal_scope
from test.dsh import test_native_access as native_tests

native = native_tests.native
login = native_tests.login

IDLE = 14 * 86400


@pytest.fixture
def idle(native):
    runtime, engine = native
    clock = [datetime.now(UTC).replace(tzinfo=None, microsecond=0)]
    runtime.sessions.now = lambda: clock[0]
    runtime.sessions.idle_seconds = IDLE
    runtime.sessions.refresh_grace_seconds = 86400
    return runtime, engine, clock


def actor(issued, *, user="20", tenant="2"):
    return DshPrincipal(tenant_id=tenant, user_id=user, session_id=issued["session_id"])


def stored(engine, issued):
    with Session(engine) as session, principal_scope(actor(issued)):
        return session.get(DshSession, issued["session_id"])


def tokens(engine, issued):
    with Session(engine) as session, principal_scope(actor(issued)):
        return session.exec(
            select(DshRefreshToken)
            .where(DshRefreshToken.session_id == issued["session_id"])
            .order_by(DshRefreshToken.generation)
        ).all()


async def test_new_login_defaults_to_14_days_and_refresh_does_not_keep_it_alive(idle):
    """AC-IDLE-01, AC-IDLE-02: background rotation doesn't slide the deadline."""
    runtime, engine, clock = idle
    start = clock[0]
    issued = current = await login(runtime)
    row = stored(engine, issued)
    assert row.expiry_policy == SLIDING_SESSION_POLICY
    assert row.idle_ttl_seconds == IDLE
    assert row.last_activity_at == start
    assert row.expires_at == start + timedelta(days=14)
    assert issued["refresh_expires_in"] == IDLE
    for day in (1, 7, 13):
        clock[0] = start + timedelta(days=day)
        current = await runtime.sessions.refresh(current["refresh_token"])
        assert current["session_expires_at"] == issued["session_expires_at"]
    assert stored(engine, issued).last_activity_at == start
    clock[0] = start + timedelta(days=14)
    with pytest.raises(DshSessionExpiredError):
        await runtime.sessions.refresh(current["refresh_token"])
    with pytest.raises(DshSessionExpiredError):
        await runtime.sessions.record_activity(actor(issued))


async def test_business_activity_slides_past_30_and_60_days_and_pins_policy(idle):
    """AC-IDLE-01, AC-IDLE-03: no hidden absolute cap or moving config interpretation."""
    runtime, engine, clock = idle
    start = clock[0]
    issued = current = await login(runtime)
    runtime.sessions.idle_seconds = 7 * 86400
    for day in (13, 26, 39, 52, 65):
        clock[0] = start + timedelta(days=day)
        await runtime.sessions.record_activity(actor(issued))
        current = await runtime.sessions.refresh(current["refresh_token"])
        row = stored(engine, issued)
        assert row.created_at == start
        assert row.idle_ttl_seconds == IDLE
        assert row.expires_at == clock[0] + timedelta(days=14)
        assert row.version == 1
        assert current["session_id"] == issued["session_id"]
        assert current["refresh_expires_in"] == IDLE
        assert tokens(engine, issued)[-1].expires_at == row.expires_at


@pytest.mark.parametrize("action", ["activity", "refresh"])
async def test_waiting_for_the_session_lock_does_not_revive_expired_credentials(idle, monkeypatch, action):
    runtime, engine, clock = idle
    start = clock[0]
    issued = await login(runtime)
    clock[0] = start + timedelta(days=14, seconds=-1)
    original_get = DshSessionRepository.get

    def lock_after_expiry(repository, session_id, *, lock=False):
        row = original_get(repository, session_id, lock=lock)
        if lock:
            clock[0] = start + timedelta(days=14)
        return row

    monkeypatch.setattr(DshSessionRepository, "get", lock_after_expiry)
    with pytest.raises(DshSessionExpiredError):
        if action == "activity":
            await runtime.sessions.record_activity(actor(issued))
        else:
            await runtime.sessions.refresh(issued["refresh_token"])
    assert stored(engine, issued).last_activity_at == start
    assert len(tokens(engine, issued)) == 1


async def test_activity_does_not_rotate_and_old_unspent_token_survives_its_original_deadline(idle):
    runtime, engine, clock = idle
    start = clock[0]
    issued = await login(runtime)
    clock[0] = start + timedelta(days=13)
    await runtime.sessions.record_activity(actor(issued))
    assert len(tokens(engine, issued)) == 1
    clock[0] = start + timedelta(days=20)
    refreshed = await runtime.sessions.refresh(issued["refresh_token"])
    assert refreshed["refresh_expires_in"] == 7 * 86400
    assert stored(engine, issued).last_activity_at == start + timedelta(days=13)


async def test_lost_response_recovery_after_old_deadline_does_not_touch_activity(idle):
    """AC-IDLE-04: old USED expiry isn't an independent cap on a sliding session."""
    runtime, engine, clock = idle
    start = clock[0]
    issued = await login(runtime)
    clock[0] = start + timedelta(days=13, hours=23)
    successor = await runtime.sessions.refresh(issued["refresh_token"])
    await runtime.sessions.record_activity(actor(issued))
    last = stored(engine, issued).last_activity_at
    before = [(row.token_hash, row.state, row.used_at, row.expires_at) for row in tokens(engine, issued)]
    clock[0] += timedelta(hours=8)
    recovered = await runtime.sessions.refresh(issued["refresh_token"])
    assert recovered["refresh_token"] == successor["refresh_token"]
    assert stored(engine, issued).last_activity_at == last
    assert [(row.token_hash, row.state, row.used_at, row.expires_at) for row in tokens(engine, issued)] == before


async def test_only_the_active_device_slides_and_expired_device_cannot_revive(idle):
    """AC-IDLE-05: a user's active Mac never extends another device."""
    runtime, engine, clock = idle
    start = clock[0]
    first, second = await login(runtime), await login(runtime)
    clock[0] += timedelta(days=13)
    await runtime.sessions.record_activity(actor(first))
    clock[0] = start + timedelta(days=14)
    await runtime.sessions.refresh(first["refresh_token"])
    with pytest.raises(DshSessionExpiredError):
        await runtime.sessions.refresh(second["refresh_token"])
    with pytest.raises(DshSessionExpiredError):
        await runtime.sessions.record_activity(actor(second))
    assert stored(engine, second).last_activity_at == start


async def test_activity_is_owner_and_tenant_scoped_and_rechecks_disabled_identity(idle):
    runtime, engine, clock = idle
    issued = await login(runtime)
    original = stored(engine, issued).expires_at
    with principal_scope(actor(issued, user="21")):
        row, error = await runtime.sessions.run(
            lambda repo: repo.record_activity(
                actor(issued, user="21"), lambda: clock[0], idle_seconds=IDLE, migrate_existing=True
            )
        )
    assert row is None and error == "invalid_access_token"
    with principal_scope(actor(issued, tenant="3")):
        row, error = await runtime.sessions.run(
            lambda repo: repo.record_activity(
                actor(issued, tenant="3"), lambda: clock[0], idle_seconds=IDLE, migrate_existing=True
            )
        )
    assert row is None and error == "invalid_access_token"
    runtime.identity.identities.get.return_value.active = False
    with pytest.raises(DshUserDisabledError):
        await runtime.sessions.record_activity(actor(issued))
    assert stored(engine, issued).expires_at == original


async def test_legacy_sessions_convert_only_on_admitted_activity_when_enabled(idle):
    """AC-IDLE-06: neither deploy nor refresh fabricates historical activity."""
    runtime, engine, clock = idle
    runtime.sessions.idle_seconds = None
    issued = await login(runtime)
    initial = stored(engine, issued)
    assert initial.expiry_policy == ABSOLUTE_SESSION_POLICY
    assert initial.last_activity_at is None
    runtime.sessions.idle_seconds = IDLE
    clock[0] += timedelta(days=20)
    current = await runtime.sessions.refresh(issued["refresh_token"])
    await runtime.sessions.record_activity(actor(issued))
    assert stored(engine, issued).expires_at == initial.expires_at
    runtime.sessions.migrate_idle_sessions = True
    await runtime.sessions.refresh(current["refresh_token"])
    assert stored(engine, issued).last_activity_at is None
    await runtime.sessions.record_activity(actor(issued))
    converted = stored(engine, issued)
    assert converted.expiry_policy == SLIDING_SESSION_POLICY
    assert converted.expires_at == clock[0] + timedelta(days=14)
    assert tokens(engine, issued)[-1].expires_at == converted.expires_at


async def test_revocation_stays_constant_size_and_cannot_be_overwritten_by_activity(idle):
    runtime, engine, clock = idle
    issued = await login(runtime)
    with Session(engine) as session:
        session.add_all(
            [
                DshRefreshToken(
                    tenant_id=2,
                    session_id=issued["session_id"],
                    generation=n,
                    token_hash=hashlib.sha256(f"synthetic-history-{n}".encode()).hexdigest(),
                    state="USED",
                    used_at=clock[0],
                    expires_at=clock[0] + timedelta(days=14),
                )
                for n in range(2, 502)
            ]
        )
        session.commit()
    statements = []

    def observe(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement.lower())

    sa.event.listen(engine, "before_cursor_execute", observe)
    try:
        await runtime.sessions.revoke(2, 20, issued["session_id"])
    finally:
        sa.event.remove(engine, "before_cursor_execute", observe)
    assert not any("dsh_refresh_token" in statement for statement in statements)
    with pytest.raises(DshSessionRevokedError):
        await runtime.sessions.refresh(issued["refresh_token"])
    with pytest.raises(DshSessionRevokedError):
        await runtime.sessions.record_activity(actor(issued))


def test_idle_config_keeps_legacy_absolute_ttl_and_has_a_separate_rollout_switch():
    config = DshSettings()
    assert config.session_idle_ttl_seconds == IDLE
    assert config.session_ttl_seconds == 30 * 86400
    assert config.session_idle_migrate_existing is False
    for value in (599, 30 * 86400 + 1, "1209600"):
        with pytest.raises(ValidationError):
            DshSettings(session_idle_ttl_seconds=value)


def test_migration_is_ddl_only_repeatable_and_preserves_legacy_rows():
    """AC-IDLE-08: upgrade old schema without backfilling invented activity."""
    path = Path(__file__).resolve().parents[2] / "bisheng/core/database/alembic/versions/v3_0_0_dsh_idle_sessions.py"
    spec = importlib.util.spec_from_file_location("idle_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = sa.create_engine("sqlite://")
    try:
        with engine.begin() as conn:
            conn.execute(sa.text("CREATE TABLE dsh_session (session_id VARCHAR(36) PRIMARY KEY)"))
            conn.execute(
                sa.text("CREATE TABLE dsh_refresh_token (tenant_id BIGINT, session_id VARCHAR(36), state VARCHAR(16))")
            )
            conn.execute(sa.text("INSERT INTO dsh_session (session_id) VALUES ('synthetic-legacy')"))
            with Operations.context(MigrationContext.configure(conn)):
                module.upgrade()
                module.upgrade()
                module.downgrade()
            row = conn.execute(
                sa.text("SELECT expiry_policy, last_activity_at, idle_ttl_seconds FROM dsh_session")
            ).one()
            assert tuple(row) == (ABSOLUTE_SESSION_POLICY, None, None)
            indexes = sa.inspect(conn).get_indexes("dsh_refresh_token")
            assert next(index for index in indexes if index["name"] == "ix_dsh_refresh_active")["column_names"] == [
                "tenant_id",
                "session_id",
                "state",
            ]
    finally:
        engine.dispose()


async def test_released_desktop_parser_accepts_the_sliding_deadline(idle):
    """AC-IDLE-07: use the unmodified released package, not a Python facsimile."""
    desktop = os.environ.get("DSH_DESKTOP_SOURCE_DIR")
    if not desktop:
        pytest.skip("Set DSH_DESKTOP_SOURCE_DIR to the exported v1.2.0 package")
    runtime, _engine, clock = idle
    issued = await login(runtime)
    clock[0] += timedelta(days=13)
    await runtime.sessions.record_activity(actor(issued))
    renewed = await runtime.sessions.refresh(issued["refresh_token"])
    contract = (Path(desktop) / "packages/dsh-desktop-enterprise/contract.js").resolve()
    assert contract.is_file()
    script = """
import { readFileSync } from 'node:fs';
const { parseToken } = await import(process.argv[1]);
const { initial, updated } = JSON.parse(readFileSync(0, 'utf8'));
const a = parseToken(initial, 'https://platform.example');
const b = parseToken(updated, 'https://platform.example');
if (a.session_id !== b.session_id || !(Date.parse(b.session_expires_at) > Date.parse(a.session_expires_at))) {
  throw new Error('Sliding expiry contract failed');
}
process.stdout.write('sliding-contract-ok');
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script, contract.as_uri()],
        input=json.dumps({"initial": issued, "updated": renewed}),
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, "Released desktop parser rejected sliding expiry"
    assert result.stdout == "sliding-contract-ok"
