import asyncio
import json
import os
import re
from abc import ABC
from datetime import timedelta
from io import BytesIO
from pathlib import Path
from typing import BinaryIO, Union, Optional

import minio
from loguru import logger
from minio.commonconfig import Filter
from minio.error import S3Error
from minio.lifecycleconfig import LifecycleConfig, Rule, Expiration
from urllib3 import BaseHTTPResponse

from bisheng.common.services.config_service import settings as _bisheng_settings
from bisheng.core.config.settings import MinioConf
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.core.storage.base import BaseStorage

# F017 AC-06: prefix pattern installed by multi_tenant layout —
#   Root       → no prefix (e.g. ``knowledge/<file>``)
#   Child N    → ``tenant_{code}/knowledge/<file>``
# The regex is deliberately permissive (tenant_* then a slash) because
# Tenant codes are deployment-specific (e.g. 'subA', 'legal-co', '01').
_TENANT_PREFIX_RE = re.compile(r'^tenant_[^/]+/')


def _is_no_such_key_error(exc: Exception) -> bool:
    """True only for the minio-py S3 NoSuchKey response (S3Error.code)."""
    return isinstance(exc, S3Error) and getattr(exc, 'code', None) == 'NoSuchKey'


def _translate_to_root_prefix(object_name: str) -> Optional[str]:
    """Strip a leading ``tenant_{code}/`` prefix so the key falls back to
    the Root layout. Returns None when there's no tenant prefix to remove
    (i.e. caller is already reading a Root-shaped path and fallback would
    be a no-op).
    """
    if not object_name:
        return None
    new_name, replaced = _TENANT_PREFIX_RE.subn('', object_name, count=1)
    if replaced == 0 or new_name == object_name:
        return None
    return new_name


def _should_fallback_to_root() -> bool:
    """F017 AC-06: fall back to Root prefix only when
      1. multi_tenant is enabled in this deployment;
      2. the caller's leaf tenant is a Child (tenant_id != 1 and not None).
    """
    if not getattr(getattr(_bisheng_settings, 'multi_tenant', None), 'enabled', False):
        return False
    tid = get_current_tenant_id()
    return tid is not None and tid != 1


class MinioStorage(BaseStorage, ABC):
    """MinIO storage backend implementation."""

    def __init__(self, minio_config: MinioConf):
        self.minio_config = minio_config
        self.bucket = minio_config.public_bucket
        self.tmp_bucket = minio_config.tmp_bucket

        self.minio_client_sync = minio.Minio(
            endpoint=minio_config.endpoint,
            access_key=minio_config.access_key,
            secret_key=minio_config.secret_key,
            secure=minio_config.secure,
            cert_check=minio_config.cert_check
        )
        self.share_minio_client = minio.Minio(
            endpoint=minio_config.sharepoint,
            access_key=minio_config.access_key,
            secret_key=minio_config.secret_key,
            secure=minio_config.share_schema,
            cert_check=minio_config.share_cert_check
        )

        # self.minio_client = miniopy_async.Minio(
        #     endpoint=minio_config.endpoint,
        #     access_key=minio_config.access_key,
        #     secret_key=minio_config.secret_key,
        #     secure=minio_config.secure,
        #     cert_check=minio_config.cert_check
        # )
        self._init_bucket_conf()

    def _init_bucket_conf(self):
        # create need bucket
        self.create_bucket_sync(bucket_name=self.bucket)
        self.create_bucket_sync(bucket_name=self.tmp_bucket)

        # set knowledge chunk images anonymous read policy
        anonymous_read_policy = {
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                "Principal": {
                    "AWS": ["*"]
                },
                "Action": ["s3:GetObject"],
                "Resource": [f"arn:aws:s3:::{self.bucket}/knowledge/images/*",
                             f"arn:aws:s3:::{self.bucket}/tmp/images/*"]
            }]
        }
        try:
            policy = self.minio_client_sync.get_bucket_policy(self.bucket)
        except Exception as e:
            if str(e).find('NoSuchBucketPolicy') == -1:
                raise e
            self.minio_client_sync.set_bucket_policy(self.bucket, json.dumps(anonymous_read_policy))

        # set tmp bucket lifecycle
        if not self.minio_client_sync.get_bucket_lifecycle(self.tmp_bucket):
            lifecycle_conf = LifecycleConfig([
                Rule(
                    'Enabled',
                    rule_filter=Filter(prefix='*'),
                    rule_id='rule1',
                    expiration=Expiration(days=3),
                ),
            ], )
            self.minio_client_sync.set_bucket_lifecycle(self.tmp_bucket, lifecycle_conf)

    async def create_bucket(self, bucket_name: str) -> None:
        return await asyncio.to_thread(self.create_bucket_sync, bucket_name=bucket_name)

    def create_bucket_sync(self, bucket_name: str) -> None:
        if not self.minio_client_sync.bucket_exists(bucket_name):
            self.minio_client_sync.make_bucket(bucket_name)

    async def check_bucket_exists(self, bucket_name: str) -> bool:
        return await asyncio.to_thread(self.check_bucket_exists, bucket_name=bucket_name)

    def check_bucket_exists_sync(self, bucket_name: str) -> bool:
        return self.minio_client_sync.bucket_exists(bucket_name)

    async def get_all_buckets(self) -> list:
        return await asyncio.to_thread(self.get_all_buckets_sync)

    def get_all_buckets_sync(self) -> list:
        return self.minio_client_sync.list_buckets()

    async def remove_bucket(self, bucket_name: str) -> None:
        return await asyncio.to_thread(self.remove_bucket_sync, bucket_name=bucket_name)

    def remove_bucket_sync(self, bucket_name: str) -> None:
        if self.minio_client_sync.bucket_exists(bucket_name):
            self.minio_client_sync.remove_bucket(bucket_name)

    async def put_object(self, *, bucket_name: Optional[str] = None, object_name: str,
                         file: Union[bytes, BinaryIO, Path, str],
                         content_type: str = "application/octet-stream", **kwargs) -> None:
        return await asyncio.to_thread(self.put_object_sync, bucket_name=bucket_name, object_name=object_name,
                                       file=file, content_type=content_type, **kwargs)

    def put_object_sync(self, *, bucket_name: Optional[str] = None, object_name: str,
                        file: Union[bytes, BinaryIO, Path, str],
                        content_type: str = "application/octet-stream", **kwargs) -> None:

        if bucket_name is None:
            bucket_name = self.bucket

        if isinstance(file, (Path, str)):
            file_path = str(file)
            self.minio_client_sync.fput_object(
                bucket_name=bucket_name,
                object_name=object_name,
                file_path=file_path,
                content_type=content_type,
                **kwargs
            )
            return

        data_stream = file

        if isinstance(file, bytes):
            data_stream = BytesIO(file)

        if 'length' not in kwargs:
            try:
                if hasattr(data_stream, "getbuffer"):
                    kwargs['length'] = data_stream.getbuffer().nbytes

                elif hasattr(data_stream, "fileno"):
                    try:
                        kwargs['length'] = os.fstat(data_stream.fileno()).st_size
                    except Exception:

                        data_stream.seek(0, 2)
                        kwargs['length'] = data_stream.tell()
                        data_stream.seek(0)
                else:
                    data_stream.seek(0, 2)
                    kwargs['length'] = data_stream.tell()
                    data_stream.seek(0)

            except Exception as e:
                raise ValueError(f"Could not determine file length for upload: {str(e)}")

        if hasattr(data_stream, "seek") and callable(data_stream.seek):
            data_stream.seek(0)

        self.minio_client_sync.put_object(
            bucket_name=bucket_name,
            object_name=object_name,
            data=data_stream,
            content_type=content_type,
            **kwargs
        )

    async def put_object_tmp(self, object_name: str, file: Union[bytes, BinaryIO, Path, str],
                             content_type: str = "application/octet-stream", **kwargs) -> None:
        await self.put_object(
            bucket_name=self.tmp_bucket,
            object_name=object_name,
            file=file,
            content_type=content_type,
            **kwargs
        )

    def put_object_tmp_sync(self, object_name: str, file: Union[bytes, BinaryIO, Path, str],
                            content_type: str = "application/octet-stream", **kwargs) -> None:
        self.put_object_sync(
            bucket_name=self.tmp_bucket,
            object_name=object_name,
            file=file,
            content_type=content_type,
            **kwargs
        )

    async def get_object(self, bucket_name: Optional[str] = None, object_name: str = None) -> bytes | None:
        return await asyncio.to_thread(self.get_object_sync, bucket_name=bucket_name, object_name=object_name)

    def get_object_sync(self, bucket_name: Optional[str] = None, object_name: str = None) -> bytes | None:

        if bucket_name is None:
            bucket_name = self.bucket

        if object_name is None:
            raise ValueError("get_object_sync: object_name must be provided")

        try:
            response = self.minio_client_sync.get_object(bucket_name, object_name)
        except Exception as e:
            # F017 AC-06: Child user reading a Root-shared file may hit a
            # NoSuchKey for their own tenant prefix — retry with the Root
            # prefix (shared resources live under default/ without the
            # tenant_{code}/ segment). Only fall back in multi-tenant mode
            # and only for Child callers (see _should_fallback_to_root).
            if not _is_no_such_key_error(e) or not _should_fallback_to_root():
                raise
            root_name = _translate_to_root_prefix(object_name)
            if root_name is None:
                raise
            logger.info(
                '[F017] MinIO fallback: %s not found, retry at Root path %s',
                object_name, root_name,
            )
            try:
                response = self.minio_client_sync.get_object(bucket_name, root_name)
            except Exception as e2:
                # Genuine miss — surface as 19503 so the caller / UI knows
                # it was a cross-tenant fallback attempt that failed
                # rather than a plain 404.
                from bisheng.common.errcode.tenant_sharing import StorageSharingFallbackError
                raise StorageSharingFallbackError() from e2

        try:
            data = response.read()
            return data
        except Exception:
            raise

        finally:
            response.close()
            response.release_conn()

    def download_object_sync(self, bucket_name: Optional[str] = None, object_name: str = None) -> BaseHTTPResponse:
        # This method is intended for streaming downloads, returning the raw response object for the caller to handle the stream.
        # The caller is responsible for closing the response and releasing the connection after consuming the stream.
        if bucket_name is None:
            bucket_name = self.bucket

        if object_name is None:
            raise ValueError("download_object_sync: object_name must be provided")
        try:
            return self.minio_client_sync.get_object(bucket_name, object_name)
        except Exception as e:
            # F017 AC-06: mirror get_object_sync's Root-prefix fallback so
            # streaming downloads of Root-shared files also succeed for
            # Child users.
            if not _is_no_such_key_error(e) or not _should_fallback_to_root():
                raise
            root_name = _translate_to_root_prefix(object_name)
            if root_name is None:
                raise
            logger.info(
                '[F017] MinIO download fallback: %s not found, retry at Root path %s',
                object_name, root_name,
            )
            try:
                return self.minio_client_sync.get_object(bucket_name, root_name)
            except Exception as e2:
                from bisheng.common.errcode.tenant_sharing import StorageSharingFallbackError
                raise StorageSharingFallbackError() from e2

    async def object_exists(self, bucket_name: Optional[str] = None, object_name: str = None) -> bool:

        return await asyncio.to_thread(self.object_exists_sync, bucket_name=bucket_name, object_name=object_name)

    def object_exists_sync(self, bucket_name: Optional[str] = None, object_name: str = None) -> bool:

        if not bucket_name:
            bucket_name = self.bucket

        if not object_name:
            logger.warning("object_exists_sync: object_name must be provided")
            return False

        try:
            self.minio_client_sync.stat_object(bucket_name, object_name)
            return True
        except Exception as e:
            if _is_no_such_key_error(e):
                # F017 AC-06: treat an existing Root-shared file as present
                # for Child callers. No exception here — existence check
                # is advisory and pre-existing callers expect False/True,
                # not ``StorageSharingFallbackError``.
                if _should_fallback_to_root():
                    root_name = _translate_to_root_prefix(object_name)
                    if root_name is not None:
                        try:
                            self.minio_client_sync.stat_object(bucket_name, root_name)
                            return True
                        except Exception:
                            return False
                return False
            raise e

    async def copy_object(self, source_bucket: str = None, source_object: str = None,
                          dest_bucket: str = None, dest_object: str = None) -> None:

        return await asyncio.to_thread(self.copy_object_sync, source_bucket=source_bucket, source_object=source_object,
                                       dest_bucket=dest_bucket, dest_object=dest_object)

    def copy_object_sync(self, source_bucket: str = None, source_object: str = None,
                         dest_bucket: str = None, dest_object: str = None) -> None:

        if source_bucket is None:
            source_bucket = self.tmp_bucket

        if dest_bucket is None:
            dest_bucket = self.bucket
        source = minio.commonconfig.CopySource(
            bucket_name=source_bucket,
            object_name=source_object
        )

        self.minio_client_sync.copy_object(
            bucket_name=dest_bucket,
            object_name=dest_object,
            source=source
        )

    async def remove_object(self, bucket_name: Optional[str] = None, object_name: str = None) -> None:
        return await asyncio.to_thread(self.remove_object_sync, bucket_name=bucket_name, object_name=object_name)

    def remove_object_sync(self, bucket_name: Optional[str] = None, object_name: str = None) -> None:
        if bucket_name is None:
            bucket_name = self.bucket

        if object_name is None:
            raise ValueError("remove_object_sync: object_name must be provided")

        self.minio_client_sync.remove_object(bucket_name, object_name)

    async def get_share_link(self, object_name, bucket=None, clear_host: bool = True, expire_days: int = 7) -> str:
        """
        DapatkanminioFile sharing link
        :param object_name:
        :param bucket:
        :param clear_host:  Do you want to removehost<g id="Bold">Address:</g> urlVia FrontendnginxProxy Access
        :param expire_days:  Link expiration time,  days
        :return:
        """

        return await asyncio.to_thread(self.get_share_link_sync, object_name, bucket=bucket, clear_host=clear_host,
                                       expire_days=expire_days)

    def get_share_link_sync(self, object_name, bucket=None, clear_host: bool = True, expire_days: int = 7) -> str:
        """
        Synchronous fetchminioFile sharing link, Default Removalhost<g id="Bold">Address:</g> urlwill go through the front endnginxProxy Access
        :param object_name:
        :param bucket:
        :param clear_host:  Do you want to removehost<g id="Bold">Address:</g> urlVia FrontendnginxProxy Access
        :param expire_days:  Link expiration time,  days
        :return:
        """

        if bucket is None:
            bucket = self.bucket
        # filepath "/" There will be at the beginningnginxQuestions
        if object_name[0] == '/':
            object_name = object_name[1:]

        share_link = self.share_minio_client.presigned_get_object(bucket, object_name,
                                                                  expires=timedelta(days=expire_days))
        if clear_host:
            share_link = self.clear_minio_share_host(share_link)
        return share_link

    def get_minio_share_host(self) -> str:
        """
        Dapatkanminio share host
        """
        minio_share = self.minio_config.sharepoint
        if self.minio_config.share_schema:
            return f'https://{minio_share}'
        return f'http://{minio_share}'

    def clear_minio_share_host(self, file_url: str):
        """
         TODO The logical solution is to deploy ahttpsright of privacyminioUse with front-end
         to be erasedurlhitting the nail on the headminio share<g id="Bold">Address:</g> Let the front end throughnginxProxy to access resources
        """
        share_host = self.get_minio_share_host()

        return file_url.replace(share_host, '')

    async def close(self) -> None:
        """Close Minio Client link"""
        # await self.minio_client.close_session()
        pass

    def close_sync(self) -> None:
        """Sync off Minio Client link"""
        del self.minio_client_sync
