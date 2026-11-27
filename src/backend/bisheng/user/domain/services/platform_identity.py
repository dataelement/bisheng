"""Normalize verified platform identity without changing management-scope semantics."""

from bisheng.core.session_activity import AuthenticatedActivity
from bisheng.user.domain.services.platform_transport import access_credential
from bisheng.user.platform_auth_runtime import get_platform_auth


class PlatformActivity(AuthenticatedActivity):
    def __init__(self, service, token):
        self.service, self.token = service, token

    async def record(self):
        await self.service.activity(self.token)

    def policy_for(self, endpoint):
        return getattr(endpoint, "__platform_session_activity_policy__", None) or super().policy_for(endpoint)


async def authenticate_platform(connection, *, identity_class=None, token=None):
    from bisheng.user.domain.services.auth import LoginUser

    service = get_platform_auth(connection)
    token = token or access_credential(connection)
    data = await service.inspect(token)
    claims = service.decode(token)
    cls = identity_class or LoginUser
    user = await cls.init_login_user(
        user_id=int(claims["sub"]),
        user_name=data["user"]["user_name"],
        tenant_id=int(claims["tenant_id"]),
        token_version=claims["token_version"],
        **({"require_current_super": True} if getattr(connection.state, "require_current_super", False) else {}),
    )
    user._runtime_credential_reference = {
        "kind": "platform_session",
        "session_id": claims["session_id"],
        "session_version": claims["session_version"],
        "user_id": int(claims["sub"]),
        "tenant_id": int(claims["tenant_id"]),
        "token_version": claims["token_version"],
        "expires_at": data["access_expires_at"],
    }
    connection.state.authenticated_activity = PlatformActivity(service, token)
    return user


def is_platform_token(token):
    import jwt

    try:
        return jwt.get_unverified_header(token).get("typ") == "bisheng-platform-access+jwt"
    except (jwt.PyJWTError, TypeError):
        return False
