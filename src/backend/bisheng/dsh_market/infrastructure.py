from .domain.repository import MarketRepository
from .domain.service import MarketService


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
