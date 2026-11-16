"""Validate business department facts without deciding resource access."""


class DepartmentRecoveryService:
    def __init__(self, repository):
        self.repository = repository

    async def prove(self, department, expected_parent, *, session=None, lock=False):
        if not department or department["status"] != "active" or department["deleted"]:
            raise ValueError("DEPARTMENT_INACTIVE")
        if department["parent_id"] != expected_parent:
            raise ValueError("BUSINESS_PARENT_CHANGED")
        ancestors = await self.repository.ancestors(department, session=session, lock=lock)
        chain = [*list(reversed(ancestors)), department]
        path = "/"
        allowed_tenants = {chain[0]["tenant_id"]}
        for item in chain:
            if item["status"] != "active" or item["deleted"]:
                raise ValueError("ANCESTOR_INACTIVE")
            path += f"{item['id']}/"
            if item["path"] != path:
                raise ValueError("BUSINESS_PATH_INVALID")
            if item["is_tenant_root"]:
                if not item["mounted_tenant_id"]:
                    raise ValueError("MOUNT_BINDING_INVALID")
                allowed_tenants.add(item["mounted_tenant_id"])
            elif item["mounted_tenant_id"] is not None:
                raise ValueError("MOUNT_BINDING_INVALID")
            if item["tenant_id"] not in allowed_tenants:
                raise ValueError("UNEXPLAINED_TENANT_BOUNDARY")
        mounts = await self.repository.mount_facts(department, ancestors, session=session, lock=lock)
        fields = ("id", "tenant_id", "parent_id", "path", "status", "deleted", "is_tenant_root", "mounted_tenant_id")
        return {
            "department": {key: department[key] for key in fields},
            "ancestors": [{key: item[key] for key in fields} for item in ancestors],
            "mounts": mounts,
        }
