from datetime import timedelta

import minio
from bisheng.settings import settings

bucket = 'bisheng'


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
            secure=False)
        self.minio_share = minio.Minio(
            endpoint=settings.get_knowledge().get('minio').get('MINIO_SHAREPOIN'),
            access_key=settings.get_knowledge().get('minio').get('MINIO_ACCESS_KEY'),
            secret_key=settings.get_knowledge().get('minio').get('MINIO_SECRET_KEY'),
            secure=False)

    def upload_minio(self, object_name: str, file_path, content_type='application/text'):
        # 初始化minio
        self.mkdir(bucket=bucket)
        if self.minio_client:
            self.minio_client.fput_object(bucket_name=bucket,
                                          object_name=object_name,
                                          file_path=file_path,
                                          content_type=content_type)

    def get_share_link(self, object_name):
        # filepath "/" 开头会有nginx问题
        if object_name[0] == '/':
            object_name = object_name[1:]
        if self.minio_share:
            return self.minio_share.presigned_get_object(bucket_name=bucket,
                                                         object_name=object_name,
                                                         expires=timedelta(days=7))
        else:
            return ''

    def delete_minio(self, object_name: str):
        if self.minio_client:
            self.minio_client.remove_object(bucket_name=bucket, object_name=object_name)

    def mkdir(self, bucket: str):
        if self.minio_client:
            if not self.minio_client.bucket_exists(bucket):
                self.minio_client.make_bucket(bucket)
