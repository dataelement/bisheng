"""Tenant transfer uses the normal durable projection writer and original retry fence."""

from bisheng.core.context.tenant import tenant_execution_scope
from bisheng.permission.domain.services.tenant_transfer_policy import blocked, compile_transfer


async def verify_transfer_input(projection, snapshots, *, source, destination, pin, operator_id):
    """A transport/pin failure cannot move any SQL resource; only native Grant edges are touched."""
    graphs = {}
    for snapshot in snapshots:
        plan = compile_transfer(snapshot, source=source, destination=destination, pin=pin, operator_id=operator_id)
        old = {row.key for row in plan.deltas if row.action == "DELETE"}
        new = {row.key for row in plan.deltas if row.action == "WRITE"} - old
        objects = {plan.scope_key} | {row.object for row in plan.deltas if row.object.startswith("permission_grant:")}
        for key in sorted(objects):
            graphs[key] = await projection._fga.read_object(key)
        before = set().union(*(graphs[key] for key in objects))
        if not old <= before or before.intersection(new):
            blocked(f"physical Grant graph differs: {plan.scope_key}")
        resource_graph = graphs[plan.scope_key]
        expected_visible = {
            (row["projected_subject"], "visible", plan.scope_key)
            for row in snapshot["visible"]
            if row["state"] == "ACTIVE"
        }
        if {row for row in resource_graph if row[1] == "visible"} != expected_visible:
            blocked(f"physical visibility differs: {plan.scope_key}")
        from bisheng.core.openfga.authorization_model_f048 import TECHNICAL_MARKER_SUBJECTS

        mode = snapshot["mode"]
        mode_rows = {(user, mode["mode"].lower() + "_mode", plan.scope_key) for user in TECHNICAL_MARKER_SUBJECTS}
        if {row for row in resource_graph if row[1] in {"custom_mode", "inherit_mode"}} != mode_rows:
            blocked(f"physical mode differs: {plan.scope_key}")
        parent = (
            {(f"{mode['parent_type']}:{mode['parent_id']}", "parent", plan.scope_key)}
            if mode["parent_type"] and mode["parent_id"]
            else set()
        )
        if {row for row in resource_graph if row[1] == "parent"} != parent:
            blocked(f"physical parent differs: {plan.scope_key}")
        expected_bindings = {key for key in old if key[1] == "grant"}
        if {key for key in graphs[plan.scope_key] if key[1] == "grant"} != expected_bindings:
            blocked(f"untracked resource Grant: {plan.scope_key}")
        for key in objects - {plan.scope_key}:
            if graphs[key] != {row for row in old if row[2] == key}:
                blocked(f"untracked Grant source: {plan.scope_key}")
    return graphs


async def resume_transfer(projection, operation_ids, *, destination):
    with tenant_execution_scope(destination):
        for ident in operation_ids:
            operation = await projection._repository.aget_operation(ident)
            if operation is None or operation.operation_type != "RESOURCE_TENANT_TRANSFER":
                blocked("transfer journal missing")
            if operation.status == "FAILED_CLOSED":
                preview = await projection.inspect_failed_closed_recovery(ident)
                await projection.recover_failed_closed_operation(
                    ident, confirmation_checksum=preview.confirmation_checksum
                )
            else:
                await projection.reconcile_operation(ident)


class _TransferTransport:
    def __init__(self, delegate, client):
        self.delegate, self.client = delegate, client

    async def write_atomic(self, **kwargs):
        return await self.delegate.write_atomic(**kwargs)

    async def read_present(self, *args, **kwargs):
        return await self.delegate.read_present(*args, **kwargs)

    async def read_object(self, object_key):
        rows = await self.client.read_tuples(object=object_key, consistency="HIGHER_CONSISTENCY")
        if any(row.get("condition") for row in rows):
            blocked("conditional permission tuples cannot be migrated")
        return frozenset((row["user"], row["relation"], row["object"]) for row in rows)


def transfer_projection(original, client):
    """Private operation composition: leave the shared online projection service unchanged."""
    from bisheng.permission.domain.services.projection_service import ProjectionService

    return ProjectionService(
        repository=original._repository,
        marker=original._marker,
        scope_guard=original._scope_guard,
        fga=_TransferTransport(original._fga, client),
        finalizer=original._finalizer,
        events=original._events,
    )
