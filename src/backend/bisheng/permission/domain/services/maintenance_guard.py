"""Opt-in operational fences; ordinary permission requests remain unchanged.

Callbacks are supplied by an explicit maintenance composition. Permission
services know neither migration Runs nor their owning business repositories.
"""

import json
from contextlib import contextmanager
from contextvars import ContextVar
from hashlib import sha256

from loguru import logger

from bisheng.core.context.tenant import get_current_tenant_id, tenant_execution_scope

_maintenance = ContextVar("f048_explicit_maintenance_guards", default=None)


@contextmanager
def maintenance_guard(*, transaction_guard=None, external_guard=None, global_tenants=(), identity=None):
    token = _maintenance.set((transaction_guard, external_guard, tuple(sorted(set(global_tenants))), identity or {}))
    try:
        yield
    finally:
        _maintenance.reset(token)


async def acheck_transaction(session, *, global_scope=False):
    state = _maintenance.get()
    if state is None or state[0] is None:
        return
    callback, _external, tenants, _identity = state
    scopes = tenants if global_scope else (get_current_tenant_id(),)
    for tenant in scopes:
        # The explicit maintenance caller may be in a global SQL read/write
        # scope. The opaque guard itself requires one concrete, strict tenant.
        with tenant_execution_scope(tenant):
            await callback(session)


async def guarded_fga_write(port, *, writes, deletes):
    state = _maintenance.get()
    if state is None or state[1] is None:
        return await port.write_atomic(writes=writes, deletes=deletes)
    _callback, external, _tenants, identity = state
    rows = [(row.phase, row.sequence, row.action, row.user, row.relation, row.object) for row in (*writes, *deletes)]
    digest = sha256(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    ticket = await external.begin(
        kind="history_fga",
        identity={**identity, "tenant_id": get_current_tenant_id(), "request_sha256": digest, "tuple_count": len(rows)},
    )
    try:
        receipt = await port.write_atomic(writes=writes, deletes=deletes)
    except BaseException:
        try:
            await external.finish(ticket, outcome="unknown", receipt=None)
        except Exception:
            # The durable dispatch intent remains open even when the control
            # connection vanished. Never convert this cleanup failure to ACK.
            logger.warning("Maintenance FGA dispatch remains uncertain; original durable intent requires recovery")
        raise
    acknowledgement = sha256(
        json.dumps(
            {"request_sha256": digest, "commit_checksum": receipt}, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    await external.finish(ticket, outcome="acknowledged", receipt=acknowledgement)
    return receipt
