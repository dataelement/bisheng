"""Prove an explicit IAM deletion and freeze its complete bounded cleanup effects."""


class IamArchiveDepartmentService:
    def __init__(self, repository, role_repository):
        self.repository, self.role_repository = repository, role_repository

    async def prove(self, department, source, evidence, fingerprint, *, session, lock=False):
        if department["status"] not in {"active", "archived"} or department["deleted"] not in (0, 1):
            raise ValueError("ARCHIVE_LIFECYCLE_UNPROVEN")
        if department["status"] == "active" and department["deleted"]:
            raise ValueError("ARCHIVE_LIFECYCLE_CONFLICT")
        if (
            department["parent_id"] is None
            or department["is_tenant_root"]
            or department["mounted_tenant_id"] is not None
        ):
            raise ValueError("ARCHIVE_MOUNT_NOT_SUPPORTED")
        if (
            source["id"] != department["id"]
            or source["tenant_id"] != department["tenant_id"]
            or evidence
            != {"id": source["external_id"], "http_status": 200, "errcode": "1", "errmsg": "部门不存在\uff01"}
        ):
            raise ValueError("ARCHIVE_IAM_DELETION_NOT_PROVEN")
        if not department["path"].startswith("/") or not department["path"].endswith(f"/{department['id']}/"):
            raise ValueError("ARCHIVE_UNSAFE_PATH")
        await self.repository.require_leaf(department, session=session)
        associations, last_sync_ts = await self.repository.archive_snapshot(
            department, self.role_repository, session=session, lock=lock
        )
        if any(row["grant_source"] not in {"sso", "manual"} for row in associations["admins"]):
            raise ValueError("ARCHIVE_ADMIN_SOURCE_UNPROVEN")
        target = department | {"status": "archived", "deleted": 1}
        fields = ("id", "tenant_id", "parent_id", "path", "status", "deleted", "is_tenant_root", "mounted_tenant_id")
        proof = {
            "department": {key: target[key] for key in fields},
            "direct_members": [],
            "ancestors": [],
            "mounts": [],
            "iam_archive": {
                "local_identity": source,
                "evidence": evidence,
                "source_fingerprint": fingerprint,
                "last_sync_ts": last_sync_ts,
            },
        }
        return proof, {
            "kind": "archive",
            "source": source,
            "target": target,
            "before": associations,
            "last_sync_ts": last_sync_ts,
        }
