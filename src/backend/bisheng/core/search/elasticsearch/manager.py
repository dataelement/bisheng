import logging

from elasticsearch import AsyncElasticsearch, Elasticsearch

from bisheng.core.context import BaseContextManager
from bisheng.core.search.elasticsearch.es_connection import ESConnection

logger = logging.getLogger(__name__)

statistics_es_name = "statistics_elasticsearch"


class EsConnManager((BaseContextManager[ESConnection])):
    name: str = "elasticsearch"

    def __init__(self, es_hosts: str, name: str = None, **kwargs):

        if name:
            self.name = name

        super().__init__(self.name, **kwargs)
        self.es_hosts = es_hosts
        self.kwargs = kwargs

    async def _async_initialize(self) -> ESConnection:
        """Inisialisasi Elasticsearch Connection Manager"""
        return ESConnection(self.es_hosts, **self.kwargs)

    def _sync_initialize(self) -> ESConnection:
        """Synchronization Initialization"""
        return ESConnection(self.es_hosts, **self.kwargs)

    async def _async_cleanup(self) -> None:
        """Cleaned Elasticsearch reasourse"""
        if self._instance:
            await self._instance.close()

    def _sync_cleanup(self) -> None:
        """Synchronous Cleanup Elasticsearch reasourse"""
        if self._instance:
            self._instance.sync_close()


async def get_es_connection() -> AsyncElasticsearch:
    """Dapatkan Elasticsearch Connection Instance"""
    from bisheng.core.context.manager import app_context
    try:
        return (await app_context.async_get_instance(EsConnManager.name)).es_connection
    except KeyError:
        logger.warning(f"EsConnManager not found in app_context. Registering a new instance.")
        try:
            from bisheng.common.services.config_service import settings
            app_context.register_context(
                EsConnManager(es_hosts=settings.get_telemetry_conf().elasticsearch_url,
                              **settings.get_telemetry_conf().ssl_verify
                              ))
            return (await app_context.async_get_instance(EsConnManager.name)).es_connection
        except Exception as e:
            logger.error(f"Failed to register EsConnManager: {e}")
            raise KeyError(f"EsConnManager not found in app_context and failed to register a new instance.") from e


async def get_statistics_es_connection() -> AsyncElasticsearch:
    """Get statistics Elasticsearch Connection Instance"""
    from bisheng.core.context.manager import app_context
    try:
        return (await app_context.async_get_instance(statistics_es_name)).es_connection
    except KeyError:
        logger.warning(f"Statistics EsConnManager not found in app_context. Registering a new instance.")
        try:
            from bisheng.common.services.config_service import settings

            app_context.register_context(
                EsConnManager(es_hosts=settings.get_telemetry_conf().elasticsearch_url,
                              name=statistics_es_name,
                              **settings.get_telemetry_conf().statistics_ssl_verify))
            return (await app_context.async_get_instance(statistics_es_name)).es_connection
        except Exception as e:
            logger.error(f"Failed to register Statistics EsConnManager: {e}")
            raise KeyError(
                f"Statistics EsConnManager not found in app_context and failed to register a new instance.") from e


def get_es_connection_sync() -> Elasticsearch:
    """Synchronous fetch Elasticsearch Connection Instance"""
    from bisheng.core.context.manager import app_context
    try:
        return app_context.sync_get_instance(EsConnManager.name).sync_es_connection
    except KeyError:
        logger.warning(f"EsConnManager not found in app_context. Registering a new instance.")
        try:
            from bisheng.common.services.config_service import settings
            app_context.register_context(
                EsConnManager(es_hosts=settings.get_telemetry_conf().elasticsearch_url,
                              **settings.get_telemetry_conf().ssl_verify
                              ))
            return app_context.sync_get_instance(EsConnManager.name).sync_es_connection
        except Exception as e:
            logger.error(f"Failed to register EsConnManager: {e}")
            raise KeyError(f"EsConnManager not found in app_context and failed to register a new instance.") from e


def get_statistics_es_connection_sync() -> Elasticsearch:
    """Sync Fetch Stats Elasticsearch Connection Instance"""
    from bisheng.core.context.manager import app_context
    try:
        return app_context.sync_get_instance(statistics_es_name).sync_es_connection
    except KeyError:
        logger.warning(f"Statistics EsConnManager not found in app_context. Registering a new instance.")
        try:
            from bisheng.common.services.config_service import settings

            app_context.register_context(
                EsConnManager(es_hosts=settings.get_telemetry_conf().elasticsearch_url,
                              name=statistics_es_name,
                              **settings.get_telemetry_conf().ssl_verify))
            return app_context.sync_get_instance(statistics_es_name).sync_es_connection
        except Exception as e:
            logger.error(f"Failed to register Statistics EsConnManager: {e}")
            raise KeyError(
                f"Statistics EsConnManager not found in app_context and failed to register a new instance.") from e
