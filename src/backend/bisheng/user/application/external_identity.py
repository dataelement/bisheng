"""用户 Owner 对外投影协议。只传命令与回执。不传 ORM。"""

from dataclasses import replace

from pydantic import BaseModel, ConfigDict, SecretStr

from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.user.domain.repositories.external_identity_projection import (
    CurrentExternalAccount,
    ExternalShadowIdentity,
    ExternalShadowOperation,
    ExternalShadowReceipt,
    UserExternalIdentityProjectionRepository,
)

__all__ = [
    "CurrentExternalAccount",
    "ExternalShadowIdentity",
    "ExternalShadowOperation",
    "ExternalShadowReceipt",
    "KunlianExternalIdentityApplication",
    "UserExternalIdentityProjectionRepository",
]


class KunlianUserPayload(UserPayload):
    """已读取当前资格后的固定主体。禁止回退到构造函数中的角色查询。"""

    model_config = ConfigDict(frozen=True)
    auth_source: str = "kunlian"

    def __init__(self, **data):
        BaseModel.__init__(self, **data)


async def check_current_global_super(user_id: int, role_ids: tuple[int, ...]) -> bool:
    from bisheng.database.constants import AdminRole
    from bisheng.permission.application import PermissionObject, PermissionSubject, get_permission_relation_api

    if AdminRole in role_ids:
        return True
    permissions = await get_permission_relation_api()
    return await permissions.check(
        subject=PermissionSubject("user", str(user_id)),
        relation="super_admin",
        resource=PermissionObject("system", "global"),
        consistency="HIGHER_CONSISTENCY",
    )


class KunlianExternalIdentityApplication:
    def __init__(self, repository: UserExternalIdentityProjectionRepository, *, global_super_checker=None):
        self.repository = repository
        self.global_super_checker = global_super_checker or check_current_global_super

    async def require_current_global_super(self, user_id: int) -> None:
        from bisheng.common.errcode.sso_sync import KunlianIdentityUnavailableError

        roles = await self.repository.read_control_plane_actor_roles(user_id)
        if not await self.global_super_checker(user_id, roles):
            raise KunlianIdentityUnavailableError()

    async def is_reserved_external_account(self, user_id: int) -> bool:
        return await self.repository.is_reserved_external_account(user_id)

    async def read_current_qualification(self, user_id: int, *, identity_key: str) -> CurrentExternalAccount:
        return await self.repository.read_current_qualification(user_id, identity_key=identity_key)

    async def build_admitted_payload(self, facts: CurrentExternalAccount, *, local_tenant_id: int) -> UserPayload:
        is_global_super = await self.global_super_checker(facts.user_id, facts.role_ids)
        return KunlianUserPayload(
            user_id=facts.user_id,
            user_name=facts.user_name,
            user_role=list(facts.role_ids),
            token_version=facts.token_version,
            tenant_id=local_tenant_id,
            is_global_super=is_global_super,
        )

    async def require_login_access(self, facts: CurrentExternalAccount, *, local_tenant_id: int):
        from bisheng.common.errcode.user import UserNoRoleForLoginError, UserNoWebMenuForLoginError
        from bisheng.core.context.tenant import tenant_execution_scope
        from bisheng.user.domain.services.user import UserService

        with tenant_execution_scope(local_tenant_id):
            refusal = await UserService._reject_login_if_user_has_no_usable_access(facts, role_ids=facts.role_ids)
        if refusal is not None:
            if refusal.status_code == UserNoRoleForLoginError.Code:
                raise UserNoRoleForLoginError()
            raise UserNoWebMenuForLoginError()

    async def issue_kunlian_token(self, signing_context: dict, reference, *, identity_key: str, signer) -> SecretStr:
        from bisheng.common.errcode.sso_sync import KunlianSessionExpiredError
        from bisheng.user.domain.services.auth import LoginUser

        current = await self.read_current_qualification(signing_context["user_id"], identity_key=identity_key)
        if current.token_version != signing_context["token_version"]:
            raise KunlianSessionExpiredError()
        fixed = replace(current, user_name=signing_context["user_name"])
        token = LoginUser.create_access_token(
            fixed,
            signer,
            tenant_id=signing_context["tenant_id"],
            token_version=signing_context["token_version"],
            auth_source="kunlian",
            kunlian_session=reference,
            issued_at=signing_context["iat"],
            absolute_expires_at=signing_context["exp"],
        )
        return SecretStr(token)

    async def reserve_external_shadow(
        self, identity: ExternalShadowIdentity, source_revision: str
    ) -> ExternalShadowOperation:
        return await self.repository.reserve(identity, source_revision)

    async def ensure_external_shadow(
        self, identity: ExternalShadowIdentity, expected_revision: str, *, operation: ExternalShadowOperation
    ) -> int:
        return await self.repository.ensure_shadow(identity, expected_revision, operation=operation)

    async def read_projection_receipt(self, operation: ExternalShadowOperation) -> ExternalShadowReceipt:
        return await self.repository.read_receipt(operation)

    async def reserve_manual_status(
        self, user_id: int, *, identity_key: str, source_revision: str, disabled: bool, source_active: bool
    ):
        return await self.repository.reserve_manual_status(
            user_id,
            identity_key=identity_key,
            source_revision=source_revision,
            disabled=disabled,
            source_active=source_active,
        )

    async def set_manual_status(
        self,
        user_id: int,
        *,
        identity_key: str,
        disabled: bool,
        source_active: bool,
        operation: ExternalShadowOperation,
    ):
        await self.repository.set_manual_status(
            user_id, identity_key=identity_key, disabled=disabled, source_active=source_active, operation=operation
        )
