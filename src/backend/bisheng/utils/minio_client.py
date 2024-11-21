import io
from datetime import timedelta
from typing import BinaryIO

import minio
from bisheng.settings import settings
from loguru import logger

bucket = 'bisheng'
tmp_bucket = 'tmp-dir'


class MinioClient:
    minio_share: minio.Minio
    minio_client: minio.Minio

    tmp_bucket = tmp_bucket
    bucket = bucket

    def __init__(self) -> None:
        if 'minio' not in settings.get_knowledge(
        ) or not settings.get_knowledge().get('minio').get('MINIO_ENDPOINT'):
            raise Exception('请配置minio地址等相关配置')
        self.minio_client = minio.Minio(
            endpoint=settings.get_knowledge().get('minio').get('MINIO_ENDPOINT'),
            access_key=settings.get_knowledge().get('minio').get('MINIO_ACCESS_KEY'),
            secret_key=settings.get_knowledge().get('minio').get('MINIO_SECRET_KEY'),
            secure=settings.get_knowledge().get('minio').get('SCHEMA'),
            cert_check=settings.get_knowledge().get('minio').get('CERT_CHECK'))
        self.minio_share = minio.Minio(
            endpoint=settings.get_knowledge().get('minio').get('MINIO_SHAREPOIN'),
            access_key=settings.get_knowledge().get('minio').get('MINIO_ACCESS_KEY'),
            secret_key=settings.get_knowledge().get('minio').get('MINIO_SECRET_KEY'),
            secure=settings.get_knowledge().get('minio').get('SCHEMA'),
            cert_check=settings.get_knowledge().get('minio').get('CERT_CHECK'))
        self.mkdir(new_bucket=bucket)

    def upload_minio(self, object_name: str, file_path, content_type='application/text', bucket_name=bucket):
        # 初始化minio
        logger.debug('upload_file obj={} bucket={} file_paht={}', object_name, bucket,
                     file_path)
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
        return self.minio_share.presigned_get_object(bucket_name=bucket,
                                                     object_name=object_name,
                                                     expires=timedelta(days=7))

    def upload_tmp(self, object_name, data):
        self.mkdir(tmp_bucket)
        from minio.lifecycleconfig import LifecycleConfig, Rule, Expiration
        from minio.commonconfig import Filter

        if not self.minio_client.get_bucket_lifecycle(tmp_bucket):
            lifecycle_conf = LifecycleConfig([
                Rule(
                    'Enabled',
                    rule_filter=Filter(prefix='documents/'),
                    rule_id='rule1',
                    expiration=Expiration(days=1),
                ),
            ], )
            self.minio_client.set_bucket_lifecycle(tmp_bucket, lifecycle_conf)

        self.minio_client.put_object(bucket_name=tmp_bucket,
                                     object_name=object_name,
                                     data=io.BytesIO(data),
                                     length=len(data))

    def delete_minio(self, object_name: str):
        self.minio_client.remove_object(bucket_name=bucket, object_name=object_name)

    def mkdir(self, new_bucket: str):
        if not self.minio_client.bucket_exists(new_bucket):
            self.minio_client.make_bucket(new_bucket)

    def upload_minio_file(self, object_name: str, file: BinaryIO, bucket_name=bucket, length: int = -1, **kwargs):
        # 初始化minio
        if length == -1:
            length = len(file.read())
            file.seek(0)
        self.minio_client.put_object(bucket_name=bucket_name,
                                     object_name=object_name,
                                     data=file,
                                     length=length, **kwargs)

    def download_minio(self, object_name: str):
        return self.minio_client.get_object(bucket_name=bucket, object_name=object_name)

    @classmethod
    def clear_minio_share_host(cls, file_url: str):
        """
         TODO 合理方案是部署一个https的minio配合前端使用
         抹去url中的minio share地址， 让前端通过nginx代理去访问资源
        """
        minio_share = settings.get_knowledge().get('minio', {}).get('MINIO_SHAREPOIN', '')
        return file_url.replace(f"http://{minio_share}", "")

    def object_exists(self, bucket_name, object_name, **kwargs):
        try:
            self.minio_client.stat_object(bucket_name, object_name, **kwargs)
            return True
        except Exception as e:
            if 'code: NoSuchKey' in str(e):
                return False
            raise e

    def get_object(self, bucket_name, object_name, **kwargs) -> bytes:
        try:
            response = self.minio_client.get_object(bucket_name, object_name, **kwargs)
            return response.read()
        finally:
            response.close()
            response.release_conn()
