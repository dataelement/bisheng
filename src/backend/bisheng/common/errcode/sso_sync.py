import json

from fastapi import HTTPException
from fastapi.responses import JSONResponse

from .base import BaseErrorCode

# SSO / org-sync realtime module error codes, module code: 193
# Assigned by F014-sso-org-realtime-sync and shared with F015-ldap-reconcile-celery (v2.5.1).
# Covers HMAC-authenticated Gateway callbacks for SSO login + bulk department sync.


class SsoHmacInvalidError(BaseErrorCode):
    Code: int = 19301
    Msg: str = "HMAC signature missing or invalid; reject request"


class SsoDeptMountConflictError(BaseErrorCode):
    Code: int = 19302
    Msg: str = (
        "tenant_mapping cannot mount department: parent chain already carries "
        "a mount point (INV-T1: only 2-level tenant tree is supported)"
    )


class SsoTenantDisabledError(BaseErrorCode):
    Code: int = 19303
    Msg: str = "Leaf tenant is not active (disabled/archived/orphaned); login blocked"


class SsoCrossSourceUserError(BaseErrorCode):
    Code: int = 19304
    Msg: str = "Existing user with conflicting source cannot be reused for SSO"


class SsoTsConflictSkippedError(BaseErrorCode):
    Code: int = 19310
    Msg: str = "Incoming ts is older than last_sync_ts; operation skipped (INV-T12)"


class SsoUserLockBusyError(BaseErrorCode):
    Code: int = 19311
    Msg: str = "Another SSO login for the same external_user_id is in progress"


class SsoDeptParentMissingError(BaseErrorCode):
    Code: int = 19312
    Msg: str = (
        "Department parent chain missing in bisheng; Gateway must push parents "
        "via /api/v1/departments/sync before login-sync"
    )


class SsoPrimaryDeptMissingError(BaseErrorCode):
    Code: int = 19313
    Msg: str = "primary_dept_external_id is required for SSO login-sync"


# ---------------------------------------------------------------------------
# F015-ldap-reconcile-celery (shared module MMM=193)
# ---------------------------------------------------------------------------


class SsoReconcileLockBusyError(BaseErrorCode):
    Code: int = 19314
    Msg: str = (
        "Another reconcile run for the same org_sync_config is in progress; skip this trigger (Redis SETNX lock busy)"
    )


class SsoRelinkStrategyUnsupportedError(BaseErrorCode):
    Code: int = 19315
    Msg: str = "Unknown relink matching_strategy; expected external_id_map or path_plus_name"


class SsoRelinkConflictUnresolvedError(BaseErrorCode):
    Code: int = 19316
    Msg: str = "relink conflict candidate list is empty or the chosen new_external_id is not among stored candidates"


class SsoSameTsRemoveAppliedWarnError(BaseErrorCode):
    Code: int = 19317
    Msg: str = (
        "Same-ts upsert/remove collision resolved by applying remove (INV-T12 AC-11); audit_log written, admin notified"
    )


class SsoReconcileReservedError(BaseErrorCode):
    Code: int = 19318
    Msg: str = "Reserved for future reconcile error paths"


# 新昆联分支显式采用真实 HTTP 状态。不改变旧错误处理。
class KunlianError(BaseErrorCode):
    http_status: int
    reason_code: str

    def __str__(self):
        return self.Msg

    @classmethod
    def return_resp(cls, msg=None, data=None):
        return super().return_resp(msg=cls.Msg, data={"reason_code": cls.reason_code})

    @classmethod
    def http_exception(cls, msg=None):
        return HTTPException(status_code=cls.http_status, detail={"reason_code": cls.reason_code})

    def to_response(self):
        return JSONResponse(status_code=self.http_status, content=self.to_dict())

    def to_json_str(self, data=None):
        return json.dumps(self.to_dict(), ensure_ascii=False)

    def to_sse_event_instance(self, event="error", data=None):
        return self.to_sse_event(event=event, data={"reason_code": self.reason_code})

    def to_sse_event_instance_str(self, event="error", data=None):
        return f"event: {event}\ndata: {self.to_json_str()}\n\n"

    def to_dict(self, data=None) -> dict:
        return {"status_code": self.Code, "status_message": self.Msg, "data": {"reason_code": self.reason_code}}

    def return_resp_instance(self, data=None):
        return self.return_resp(data={"reason_code": self.reason_code})


class KunlianLoginInvalidError(KunlianError):
    Code: int = 19320
    Msg: str = "Login verification failed. Sign in again."
    http_status: int = 400
    reason_code: str = "LOGIN_INVALID"


class KunlianDirectoryNotReadyError(KunlianError):
    Code: int = 19321
    Msg: str = "The directory is not ready. Sign in again after synchronization."
    http_status: int = 409
    reason_code: str = "DIRECTORY_NOT_READY"


class KunlianIdentityUnavailableError(KunlianError):
    Code: int = 19322
    Msg: str = "The current identity or tenant is unavailable."
    http_status: int = 403
    reason_code: str = "IDENTITY_UNAVAILABLE"


class KunlianSessionExpiredError(KunlianError):
    Code: int = 19323
    Msg: str = "Your session has expired. Sign in again."
    http_status: int = 401
    reason_code: str = "SESSION_EXPIRED"


class KunlianDependencyUnavailableError(KunlianError):
    Code: int = 19324
    Msg: str = "Identity verification is unavailable. Try again later."
    http_status: int = 503
    reason_code: str = "DEPENDENCY_UNAVAILABLE"


class KunlianDirectorySyncError(KunlianError):
    Code: int = 19325
    Msg: str = "Directory synchronization failed. Contact your administrator."
    http_status: int = 502
    reason_code: str = "DIRECTORY_SYNC_FAILED"


class KunlianSyncConflictError(KunlianError):
    Code: int = 19326
    Msg: str = "Synchronization is running or its state has changed. Refresh and try again."
    http_status: int = 409
    reason_code: str = "SYNC_CONFLICT"


class KunlianBindingConflictError(KunlianError):
    Code: int = 19327
    Msg: str = "Identity or tenant mapping conflict. Contact your administrator."
    http_status: int = 409
    reason_code: str = "BINDING_CONFLICT"


class KunlianTrustRejectedError(KunlianError):
    Code: int = 19328
    Msg: str = "Request verification failed. Start the operation again."
    http_status: int = 403
    reason_code: str = "TRUST_REJECTED"


class KunlianLogoutIncompleteError(KunlianError):
    Code: int = 19329
    Msg: str = "Signed out of BiSheng. Kunlian sign-out is incomplete."
    http_status: int = 502
    reason_code: str = "LOGOUT_INCOMPLETE"
