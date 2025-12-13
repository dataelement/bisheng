import json
from abc import ABC
from io import BytesIO
from pathlib import Path
from typing import BinaryIO, Union, Optional

import minio
import miniopy_async
import miniopy_async.commonconfig as miniopy_async_commonconfig
from loguru import logger
from minio.commonconfig import Filter
from minio.lifecycleconfig import LifecycleConfig, Rule, Expiration

from bisheng.core.config.settings import MinioConf
from bisheng.core.storage.base import BaseStorage


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

        self.minio_client = miniopy_async.Minio(
            endpoint=minio_config.endpoint,
            access_key=minio_config.access_key,
            secret_key=minio_config.secret_key,
            secure=minio_config.secure,
            cert_check=minio_config.cert_check
        )
        self._init_bucket_conf()

    def _init_bucket_conf(self):
        # create need bucket
        self.create_bucket_sync(bucket_name=self.bucket)
        self.create_bucket_sync(bucket_name=self.tmp_bucket)

        anonymous_read_policy = {
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                "Principal": {
                    "AWS": ["*"]
                },
                "Action": ["s3:GetObject"],
                "Resource": [f"arn:aws:s3:::{self.bucket}/**"]
            }]
        }
        tmp_policy = {
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                "Principal": {
                    "AWS": ["*"]
                },
                "Action": ["s3:GetObject"],
                "Resource": [f"arn:aws:s3:::{self.tmp_bucket}/**"]
            }]
        }

        try:
            policy = self.minio_client_sync.get_bucket_policy(self.bucket)
        except Exception as e:
            if str(e).find('NoSuchBucketPolicy') == -1:
                raise e
            self.minio_client_sync.set_bucket_policy(self.bucket, json.dumps(anonymous_read_policy))

        try:
            policy = self.minio_client_sync.get_bucket_policy(self.tmp_bucket)
        except Exception as e:
            if str(e).find('NoSuchBucketPolicy') == -1:
                raise e
            self.minio_client_sync.set_bucket_policy(self.tmp_bucket, json.dumps(tmp_policy))

        # set tmp bucket lifecycle
        if not self.minio_client_sync.get_bucket_lifecycle(self.tmp_bucket):
            lifecycle_conf = LifecycleConfig([
                Rule(
                    'Enabled',
                    rule_filter=Filter(prefix='documents/'),
                    rule_id='rule1',
                    expiration=Expiration(days=1),
                ),
            ], )
            self.minio_client_sync.set_bucket_lifecycle(self.tmp_bucket, lifecycle_conf)

    async def create_bucket(self, bucket_name: str) -> None:
        if not await self.minio_client.bucket_exists(bucket_name):
            await self.minio_client.make_bucket(bucket_name)

    def create_bucket_sync(self, bucket_name: str) -> None:
        if not self.minio_client_sync.bucket_exists(bucket_name):
            self.minio_client_sync.make_bucket(bucket_name)

    async def check_bucket_exists(self, bucket_name: str) -> bool:
        return await self.minio_client.bucket_exists(bucket_name)

    def check_bucket_exists_sync(self, bucket_name: str) -> bool:
        return self.minio_client_sync.bucket_exists(bucket_name)

    async def get_all_buckets(self) -> list:
        return await self.minio_client.list_buckets()

    def get_all_buckets_sync(self) -> list:
        return self.minio_client_sync.list_buckets()

    async def remove_bucket(self, bucket_name: str) -> None:
        if await self.minio_client.bucket_exists(bucket_name):
            await self.minio_client.remove_bucket(bucket_name)

    def remove_bucket_sync(self, bucket_name: str) -> None:
        if self.minio_client_sync.bucket_exists(bucket_name):
            self.minio_client_sync.remove_bucket(bucket_name)

    async def put_object(self, *, bucket_name: Optional[str] = None, object_name: str,
                         file: Union[bytes, BinaryIO, Path, str],
                         content_type: str = "application/octet-stream", **kwargs) -> None:
        if bucket_name is None:
            bucket_name = self.bucket

        if isinstance(file, (bytes, BinaryIO, BytesIO)):
            if isinstance(file, bytes):
                file = BytesIO(file)
            if 'length' not in kwargs:
                length = len(file.getbuffer())
                kwargs['length'] = length
                file.seek(0)
            await self.minio_client.put_object(
                bucket_name=bucket_name,
                object_name=object_name,
                data=file,
                content_type=content_type,
                **kwargs
            )
        elif isinstance(file, (Path, str)):
            file_path = str(file)
            await self.minio_client.fput_object(
                bucket_name=bucket_name,
                object_name=object_name,
                file_path=file_path,
                content_type=content_type,
                **kwargs
            )
        else:
            await self.minio_client.put_object(
                bucket_name=bucket_name,
                object_name=object_name,
                data=file,
                content_type=content_type,
                **kwargs
            )

    def put_object_sync(self, *, bucket_name: Optional[str] = None, object_name: str,
                        file: Union[bytes, BinaryIO, Path, str],
                        content_type: str = "application/octet-stream", **kwargs) -> None:

        if bucket_name is None:
            bucket_name = self.bucket
        if isinstance(file, (bytes, BinaryIO, BytesIO)):
            if isinstance(file, bytes):
                file = BytesIO(file)
            if 'length' not in kwargs:
                length = len(file.getbuffer())
                kwargs['length'] = length
                file.seek(0)
            self.minio_client_sync.put_object(
                bucket_name=bucket_name,
                object_name=object_name,
                data=file,
                content_type=content_type,
                **kwargs
            )

        elif isinstance(file, (Path, str)):
            file_path = str(file)
            self.minio_client_sync.fput_object(
                bucket_name=bucket_name,
                object_name=object_name,
                file_path=file_path,
                content_type=content_type,
                **kwargs
            )
        else:
            self.minio_client_sync.put_object(
                bucket_name=bucket_name,
                object_name=object_name,
                data=file,
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

        if bucket_name is None:
            bucket_name = self.bucket

        if object_name is None:
            raise ValueError("get_object: object_name must be provided")

        response = await self.minio_client.get_object(bucket_name, object_name)

        try:
            data = await response.read()
            return data
        except Exception:
            raise

        finally:
            response.close()

    def get_object_sync(self, bucket_name: Optional[str] = None, object_name: str = None) -> bytes | None:

        if bucket_name is None:
            bucket_name = self.bucket

        if object_name is None:
            raise ValueError("get_object_sync: object_name must be provided")

        response = self.minio_client_sync.get_object(bucket_name, object_name)

        try:
            data = response.read()
            return data
        except Exception:
            raise

        finally:
            response.close()
            response.release_conn()

    async def object_exists(self, bucket_name: Optional[str] = None, object_name: str = None) -> bool:

        if not bucket_name:
            bucket_name = self.bucket

        if not object_name:
            logger.warning("object_exists_sync: object_name must be provided")
            return False

        try:
            await self.minio_client.stat_object(bucket_name, object_name)
            return True
        except Exception as e:
            if 'code: NoSuchKey' in str(e):
                return False
            raise e

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
            if 'code: NoSuchKey' in str(e):
                return False
            raise e

    async def copy_object(self, source_bucket: str = None, source_object: str = None,
                          dest_bucket: str = None, dest_object: str = None) -> None:

        if source_bucket is None:
            source_bucket = self.tmp_bucket

        if dest_bucket is None:
            dest_bucket = self.bucket

        source = miniopy_async_commonconfig.CopySource(
            bucket_name=source_bucket,
            object_name=source_object
        )
        await self.minio_client.copy_object(
            bucket_name=dest_bucket,
            object_name=dest_object,
            source=source
        )

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
        if bucket_name is None:
            bucket_name = self.bucket

        if object_name is None:
            raise ValueError("remove_object: object_name must be provided")

        await self.minio_client.remove_object(bucket_name, object_name)

    def remove_object_sync(self, bucket_name: Optional[str] = None, object_name: str = None) -> None:
        if bucket_name is None:
            bucket_name = self.bucket

        if object_name is None:
            raise ValueError("remove_object_sync: object_name must be provided")

        self.minio_client_sync.remove_object(bucket_name, object_name)

    def get_share_link(self, object_name, bucket=None) -> str:
        """
        获取minio文件分享链接
        :param object_name:
        :param bucket:
        :return:
        """

        if bucket is None:
            bucket = self.bucket

        # filepath "/" 开头会有nginx问题
        if object_name[0] == '/':
            object_name = object_name[1:]
        # 因为bucket都允许公开访问了，所以不再需要生成有期限的url
        share_host = self.get_minio_share_host()
        return f'{share_host}/{bucket}/{object_name}'

    def get_minio_share_host(self) -> str:
        """
        获取minio share host
        """
        minio_share = self.minio_config.sharepoint
        if self.minio_config.share_schema:
            return f'https://{minio_share}'
        return f'http://{minio_share}'

    def clear_minio_share_host(self, file_url: str):
        """
         TODO 合理方案是部署一个https的minio配合前端使用
         抹去url中的minio share地址， 让前端通过nginx代理去访问资源
        """
        share_host = self.get_minio_share_host()

        return file_url.replace(share_host, '')

    async def close(self) -> None:
        """关闭 Minio 客户端连接"""
        await self.minio_client.close_session()

    def close_sync(self) -> None:
        """同步关闭 Minio 客户端连接"""
        del self.minio_client_sync
