"""Encrypted credentials and content-addressed CA certificate storage."""

from __future__ import annotations

import hashlib
from typing import Protocol

from cryptography import x509
from cryptography.x509.extensions import ExtensionNotFound

from bisheng.core.config.settings import decrypt_token, encrypt_token


class MinioLike(Protocol):
    async def put_object(
        self,
        *,
        object_name: str,
        file: bytes,
        content_type: str,
        bucket_name: str | None = None,
    ) -> None: ...


class PlatformCredentialStore:
    def encrypt(self, secret: str) -> str:
        encrypted = encrypt_token(secret)
        return encrypted.decode("ascii") if isinstance(encrypted, bytes) else str(encrypted)

    def decrypt(self, ciphertext: str) -> str:
        return decrypt_token(ciphertext.encode("ascii"))


class MinioCertificateStore:
    def __init__(self, minio: MinioLike, *, bucket_name: str | None = None) -> None:
        self._minio = minio
        self._bucket_name = bucket_name

    async def put_ca(self, pem: bytes) -> tuple[str, str]:
        try:
            certificate = x509.load_pem_x509_certificate(pem)
        except ValueError as exc:
            raise ValueError("CA upload must be a PEM certificate") from exc
        try:
            constraints = certificate.extensions.get_extension_for_class(x509.BasicConstraints).value
        except ExtensionNotFound as exc:
            raise ValueError("certificate is not a CA certificate") from exc
        if not constraints.ca:
            raise ValueError("certificate is not a CA certificate")

        sha256 = hashlib.sha256(pem).hexdigest()
        object_key = f"eplus/ca/{sha256}.pem"
        await self._minio.put_object(
            bucket_name=self._bucket_name,
            object_name=object_key,
            file=pem,
            content_type="application/x-pem-file",
        )
        return object_key, sha256
