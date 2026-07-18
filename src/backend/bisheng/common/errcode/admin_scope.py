from .base import BaseErrorCode


# Admin-scope module error codes, module code: 197
# Assigned by F019-admin-tenant-scope (v2.5.1). Covers the global super admin's
# management-view switch backed by Redis `admin_scope:{user_id}` (INV-T14).
# Non-super-admins calling the API are rejected by 19701; invalid target tenant
# ids (not in `tenant` table) are rejected by 19702 before Redis is touched.


class AdminScopeForbiddenError(BaseErrorCode):
    Code: int = 19701
    Msg: str = (
        'Only the global super admin may set an admin tenant-scope '
        '(INV-T14); caller is not a super admin'
    )


class AdminScopeTenantNotFoundError(BaseErrorCode):
    Code: int = 19702
    Msg: str = 'Target tenant for admin scope does not exist'
