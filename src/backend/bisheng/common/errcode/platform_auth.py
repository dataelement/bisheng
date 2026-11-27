"""Platform authentication errors with stable HTTP and application contracts."""

from bisheng.common.errcode.base import BaseErrorCode


class PlatformAuthError(BaseErrorCode):
    Code = 10650
    Msg = "invalid_access_token"

    def __init__(self, reason="invalid_access_token", **details):
        reasons = [
            "invalid_access_token",
            "access_expired",
            "invalid_refresh_token",
            "refresh_token_reused",
            "session_expired",
            "session_revoked",
            "legacy_web_token_rejected",
            "web_bootstrap_required",
            "web_bootstrap_expired",
            "auth_service_unavailable",
            "csrf_rejected",
            "credential_conflict",
            "client_upgrade_required",
            "invalid_auth_request",
            "web_binding_completed",
        ]
        self.reason = reason
        self.http_status = {
            "web_bootstrap_required": 409,
            "web_binding_completed": 409,
            "auth_service_unavailable": 503,
            "csrf_rejected": 403,
            "credential_conflict": 400,
            "client_upgrade_required": 426,
            "invalid_auth_request": 400,
        }.get(reason, 401)
        self.details = details
        super().__init__(msg=reason, code=10650 + reasons.index(reason))

    def payload(self):
        data = {"auth_reason": self.reason, "retryable": self.http_status == 503, **self.details}
        payload = self.to_dict(data)
        if self.reason == "client_upgrade_required":
            payload["status_message"] = "当前客户端版本不受支持, 请升级客户端后重新登录"
            payload["message"] = payload["status_message"]
        return payload
