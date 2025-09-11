from abc import ABC, abstractmethod
from datetime import timedelta
from typing import Any

from loguru import logger
from minio import Minio


class BaseExecutor(ABC):
    def __init__(self, minio: dict, **kwargs):
        self.minio = minio

    @abstractmethod
    def run(self, code: str) -> Any:
        raise NotImplementedError()

    def upload_minio(
            self,
            object_name: str,
            file_path,
    ):
        # 初始化minio

        minio_client = Minio(
            endpoint=self.minio.get('endpoint'),
            access_key=self.minio.get('access_key'),
            secret_key=self.minio.get('secret_key'),
            secure=self.minio.get('schema'),
            cert_check=self.minio.get('cert_check'),
        )
        minio_share = Minio(
            endpoint=self.minio.get('sharepoint'),
            access_key=self.minio.get('access_key'),
            secret_key=self.minio.get('secret_key'),
            secure=self.minio.get('share_schema', False),
            cert_check=self.minio.get('share_cert_check', False),
        )
        bucket = self.minio.get('tmp_bucket', 'tmp-dir')
        logger.debug(
            'upload_file obj={} bucket={} file_paht={}',
            object_name,
            bucket,
            file_path,
        )
        minio_client.fput_object(
            bucket_name=bucket,
            object_name=object_name,
            file_path=file_path,
        )
        return minio_share.presigned_get_object(
            bucket_name=bucket,
            object_name=object_name,
            expires=timedelta(days=7),
        )

    def close(self) -> None:
        pass
