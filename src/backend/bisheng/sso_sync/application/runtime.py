"""进程内客户端装配。权威状态仍在 SQL/Redis。不在本地缓存允许结果。"""

import asyncio
import hashlib
import os
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

from cryptography.fernet import Fernet
from pydantic import SecretStr

from bisheng.common.errcode.sso_sync import KunlianDependencyUnavailableError
from bisheng.role.application.external_basic_role import ExternalBasicRoleApplication, RoleExternalBasicRoleRepository
from bisheng.sso_sync.application.browser import KunlianBrowserApplication
from bisheng.sso_sync.application.kunlian import (
    KunlianApiBindings,
    KunlianDirectoryApplication,
    KunlianLoginApplication,
    KunlianLogoutApplication,
    KunlianManagementApplication,
    KunlianSessionApplication,
)
from bisheng.sso_sync.domain.clients.kunlian import KunlianOidcClient
from bisheng.sso_sync.domain.repositories.kunlian import KunlianDirectoryRepository
from bisheng.sso_sync.domain.services.kunlian_directory import DirectoryCredential, KunlianDirectoryService
from bisheng.sso_sync.domain.services.kunlian_login import (
    KunlianInternalTrust,
    KunlianLoginService,
    reserve_internal_nonce,
)
from bisheng.sso_sync.domain.services.kunlian_logout import KunlianLogoutService
from bisheng.sso_sync.domain.services.kunlian_onboarding import KunlianOnboardingService
from bisheng.sso_sync.domain.services.kunlian_projection import KunlianProjectionService
from bisheng.sso_sync.domain.services.kunlian_session import KunlianSessionService
from bisheng.tenant.application.external_membership import (
    ExternalMembershipRepository,
    KunlianExternalMembershipApplication,
)
from bisheng.tenant.application.external_provision import (
    KunlianExternalTenantApplication,
    TenantExternalProvisionRepository,
)
from bisheng.user.application.external_basic_access import (
    ExternalBasicAccessApplication,
    UserExternalBasicAccessRepository,
)
from bisheng.user.application.external_identity import (
    KunlianExternalIdentityApplication,
    UserExternalIdentityProjectionRepository,
)


def resolve_environment_secret(reference: str) -> SecretStr:
    """仅解析运维显式登记的环境变量引用。不把引用当明文或路径读取。"""
    if not reference.startswith("env:") or re.fullmatch(r"[A-Z_][A-Z0-9_]{0,127}", reference[4:]) is None:
        raise LookupError("SECRET_REFERENCE_UNAVAILABLE")
    value = os.environ.get(reference[4:])
    if not value:
        raise LookupError("SECRET_REFERENCE_UNAVAILABLE")
    return SecretStr(value)


@dataclass(frozen=True)
class KunlianWorkerServices:
    config: object
    directory: KunlianDirectoryService
    projection: KunlianProjectionService
    onboarding: KunlianOnboardingService | None = None


class KunlianRuntimeProvider:
    def __init__(self, *, secret_resolver=resolve_environment_secret):
        self.secret_resolver = secret_resolver
        self._lock = asyncio.Lock()
        self._key = None
        self._idp = None
        self._bindings = None
        self._browser = None
        self.directory_service = None
        self._worker_services = None

    async def _load(self):
        from bisheng.common.services.config_service import settings
        from bisheng.user.domain.services.auth import AuthJwt

        config = settings.sso_sync.kunlian.model_copy(deep=True)
        multi_tenant_enabled = settings.multi_tenant.enabled
        references = (
            "client_secret_reference",
            "sync_key_reference",
            "internal_secret_reference",
            "csrf_secret_reference",
            "encryption_secret_reference",
        )
        secrets = {}
        for name in references:
            try:
                secrets[name] = self.secret_resolver(getattr(config, name))
            except (LookupError, ValueError):
                secrets[name] = None
        allow_multi_login = await settings.aget_from_db("allow_multi_login") if config.login_enabled else True
        # 密钥摘要只用于进程内客户端重建。不能输出、持久化或充当业务凭据。
        fingerprint = tuple(
            hashlib.sha256(value.get_secret_value().encode()).digest() if value else None for value in secrets.values()
        )
        key = (config.model_dump_json(), multi_tenant_enabled, allow_multi_login, fingerprint)
        if key == self._key:
            return
        async with self._lock:
            if key == self._key:
                return
            if self._idp is not None:
                await self._idp.__aexit__(None, None, None)
                self._idp = None

            def unavailable_crypto(value):
                raise KunlianDependencyUnavailableError()

            encrypt, decrypt, version = unavailable_crypto, unavailable_crypto, None
            cipher_secret = secrets["encryption_secret_reference"]
            if cipher_secret:
                try:
                    cipher = Fernet(cipher_secret.get_secret_value().encode("ascii"))
                except (ValueError, UnicodeError):
                    cipher_secret = None
                else:
                    version = "f118-" + hashlib.sha256(cipher_secret.get_secret_value().encode()).hexdigest()[:24]

                    def encrypt(value):
                        return cipher.encrypt(value.encode()).decode("ascii")

                    def decrypt(value):
                        return cipher.decrypt(value.encode()).decode()

            repository = KunlianDirectoryRepository(encrypt_value=encrypt, decrypt_value=decrypt, key_version=version)
            user_owner = KunlianExternalIdentityApplication(UserExternalIdentityProjectionRepository())
            tenant_owner = KunlianExternalMembershipApplication(ExternalMembershipRepository())
            projection = KunlianProjectionService(repository, user_owner=user_owner, tenant_owner=tenant_owner)
            role_owner = ExternalBasicRoleApplication(RoleExternalBasicRoleRepository())
            onboarding = KunlianOnboardingService(
                repository,
                config,
                tenants=KunlianExternalTenantApplication(TenantExternalProvisionRepository()),
                users=user_owner,
                roles=role_owner,
                access=ExternalBasicAccessApplication(UserExternalBasicAccessRepository(role_port=role_owner)),
                projection=projection,
                multi_tenant_enabled=multi_tenant_enabled,
            )

            def directory_credential(reference):
                if cipher_secret is None:
                    raise LookupError("ENCRYPTION_KEY_UNAVAILABLE")
                value = self.secret_resolver(reference)
                return DirectoryCredential(hashlib.sha256(value.get_secret_value().encode()).hexdigest(), value)

            def secret_readiness():
                reasons = [
                    name.removesuffix("_reference").upper() + "_UNAVAILABLE"
                    for name, value in secrets.items()
                    if not value
                ]
                if cipher_secret is None:
                    reasons.append("ENCRYPTION_KEY_UNAVAILABLE")
                distinct = [value.get_secret_value() for value in secrets.values() if value]
                if len(set(distinct)) != len(distinct):
                    reasons.append("SECRET_SEPARATION_INVALID")
                return tuple(reasons)

            directory = KunlianDirectoryService(
                repository,
                config,
                credential_resolver=directory_credential,
                encrypt_cursor=encrypt,
                decrypt_cursor=decrypt,
                readiness_probe=secret_readiness,
            )
            sessions = login = None
            protocol = None
            # 本地协议不依赖登录开关、目录、OIDC secret 或外部网络。只核验原会话绑定。
            try:
                origin = urlsplit(config.public_origin)
            except ValueError:
                # 非法登记不能启用协议。管理就绪诊断仍由配置模型报告。
                origin = urlsplit("")
            distinct = [value.get_secret_value() for value in secrets.values() if value]
            protocol_ready = (
                config.connection_id
                and config.issuer
                and config.client_id
                and origin.hostname
                and not origin.username
                and not origin.password
                and not origin.path
                and not origin.query
                and not origin.fragment
                and (
                    origin.scheme == "https"
                    or (origin.scheme == "http" and config.public_origin in config.approved_test_origins)
                )
                and secrets["csrf_secret_reference"]
                and len(set(distinct)) == len(distinct)
            )
            if protocol_ready:
                local_sessions = KunlianSessionService(
                    repository,
                    config,
                    idp_client=None,
                    user_owner=None,
                    tenant_owner=None,
                    multi_tenant_enabled=multi_tenant_enabled,
                    csrf_secret=secrets["csrf_secret_reference"],
                )
                protocol_trust = None
                if (
                    re.fullmatch(r"[A-Za-z0-9._-]{1,64}", config.internal_key_id)
                    and secrets["internal_secret_reference"]
                ):
                    protocol_trust = KunlianInternalTrust(
                        key_id=config.internal_key_id,
                        secret=secrets["internal_secret_reference"],
                        reserve_nonce=reserve_internal_nonce,
                    )
                protocol = KunlianLogoutApplication(
                    KunlianLogoutService(repository, config, sessions=local_sessions, trust=protocol_trust)
                )
            if not config.readiness_reasons(multi_tenant_enabled=multi_tenant_enabled) and not secret_readiness():
                self._idp = KunlianOidcClient(config, client_secret=secrets["client_secret_reference"])
                sessions = KunlianSessionApplication(
                    KunlianSessionService(
                        repository,
                        config,
                        idp_client=self._idp,
                        user_owner=user_owner,
                        tenant_owner=tenant_owner,
                        multi_tenant_enabled=multi_tenant_enabled,
                        csrf_secret=secrets["csrf_secret_reference"],
                        onboarding=onboarding,
                    )
                )
                trust = KunlianInternalTrust(
                    key_id=config.internal_key_id,
                    secret=secrets["internal_secret_reference"],
                    reserve_nonce=reserve_internal_nonce,
                )
                login = KunlianLoginApplication(
                    KunlianLoginService(
                        repository,
                        config,
                        trust=trust,
                        idp_client=self._idp,
                        directory=KunlianDirectoryApplication(directory),
                        user_owner=user_owner,
                        tenant_owner=tenant_owner,
                        signer_factory=AuthJwt,
                        multi_tenant_enabled=multi_tenant_enabled,
                        allow_multi_login=allow_multi_login is True,
                        onboarding=onboarding,
                    )
                )
            self.directory_service = directory
            self._worker_services = KunlianWorkerServices(
                config,
                directory,
                projection,
                onboarding,
            )
            self._browser = KunlianBrowserApplication(
                config=config, repository=repository, user_owner=user_owner, sessions=sessions, protocol=protocol
            )
            self._bindings = KunlianApiBindings(
                config=config,
                login=login,
                protocol=protocol,
                management=KunlianManagementApplication(
                    directory,
                    user_owner=user_owner,
                    tenant_owner=tenant_owner,
                    multi_tenant_enabled=multi_tenant_enabled,
                ),
            )
            self._key = key

    async def api_bindings(self):
        await self._load()
        return self._bindings

    async def browser_application(self):
        await self._load()
        return self._browser

    async def worker_services(self):
        await self._load()
        return self._worker_services

    async def aclose(self):
        async with self._lock:
            if self._idp is not None:
                await self._idp.__aexit__(None, None, None)
            self._idp = self._key = self._bindings = self._browser = self.directory_service = None
            self._worker_services = None


def get_runtime_provider(app):
    provider = getattr(app.state, "kunlian_runtime_provider", None)
    if provider is None:
        provider = KunlianRuntimeProvider()
        app.state.kunlian_runtime_provider = provider
    return provider
