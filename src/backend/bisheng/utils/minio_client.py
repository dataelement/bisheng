import io
from datetime import timedelta

import minio
from bisheng.settings import settings
from loguru import logger

bucket = 'bisheng'
tmp_bucket = 'tmp-dir'


class MinioClient():
    minio_share: minio.Minio
    minio_client: minio.Minio

    def __init__(self) -> None:
        if 'minio' not in settings.get_knowledge(
        ) or not settings.get_knowledge().get('minio').get('MINIO_ENDPOINT'):
            self.minio_client = None
            self.minio_share = None
            return
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
        self.mkdir(bucket=bucket)

    def upload_minio(self, object_name: str, file_path, content_type='application/text'):
        # 初始化minio
        if self.minio_client:
            logger.debug('upload_file obj={} bucket={} file_paht={}', object_name, bucket,
                         file_path)
            return self.minio_client.fput_object(bucket_name=bucket,
                                                 object_name=object_name,
                                                 file_path=file_path,
                                                 content_type=content_type)

    def upload_minio_data(self, object_name: str, data, length, content_type):
        # 初始化minio
        if self.minio_client:
            self.minio_client.put_object(bucket_name=bucket,
                                         object_name=object_name,
                                         data=io.BytesIO(data),
                                         length=length,
                                         content_type=content_type)

    def get_share_link(self, object_name, bucket=bucket):
        # filepath "/" 开头会有nginx问题
        if object_name[0] == '/':
            object_name = object_name[1:]
        try:
            if self.minio_share and self.minio_share.stat_object(bucket_name=bucket,
                                                                 object_name=object_name):
                return self.minio_share.presigned_get_object(bucket_name=bucket,
                                                             object_name=object_name,
                                                             expires=timedelta(days=7))
            else:
                return ''
        except Exception:
            return ''

    def upload_tmp(self, object_name, data):
        self.mkdir(tmp_bucket)
        from minio.lifecycleconfig import LifecycleConfig, Rule, Expiration
        from minio.commonconfig import Filter

        if self.minio_client and not self.minio_client.get_bucket_lifecycle(tmp_bucket):
            lifecycle_conf = LifecycleConfig([
                Rule(
                    'Enabled',
                    rule_filter=Filter(prefix='documents/'),
                    rule_id='rule1',
                    expiration=Expiration(days=1),
                ),
            ], )
            self.minio_client.set_bucket_lifecycle(tmp_bucket, lifecycle_conf)

        if self.minio_client:
            self.minio_client.put_object(bucket_name=tmp_bucket,
                                         object_name=object_name,
                                         data=io.BytesIO(data),
                                         length=len(data))

    def delete_minio(self, object_name: str):
        if self.minio_client:
            self.minio_client.remove_object(bucket_name=bucket, object_name=object_name)

    def mkdir(self, bucket: str):
        if self.minio_client:
            if not self.minio_client.bucket_exists(bucket):
                self.minio_client.make_bucket(bucket)
