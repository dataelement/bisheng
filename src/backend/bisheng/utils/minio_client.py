import io
import json
from typing import BinaryIO

import minio
from bisheng.settings import settings
from loguru import logger
from minio.commonconfig import Filter, CopySource
from minio.lifecycleconfig import LifecycleConfig, Rule, Expiration

from bisheng.settings import settings

_MinioConf = settings.get_minio_conf()
bucket = _MinioConf.public_bucket
tmp_bucket = _MinioConf.tmp_bucket


class MinioClient:
    minio_share: minio.Minio
    minio_client: minio.Minio

    tmp_bucket = tmp_bucket
    bucket = bucket

    def __init__(self) -> None:
        self.minio_client = minio.Minio(
            endpoint=_MinioConf.endpoint,
            access_key=_MinioConf.access_key,
            secret_key=_MinioConf.secret_key,
            secure=_MinioConf.schema,
            cert_check=_MinioConf.cert_check)
        self.minio_share = minio.Minio(
            endpoint=_MinioConf.sharepoint,
            access_key=_MinioConf.access_key,
            secret_key=_MinioConf.secret_key,
            secure=_MinioConf.schema,
            cert_check=_MinioConf.cert_check)

        self._init_bucket_conf()

    def _init_bucket_conf(self):
        # create need bucket
        self.mkdir(new_bucket=self.bucket)
        self.mkdir(new_bucket=self.tmp_bucket)

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
            policy = self.minio_client.get_bucket_policy(self.bucket)
        except Exception as e:
            if str(e).find('NoSuchBucketPolicy') == -1:
                raise e
            self.minio_client.set_bucket_policy(self.bucket, json.dumps(anonymous_read_policy))

        try:
            policy = self.minio_client.get_bucket_policy(self.tmp_bucket)
        except Exception as e:
            if str(e).find('NoSuchBucketPolicy') == -1:
                raise e
            self.minio_client.set_bucket_policy(self.tmp_bucket, json.dumps(tmp_policy))

        # set tmp bucket lifecycle
        if not self.minio_client.get_bucket_lifecycle(self.tmp_bucket):
            lifecycle_conf = LifecycleConfig([
                Rule(
                    'Enabled',
                    rule_filter=Filter(prefix='documents/'),
                    rule_id='rule1',
                    expiration=Expiration(days=1),
                ),
            ], )
            self.minio_client.set_bucket_lifecycle(self.tmp_bucket, lifecycle_conf)

    def upload_minio(self,
                     object_name: str,
                     file_path,
                     content_type='application/text',
                     bucket_name=bucket):
        # 初始化minio
        logger.debug('upload_file obj={} bucket={} file_paht={}', object_name, bucket, file_path)
        return self.minio_client.fput_object(bucket_name=bucket_name,
                                             object_name=object_name,
                                             file_path=file_path,
                                             content_type=content_type)

    def upload_minio_file_io(self, object_name: str, file: BinaryIO, bucket_name=bucket, **kwargs):
        # 初始化minio
        logger.debug('upload_file obj={} bucket={}', object_name, bucket)
        return self.minio_client.put_object(bucket_name=bucket_name,
                                            object_name=object_name,
                                            data=file,
                                            **kwargs)

    def upload_minio_data(self, object_name: str, data, length, content_type):
        # 初始化minio
        self.minio_client.put_object(bucket_name=bucket,
                                     object_name=object_name,
                                     data=io.BytesIO(data),
                                     length=length,
                                     content_type=content_type)

    def get_share_link(self, object_name, bucket=bucket):
        # filepath "/" 开头会有nginx问题
        if object_name[0] == '/':
            object_name = object_name[1:]
        # 因为bucket都允许公开访问了，所以不再需要生成有期限的url
        share_host = self.get_minio_share_host()
        return f'{share_host}/{bucket}/{object_name}'

    def upload_tmp(self, object_name, data):
        self.minio_client.put_object(bucket_name=tmp_bucket,
                                     object_name=object_name,
                                     data=io.BytesIO(data),
                                     length=len(data))

    def delete_minio(self, object_name: str):
        self.minio_client.remove_object(bucket_name=bucket, object_name=object_name)

    def mkdir(self, new_bucket: str):
        if not self.minio_client.bucket_exists(new_bucket):
            self.minio_client.make_bucket(new_bucket)

    def upload_minio_file(self,
                          object_name: str,
                          file: BinaryIO,
                          bucket_name=bucket,
                          length: int = -1,
                          **kwargs):
        # 初始化minio
        if length == -1:
            length = len(file.read())
            file.seek(0)
        self.minio_client.put_object(bucket_name=bucket_name,
                                     object_name=object_name,
                                     data=file,
                                     length=length,
                                     **kwargs)

    def download_minio(self, object_name: str):
        return self.minio_client.get_object(bucket_name=bucket, object_name=object_name)

    @classmethod
    def get_minio_share_host(cls) -> str:
        """
        获取minio share host
        """
        minio_share = _MinioConf.sharepoint
        if _MinioConf.schema:
            return f'https://{minio_share}'
        return f'http://{minio_share}'

    @classmethod
    def clear_minio_share_host(cls, file_url: str):
        """
         TODO 合理方案是部署一个https的minio配合前端使用
         抹去url中的minio share地址， 让前端通过nginx代理去访问资源
        """
        share_host = cls.get_minio_share_host()

        return file_url.replace(share_host, '')

    def object_exists(self, bucket_name, object_name, **kwargs):
        if not object_name:
            return False
        try:
            self.minio_client.stat_object(bucket_name, object_name, **kwargs)
            return True
        except Exception as e:
            if 'code: NoSuchKey' in str(e):
                return False
            raise e

    def get_object(self, bucket_name, object_name, **kwargs) -> bytes:
        response = None
        try:
            response = self.minio_client.get_object(bucket_name, object_name, **kwargs)
            return response.read()
        finally:
            if response:
                response.close()
                response.release_conn()

    def copy_object(
            self,
            source_object_name,
            target_object_name,
            bucket_name=bucket,
            target_bucket_name=None
    ):
        if target_bucket_name is None:
            target_bucket_name = bucket_name
        copy_source = CopySource(bucket_name=bucket_name, object_name=source_object_name)
        response = self.minio_client.copy_object(target_bucket_name, target_object_name, copy_source)
        return response


minio_client = MinioClient()
