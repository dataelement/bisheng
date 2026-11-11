"""Read-only pre-upgrade diagnostics; unknown facts remain explicit."""

from bisheng.role.application.effective_roles import load_effective_roles
from bisheng.tenant.domain.repositories.managed_tenant_preflight import ManagedTenantPreflightRepository
from bisheng.user.application.policy_bindings import read_policy_subject


async def inspect_managed_tenant(tenant_id, user_ids=(), limit=100):
    report = await ManagedTenantPreflightRepository.inventory(tenant_id, user_ids, limit)
    people = []
    for uid in report.pop("users"):
        item = {"user_id": uid}
        try:
            subject = await read_policy_subject(uid)
            policy = await load_effective_roles(uid, expected_home_tenant_id=subject.home_tenant_id)
            raw = sorted({row.role_id for row in subject.bindings if row.tenant_id == tenant_id and row.role_id != 1})
            item.update(
                state="VERIFIED" if policy.home_tenant_id == tenant_id else "FOREIGN_HOME",
                home_tenant_id=policy.home_tenant_id,
                bound_roles=raw,
                effective_roles=list(policy.role_ids),
                excluded_roles=sorted(set(raw) - set(policy.role_ids)),
                ordinary_role_menu=sorted(policy.web_menu),
                identity_admin=policy.is_identity_admin,
            )
        except Exception as exc:
            item.update(state="UNKNOWN", error_type=type(exc).__name__)
        if item.get("state") in {"VERIFIED", "FOREIGN_HOME"}:
            from types import SimpleNamespace

            from bisheng.common.services.config_service import settings
            from bisheng.core.context.tenant import strict_tenant_filter, tenant_execution_scope
            from bisheng.role.domain.services.quota_service import QuotaService

            item["approval_ordinary_labels"] = [f"role_{rid}" for rid in policy.role_ids]
            item["approval_identity_labels"] = "NOT_VERIFIED"
            if policy.home_tenant_id != tenant_id:
                item["resource_budget"] = "OWNER_MOVED_INCREMENT_REFUSED"
            try:
                with tenant_execution_scope(policy.home_tenant_id), strict_tenant_filter():
                    quotas = await QuotaService.get_all_effective_quotas(
                        uid,
                        policy.home_tenant_id,
                        login_user=SimpleNamespace(is_admin=lambda admin=policy.is_identity_admin: admin),
                    )
                item["quotas"] = {"state": "VERIFIED", "items": [row.model_dump() for row in quotas]}
            except Exception as exc:
                item["quotas"] = {"state": "UNKNOWN", "error_type": type(exc).__name__}
            if settings.dsh.enabled:
                try:
                    from bisheng.dsh.runtime import read_policy

                    with tenant_execution_scope(policy.home_tenant_id), strict_tenant_filter():
                        dsh = await read_policy(uid)
                    item["dsh"] = {"state": "VERIFIED_SQL_ONLY", "policy": dsh.model_dump() if dsh else None}
                except Exception as exc:
                    item["dsh"] = {"state": "UNKNOWN", "error_type": type(exc).__name__}
            else:
                item["dsh"] = {"state": "DISABLED"}
        people.append(item)
    from bisheng.core.context.tenant import strict_tenant_filter, tenant_execution_scope
    from bisheng.permission.application.control_state import SqlPermissionControlState

    try:
        with tenant_execution_scope(tenant_id), strict_tenant_filter():
            snapshots = await SqlPermissionControlState().permission_snapshots(
                tuple((tenant_id, row["type"], row["id"]) for row in report["resources"])
            )
        for row in report["resources"]:
            snapshot = snapshots.get((tenant_id, row["type"], row["id"]))
            row["permission_mirror"] = snapshot.projection_state if snapshot else "MISSING_OR_UNDECIDABLE"
    except Exception as exc:
        report["permission_inventory"] = {"state": "UNKNOWN", "error_type": type(exc).__name__}
    report["fga_verification"] = "NOT_RUN"
    report["people"] = people
    report["read_only"] = True
    report["historical_ready_rows"] = "READY is a migration default, not proof of historical permission completeness"
    return report
