from .base import BaseErrorCode


# Tenant tree module error codes, module code: 220
# Assigned by F011-tenant-tree-model (v2.5.1). The spec originally planned
# module code 190 but that range was already occupied by permission (F004
# 19000~19005), so F011 was reassigned to 220 on 2026-04-19.


class TenantTreeNestingForbiddenError(BaseErrorCode):
    Code: int = 22001
    Msg: str = 'MVP locked to 2-layer tree; cannot mount a tenant under a child tenant'


class TenantTreeMountConflictError(BaseErrorCode):
    Code: int = 22002
    Msg: str = 'Target department is already a mount point or lies under one'


class TenantTreeRootDeptMountError(BaseErrorCode):
    Code: int = 22003
    Msg: str = 'Root department cannot be mounted as a child tenant'


class TenantTreeInvalidParentError(BaseErrorCode):
    Code: int = 22004
    Msg: str = 'Invalid parent tenant: parent does not exist or is not root'


class TenantTreeHasChildrenError(BaseErrorCode):
    Code: int = 22005
    Msg: str = 'Cannot physically delete a tenant that has child tenants'


class TenantTreeMigrateConflictError(BaseErrorCode):
    Code: int = 22006
    Msg: str = 'tenant_id conflict while migrating child tenant resources'


class TenantTreeOrphanAlreadyExistsError(BaseErrorCode):
    Code: int = 22007
    Msg: str = 'Orphaned tenant already exists for this department'


class TenantTreeRootProtectedError(BaseErrorCode):
    Code: int = 22008
    Msg: str = 'Root tenant is system-protected; disable/archive/delete forbidden'


class TenantTreeAuditLogWriteError(BaseErrorCode):
    Code: int = 22009
    Msg: str = 'Failed to write audit_log entry'


class TenantTreeMigratePermissionError(BaseErrorCode):
    Code: int = 22010
    Msg: str = 'Only global super admin may call migrate-from-root'


class TenantTreeMigrateSourceError(BaseErrorCode):
    Code: int = 22011
    Msg: str = 'migrate-from-root requires resource.tenant_id == 1 (Root)'
