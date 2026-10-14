"""Business rules for assistant-bound E+ robot configuration."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.core.context.tenant import current_tenant_id
from bisheng.eplus.domain.models.eplus import EPlusBotConfig, EPlusBotSpace
from bisheng.eplus.domain.schemas.config import AssistantSnapshot, EPlusBotConfigUpsert
from bisheng.eplus.domain.services.bot_config_service import EPlusBotConfigService
from bisheng.eplus.infrastructure.credential_store import MinioCertificateStore

TENANT_ID = 73


class FakePermissionChecker:
    def __init__(self) -> None:
        self.calls: list[tuple[int, str, int, str]] = []

    async def require_assistant_edit(self, *, tenant_id: int, assistant_id: str, operator_id: int, action: str) -> None:
        self.calls.append((tenant_id, assistant_id, operator_id, action))


class FakeAssistantReader:
    def __init__(self) -> None:
        self.online = True

    async def get_assistant(self, *, tenant_id: int, assistant_id: str) -> AssistantSnapshot | None:
        return AssistantSnapshot(
            assistant_id=assistant_id,
            tenant_id=tenant_id,
            is_deleted=False,
            is_online=self.online,
        )


class FakeSpaceReader:
    def __init__(self, valid_ids: set[int]) -> None:
        self.valid_ids = valid_ids
        self.calls: list[tuple[int, tuple[int, ...]]] = []

    async def require_valid_spaces(self, *, tenant_id: int, space_ids: tuple[int, ...]) -> None:
        self.calls.append((tenant_id, space_ids))
        invalid = set(space_ids) - self.valid_ids
        if invalid:
            raise ValueError(f"invalid spaces: {sorted(invalid)}")


class FakeCredentialStore:
    def encrypt(self, secret: str) -> str:
        return f"encrypted:{secret}"

    def decrypt(self, ciphertext: str) -> str:
        return ciphertext.removeprefix("encrypted:")


class FakeCertificateStore:
    async def put_ca(self, pem: bytes) -> tuple[str, str]:
        digest = hashes.Hash(hashes.SHA256())
        digest.update(pem)
        sha256 = digest.finalize().hex()
        return f"eplus/ca/{sha256}.pem", sha256


class FakeNotifier:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.events: list[dict[str, int]] = []

    async def config_changed(self, event: dict[str, int]) -> None:
        if self.fail:
            raise RuntimeError("redis unavailable")
        self.events.append(event)


class FakeMinio:
    bucket = "bisheng"

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def put_object(self, *, object_name: str, file: bytes, content_type: str, bucket_name=None) -> None:
        self.objects[object_name] = file


@pytest_asyncio.fixture(autouse=True)
async def tenant_context() -> AsyncIterator[None]:
    token = current_tenant_id.set(TENANT_ID)
    try:
        yield
    finally:
        current_tenant_id.reset(token)


@pytest_asyncio.fixture
async def engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(
            lambda conn: SQLModel.metadata.create_all(
                conn,
                tables=[EPlusBotConfig.__table__, EPlusBotSpace.__table__],
            )
        )
    yield engine
    await engine.dispose()


def _request(**overrides) -> EPlusBotConfigUpsert:
    values = {
        "bot_id": "bot-1",
        "connection_url": "wss://eplus.example.test/im_openws?bizid=1",
        "secret": "plain-secret",
        "media_hosts": ["media.example.test"],
        "space_ids": [20, 10],
        "enabled": True,
    }
    values.update(overrides)
    return EPlusBotConfigUpsert(**values)


def _service(session: AsyncSession, *, notifier_fail: bool = False):
    permission = FakePermissionChecker()
    assistant = FakeAssistantReader()
    spaces = FakeSpaceReader({10, 20, 30})
    notifier = FakeNotifier(fail=notifier_fail)
    service = EPlusBotConfigService(
        session,
        permission_checker=permission,
        assistant_reader=assistant,
        space_reader=spaces,
        credential_store=FakeCredentialStore(),
        certificate_store=FakeCertificateStore(),
        notifier=notifier,
    )
    return service, permission, assistant, spaces, notifier


async def test_save_uses_only_assistant_edit_and_never_exposes_secret(engine: AsyncEngine) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        service, permission, _, spaces, notifier = _service(session)
        view = await service.save_config(
            tenant_id=TENANT_ID,
            assistant_id="assistant-1",
            operator_id=9,
            request=_request(),
        )

    assert permission.calls == [(TENANT_ID, "assistant-1", 9, "edit")]
    assert spaces.calls == [(TENANT_ID, (10, 20))]
    assert view.secret_configured is True
    assert view.space_ids == (10, 20)
    assert "plain-secret" not in repr(view)
    assert notifier.events == [
        {
            "tenant_id": TENANT_ID,
            "bot_config_id": view.id,
            "credential_version": 1,
            "scope_version": 1,
        }
    ]


async def test_secret_and_scope_versions_change_only_for_relevant_edits(engine: AsyncEngine) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        service, *_ = _service(session)
        initial = await service.save_config(
            tenant_id=TENANT_ID,
            assistant_id="assistant-1",
            operator_id=9,
            request=_request(),
        )
        reordered = await service.save_config(
            tenant_id=TENANT_ID,
            assistant_id="assistant-1",
            operator_id=9,
            request=_request(secret=None, space_ids=[10, 20]),
        )
        rotated = await service.save_config(
            tenant_id=TENANT_ID,
            assistant_id="assistant-1",
            operator_id=9,
            request=_request(secret="new-secret", space_ids=[10, 30]),
        )

    assert (initial.credential_version, initial.scope_version) == (1, 1)
    assert (reordered.credential_version, reordered.scope_version) == (1, 1)
    assert (rotated.credential_version, rotated.scope_version) == (2, 2)


async def test_rejects_invalid_spaces_and_duplicate_bot_binding(engine: AsyncEngine) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        service, *_ = _service(session)
        with pytest.raises(ValueError, match="invalid spaces"):
            await service.save_config(
                tenant_id=TENANT_ID,
                assistant_id="assistant-1",
                operator_id=9,
                request=_request(space_ids=[999]),
            )
        await service.save_config(
            tenant_id=TENANT_ID,
            assistant_id="assistant-1",
            operator_id=9,
            request=_request(),
        )
        with pytest.raises(ValueError, match="already bound"):
            await service.save_config(
                tenant_id=TENANT_ID,
                assistant_id="assistant-2",
                operator_id=9,
                request=_request(),
            )


async def test_target_requires_online_enabled_complete_non_deleted_config(engine: AsyncEngine) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        service, _, assistant, _, _ = _service(session)
        view = await service.save_config(
            tenant_id=TENANT_ID,
            assistant_id="assistant-1",
            operator_id=9,
            request=_request(),
        )
        target = await service.resolve_connection_target(tenant_id=TENANT_ID, bot_config_id=view.id)
        assert target is not None
        assert target.secret == "plain-secret"

        assistant.online = False
        assert await service.resolve_connection_target(tenant_id=TENANT_ID, bot_config_id=view.id) is None
        assistant.online = True
        await service.disable_config(
            tenant_id=TENANT_ID,
            assistant_id="assistant-1",
            operator_id=9,
        )
        assert await service.resolve_connection_target(tenant_id=TENANT_ID, bot_config_id=view.id) is None


async def test_notification_failure_does_not_rollback_saved_configuration(engine: AsyncEngine) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        service, *_ = _service(session, notifier_fail=True)
        view = await service.save_config(
            tenant_id=TENANT_ID,
            assistant_id="assistant-1",
            operator_id=9,
            request=_request(),
        )

    async with AsyncSession(engine, expire_on_commit=False) as session:
        saved = (
            await session.exec(
                select(EPlusBotConfig).where(
                    EPlusBotConfig.tenant_id == TENANT_ID,
                    EPlusBotConfig.id == view.id,
                )
            )
        ).one()
    assert saved.bot_id == "bot-1"


def _certificate_pem(*, is_ca: bool) -> bytes:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "E+ Test CA")])
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=is_ca, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    return certificate.public_bytes(serialization.Encoding.PEM)


async def test_certificate_store_accepts_only_ca_pem_and_uses_content_addressed_key() -> None:
    minio = FakeMinio()
    store = MinioCertificateStore(minio)
    ca_pem = _certificate_pem(is_ca=True)

    object_key, sha256 = await store.put_ca(ca_pem)

    assert object_key == f"eplus/ca/{sha256}.pem"
    assert minio.objects[object_key] == ca_pem
    with pytest.raises(ValueError, match="CA certificate"):
        await store.put_ca(_certificate_pem(is_ca=False))
    with pytest.raises(ValueError, match="PEM certificate"):
        await store.put_ca(b"not a certificate")
