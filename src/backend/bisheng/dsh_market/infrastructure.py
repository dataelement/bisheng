from .domain.repository import MarketRepository
from .domain.service import MarketService
from .domain.workbench_repository import WorkbenchRepository
from .domain.workbench_service import WorkbenchService


async def tenant_is_active(tenant_id):
    from bisheng.database.models.tenant import TenantDao

    tenant = await TenantDao.aget_by_id(tenant_id)
    return tenant is not None and tenant.status == "active"


class MarketStorage:
    @property
    def client(self):
        from bisheng.core.storage.minio.minio_manager import get_minio_storage_sync

        return get_minio_storage_sync()

    def put(self, tenant, digest, data):
        client = self.client
        client.put_object_sync(bucket_name=client.bucket, object_name=f"dsh-market/{tenant}/{digest}.zip", file=data)

    def get(self, tenant, digest):
        client = self.client
        return client.get_object_sync(bucket_name=client.bucket, object_name=f"dsh-market/{tenant}/{digest}.zip")


def get_market_service():
    from bisheng.core.database import get_sync_db_session

    return MarketService(MarketRepository(get_sync_db_session), MarketStorage())


class WorkbenchStorage:
    @property
    def client(self):
        from bisheng.core.storage.minio.minio_manager import get_minio_storage_sync

        return get_minio_storage_sync()

    def put(self, tenant, digest, data):
        client = self.client
        client.put_object_sync(
            bucket_name=client.bucket, object_name=f"dsh-market/workbenches/{tenant}/{digest}.tgz", file=data
        )

    def get(self, tenant, digest):
        client = self.client
        try:
            return client.get_object_sync(
                bucket_name=client.bucket, object_name=f"dsh-market/workbenches/{tenant}/{digest}.tgz"
            )
        except Exception as exc:
            from minio.error import S3Error

            if isinstance(exc, S3Error) and exc.code == "NoSuchKey":
                raise FileNotFoundError("Workbench artifact missing") from exc
            raise


def get_workbench_service():
    from bisheng.core.database import get_sync_db_session

    return WorkbenchService(WorkbenchRepository(get_sync_db_session), WorkbenchStorage())
