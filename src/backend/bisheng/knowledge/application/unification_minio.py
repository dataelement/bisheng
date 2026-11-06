"""Private M2 objects through raw MinIO, without bucket initialization."""

import hashlib
import re
import ssl
from contextlib import asynccontextmanager
from io import BytesIO

import certifi
import miniopy_async
from aiohttp import ClientSession, ClientTimeout, TCPConnector
from loguru import logger
from miniopy_async.error import S3Error

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError
from bisheng.core.config.settings import MinioConf

MAX_BYTES = 16 * 1024 * 1024
_ARTIFACT = re.compile(r"f118/unification/[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}/[a-z_]{1,48}/([0-9a-f]{64})\.json")


def _invalid(reason):
    raise KnowledgeOperationPlanConflictError(reason=f"migration_storage_{reason}")


def validate_object_key(value):
    if (
        type(value) is not str
        or not value
        or len(value) > 4096
        or "\x00" in value
        or value.startswith("/")
        or "://" in value
        or ".." in value.split("/")
    ):
        _invalid("object_key_invalid")


class UnificationMinio:
    def __init__(self, *, client, bucket, tmp_bucket, session=None):
        if (
            type(bucket) is not str
            or not bucket
            or type(tmp_bucket) is not str
            or not tmp_bucket
            or bucket == tmp_bucket
            or any(not callable(getattr(client, name, None)) for name in ("stat_object", "get_object", "put_object"))
        ):
            _invalid("native_client_required")
        self._client, self.bucket, self.tmp_bucket = client, bucket, tmp_bucket
        self._session, self._closed = session, False

    @classmethod
    @asynccontextmanager
    async def aopen(cls, config: MinioConf):
        if not isinstance(config, MinioConf):
            _invalid("configuration_required")
        context = ssl.create_default_context(cafile=certifi.where()) if config.cert_check else False
        session = ClientSession(
            connector=TCPConnector(ssl=context),
            timeout=ClientTimeout(connect=10, sock_read=config.upload_timeout_seconds),
        )
        try:
            client = miniopy_async.Minio(
                config.endpoint,
                access_key=config.access_key,
                secret_key=config.secret_key,
                secure=bool(config.secure),
                cert_check=bool(config.cert_check),
                session=session,
            )
            adapter = cls(client=client, bucket=config.public_bucket, tmp_bucket=config.tmp_bucket, session=session)
        except Exception as error:
            await session.close()
            raise KnowledgeOperationPlanConflictError(reason="migration_storage_initialize_failed") from error
        primary = None
        try:
            yield adapter
        except BaseException as error:
            primary = error
            raise
        finally:
            try:
                await adapter.aclose()
            except Exception:
                if primary is None:
                    raise
                logger.opt(exception=True).warning("M2 private storage close failed after a primary error")

    def _alive(self):
        if self._closed:
            _invalid("client_closed")

    def _artifact_key(self, bucket_name, object_name):
        self._alive()
        validate_object_key(object_name)
        match = _ARTIFACT.fullmatch(object_name)
        if bucket_name != self.bucket or match is None:
            _invalid("artifact_scope_invalid")
        return match.group(1)

    async def aclose(self):
        if self._closed:
            return
        self._closed = True
        if self._session is not None:
            await self._session.close()

    async def astat_object(self, object_name):
        self._alive()
        validate_object_key(object_name)
        try:
            result = await self._client.stat_object(self.bucket, object_name)
        except S3Error as error:
            if error.code == "NoSuchKey":
                return {"exists": False, "size": None, "etag": None}
            raise KnowledgeOperationPlanConflictError(reason="migration_storage_stat_failed") from error
        except Exception as error:
            raise KnowledgeOperationPlanConflictError(reason="migration_storage_stat_failed") from error
        if type(result.size) is not int or result.size < 0 or not isinstance(result.etag, str):
            _invalid("stat_result_invalid")
        return {"exists": True, "size": result.size, "etag": result.etag or None}

    async def object_exists(self, *, bucket_name, object_name):
        self._artifact_key(bucket_name, object_name)
        stat = await self.astat_object(object_name)
        if stat["size"] is not None and stat["size"] > MAX_BYTES:
            _invalid("artifact_size_exceeded")
        return stat["exists"]

    async def get_object(self, *, bucket_name, object_name):
        expected = self._artifact_key(bucket_name, object_name)
        response = None
        try:
            response = await self._client.get_object(bucket_name, object_name)
            declared = response.headers.get("content-length")
            if declared is not None and (not str(declared).isdigit() or int(declared) > MAX_BYTES):
                _invalid("artifact_size_exceeded")
            output = bytearray()
            async for chunk in response.content.iter_chunked(64 * 1024):
                if type(chunk) is not bytes or len(output) + len(chunk) > MAX_BYTES:
                    _invalid("artifact_size_exceeded")
                output.extend(chunk)
            result = bytes(output)
            if hashlib.sha256(result).hexdigest() != expected:
                _invalid("artifact_digest_mismatch")
            return result
        except KnowledgeOperationPlanConflictError:
            raise
        except Exception as error:
            raise KnowledgeOperationPlanConflictError(reason="migration_storage_read_failed") from error
        finally:
            if response is not None:
                response.release()

    async def put_object(self, *, bucket_name, object_name, file, content_type="application/json"):
        expected = self._artifact_key(bucket_name, object_name)
        if (
            type(file) is not bytes
            or not file
            or len(file) > MAX_BYTES
            or content_type != "application/json"
            or hashlib.sha256(file).hexdigest() != expected
        ):
            _invalid("artifact_payload_invalid")
        try:
            await self._client.put_object(
                bucket_name=bucket_name,
                object_name=object_name,
                data=BytesIO(file),
                length=len(file),
                content_type=content_type,
            )
        except Exception as error:
            raise KnowledgeOperationPlanConflictError(reason="migration_storage_write_failed") from error
