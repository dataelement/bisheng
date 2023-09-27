from datetime import timedelta

import minio
from bisheng.settings import settings

bucket = 'bisheng'

minio_share = minio.Minio(endpoint=settings.knowledges.get('minio').get('MINIO_SHAREPOIN'),
                          access_key=settings.knowledges.get('minio').get('MINIO_ACCESS_KEY'),
                          secret_key=settings.knowledges.get('minio').get('MINIO_SECRET_KEY'),
                          secure=False)
minio_client = minio.Minio(endpoint=settings.knowledges.get('minio').get('MINIO_ENDPOINT'),
                           access_key=settings.knowledges.get('minio').get('MINIO_ACCESS_KEY'),
                           secret_key=settings.knowledges.get('minio').get('MINIO_SECRET_KEY'),
                           secure=False)


def upload_minio(object_name: str, file_path, content_type='application/text'):
    minio_client.fput_object(bucket_name=bucket,
                             object_name=object_name,
                             file_path=file_path,
                             content_type=content_type)


def get_share_link(object_name):
    # filepath "/" 开头会有nginx问题
    if object_name[0] == '/':
        object_name = object_name[1:]

    return minio_share.presigned_get_object(bucket_name=bucket,
                                            object_name=object_name,
                                            expires=timedelta(days=7))


def delete_minio(object_name: str):
    minio_client.remove_object(bucket_name=bucket, object_name=object_name)
