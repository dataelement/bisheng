"""Owner validation of IAM facts for this scan's business-blocked departments."""

from bisheng.department.domain.services.current_projection_repair import (
    CurrentDepartmentRepairService,
    DepartmentRepairBusinessError,
)


class IamOneoffDepartmentService:
    def __init__(self, repository):
        self.repository = repository
        self.current = CurrentDepartmentRepairService(repository)

    async def prove(
        self,
        department,
        source,
        iam_department,
        iam_parent,
        iam_source,
        *,
        session=None,
        lock=False,
        require_current=True,
    ):
        if (
            department["status"] != "active"
            or department["deleted"]
            or department["is_tenant_root"]
            or department["mounted_tenant_id"]
        ):
            raise ValueError("IAM_ONEOFF_LIFECYCLE_OR_MOUNT_CONFLICT")
        if (
            source["id"] != department["id"]
            or source["tenant_id"] != department["tenant_id"]
            or not source["source"]
            or not source["external_id"]
            or iam_department["id"] != source["external_id"]
            or iam_department["enable"] != 1
            or iam_department["parentid"] != iam_parent["id"]
            or iam_parent["enable"] != 1
        ):
            raise ValueError("IAM_ONEOFF_IDENTITY_OR_ENABLE_CONFLICT")
        parent = await self.repository.parent_by_external(
            source["source"], iam_parent["id"], session=session, lock=lock
        )
        if parent["id"] == department["id"] or parent["tenant_id"] != department["tenant_id"]:
            raise ValueError("IAM_ONEOFF_CYCLE_OR_TENANT_CONFLICT")
        target = department | {"parent_id": parent["id"], "path": f"{parent['path']}{department['id']}/"}
        proof = await self.current.prove(target, session=session, lock=lock)
        ancestors = await self.repository.ancestors(target, session=session, lock=lock)
        if require_current and any(row["state"] != "CURRENT" for row in ancestors):
            raise ValueError("IAM_PARENT_ANCESTRY_NOT_CURRENT")
        if any(row["is_tenant_root"] or row["mounted_tenant_id"] is not None for row in [department, *ancestors]):
            raise ValueError("IAM_ONEOFF_MOUNT_NOT_SUPPORTED")
        if not department["path"].startswith("/") or not department["path"].endswith(f"/{department['id']}/"):
            raise ValueError("IAM_ONEOFF_OLD_PATH_INVALID")
        await self.repository.require_leaf(department, session=session)
        # Same business proof is reproducible after the T1 reparent commit.
        proof["iam"] = {
            "source_fingerprint": iam_source,
            "local_identity": source,
            "department": iam_department,
            "parent": iam_parent,
        }
        reparent = None
        if department["parent_id"] != target["parent_id"] or department["path"] != target["path"]:
            reparent = {"source": source, "target": target}
        return proof, reparent

    async def prove_inactive(self, department, *, session=None, lock=False):
        """A closed lifecycle can reconcile its owned tuples without revival."""
        if department["status"] != "archived" or department["deleted"] not in (0, 1):
            raise ValueError("INACTIVE_LIFECYCLE_UNPROVEN")
        if department["is_tenant_root"] or department["mounted_tenant_id"] is not None:
            raise ValueError("INACTIVE_MOUNT_REQUIRES_OWNER")
        members = await self.repository.members(department["id"], session=session, lock=lock)
        if members:
            raise DepartmentRepairBusinessError(
                "INACTIVE_DEPARTMENT_HAS_MEMBERS_REQUIRES_DISPOSITION",
                {"department": department, "direct_member_count": len(members)},
            )
        fields = ("id", "tenant_id", "parent_id", "path", "status", "deleted", "is_tenant_root", "mounted_tenant_id")
        return {
            "department": {key: department[key] for key in fields},
            "direct_members": [],
            "ancestors": [],
            "mounts": [],
            "inactive_cleanup": True,
        }, None
