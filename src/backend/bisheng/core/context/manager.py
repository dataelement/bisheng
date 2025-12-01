"""应用上下文管理器

集成了懒加载、缓存机制的全局上下文管理器
提供便捷的依赖注入和生命周期管理功能
"""
import asyncio
from contextlib import asynccontextmanager, contextmanager
from typing import Optional, Dict, Any, TypeVar, List, Union

from loguru import logger

from bisheng.core.config.settings import Settings
from bisheng.core.context.base import (
    ContextRegistry,
    BaseContextManager,
    ContextState,
    ContextError
)

T = TypeVar('T')


class ApplicationContextManager:
    """应用上下文管理器

    负责管理整个应用的基础设施服务生命周期，提供统一的访问接口
    支持依赖注入、批量操作和健康检查功能
    """

    def __init__(self):
        self._registry = ContextRegistry()
        self._initialized = False
        self._initialization_lock = asyncio.Lock()
        self._initialization_order: List[str] = []
        self._dependencies: Dict[str, List[str]] = {}

    async def initialize(self, config: Settings) -> None:
        """初始化应用上下文

        Args:
            config: 可选的配置字典，用于传递给各个上下文管理器

        Raises:
            ContextError: 初始化失败时抛出
        """
        async with self._initialization_lock:
            if self._initialized:
                logger.debug("Application context already initialized")
                return

            try:
                # 注册默认的上下文管理器
                self._register_default_contexts(config or {})

                # 按依赖顺序初始化所有上下文
                await self._initialize_contexts_in_order()

                self._initialized = True
                logger.info("Application context initialized successfully")

            except Exception as e:
                logger.exception(f"Failed to initialize application context: {e}")
                # 清理已初始化的资源
                await self.async_close()
                raise ContextError(f"Application context initialization failed: {e}") from e

    def _register_default_contexts(self, config: Settings) -> None:
        """注册默认的上下文管理器"""
        try:

            from bisheng.core.database.manager import DatabaseManager
            self.register_context(DatabaseManager(database_url=config.database_url))

            from bisheng.core.cache.redis_manager import RedisManager
            self.register_context(RedisManager(redis_url=config.redis_url))

            from bisheng.core.storage.minio.minio_manager import MinioManager
            self.register_context(MinioManager(minio_config=config.object_storage.minio))

            from bisheng.core.search.elasticsearch.manager import EsConnManager, statistics_es_name
            self.register_context(EsConnManager(es_hosts=config.get_search_conf().elasticsearch_url,
                                                **config.get_search_conf().ssl_verify))
            self.register_context(EsConnManager(es_hosts=config.get_search_conf().statistics_elasticsearch_url,
                                                name=statistics_es_name,
                                                **config.get_search_conf().statistics_ssl_verify))

            from bisheng.core.external.http_client.http_client_manager import HttpClientManager
            self.register_context(HttpClientManager())

            from bisheng.core.prompts.manager import PromptManager
            self.register_context(PromptManager())

            logger.debug("Default contexts registered")
        except ImportError as e:
            logger.warning(f"Failed to import default context managers: {e}")
        except Exception as e:
            logger.error(f"Failed to register default contexts: {e}")
            raise

    async def _initialize_contexts_in_order(self) -> None:
        """按依赖顺序初始化上下文"""
        # 如果没有定义初始化顺序，则按注册顺序初始化
        if not self._initialization_order:
            self._initialization_order = list(self._registry.get_all_contexts().keys())

        initialized = set()

        for context_name in self._initialization_order:
            if context_name not in initialized:
                await self._initialize_context_with_dependencies(context_name, initialized)

    async def _initialize_context_with_dependencies(self, context_name: str, initialized: set) -> None:
        """递归初始化上下文及其依赖"""
        if context_name in initialized:
            return

        # 先初始化依赖
        dependencies = self._dependencies.get(context_name, [])
        for dep_name in dependencies:
            if dep_name not in initialized:
                await self._initialize_context_with_dependencies(dep_name, initialized)

        # 然后初始化当前上下文
        try:
            context = self._registry.get_context(context_name)
            await context.async_get_instance()  # 这会触发初始化
            initialized.add(context_name)
            logger.debug(f"Initialized context: '{context_name}'")
        except Exception as e:
            logger.error(f"Failed to initialize context '{context_name}': {e}")
            raise

    async def async_get_instance(self, name: str) -> T:
        """异步获取指定名称的上下文实例"""
        context = self.get_context(name)
        return await context.async_get_instance()

    def sync_get_instance(self, name: str) -> T:
        """同步获取指定名称的上下文实例"""
        context = self.get_context(name)
        return context.sync_get_instance()

    def get_context(self, name: str) -> BaseContextManager:
        """获取指定名称的上下文实例"""
        return self._registry.get_context(name)

    def register_context(
            self,
            context: BaseContextManager,
            dependencies: Optional[List[str]] = None,
            initialize_order: Optional[int] = None
    ) -> None:
        """注册新的上下文管理器

        Args:
            context: 要注册的上下文管理器
            dependencies: 该上下文依赖的其他上下文名称列表
            initialize_order: 初始化顺序（数字越小越早初始化）

        Raises:
            ValueError: 如果上下文名称已存在
        """
        self._registry.register(context)

        # 记录依赖关系
        if dependencies:
            self._dependencies[context.name] = dependencies

        # 更新初始化顺序
        if initialize_order is not None:
            # 插入到指定位置
            if context.name in self._initialization_order:
                self._initialization_order.remove(context.name)

            insert_pos = 0
            for i, existing_name in enumerate(self._initialization_order):
                existing_context = self._registry.get_context(existing_name)
                if getattr(existing_context, '_initialize_order', float('inf')) > initialize_order:
                    insert_pos = i
                    break
                insert_pos = i + 1

            self._initialization_order.insert(insert_pos, context.name)
            context._initialize_order = initialize_order
        elif context.name not in self._initialization_order:
            self._initialization_order.append(context.name)

        logger.debug(f"Registered context '{context.name}' with dependencies: {dependencies or []}")

    def unregister_context(self, name: str) -> None:
        """注销上下文管理器"""
        self._registry.unregister(name)

    async def health_check(self, include_details: bool = False) -> Union[Dict[str, bool], Dict[str, Dict[str, Any]]]:
        """执行健康检查

        Args:
            include_details: 是否包含详细的健康检查信息

        Returns:
            Union[Dict[str, bool], Dict[str, Dict[str, Any]]]: 健康检查结果
        """
        results = await self._registry.health_check()

        if not include_details:
            return results

        # 包含详细信息
        detailed_results = {}
        for name, is_healthy in results.items():
            try:
                context = self._registry.get_context(name)
                detailed_results[name] = {
                    'healthy': is_healthy,
                    'state': context.get_state().value,
                    'error': str(context.get_error()) if context.get_error() else None,
                    'info': context.get_info() if hasattr(context, 'get_info') else {}
                }
            except Exception as e:
                detailed_results[name] = {
                    'healthy': False,
                    'error': f"Failed to get context info: {e}"
                }

        return detailed_results

    async def async_close(self) -> None:
        """关闭应用上下文

        按与初始化相反的顺序关闭所有上下文
        """
        if not self._initialized:
            return

        try:
            # 按相反顺序关闭上下文以确保依赖关系正确处理
            await self._close_contexts_in_reverse_order()

            # 清理状态
            self._initialized = False
            self._initialization_order.clear()
            self._dependencies.clear()

            logger.info("Application context closed successfully")
        except Exception as e:
            logger.error(f"Error closing application context: {e}")
            raise

    async def _close_contexts_in_reverse_order(self) -> None:
        """按相反顺序关闭所有上下文"""
        close_order = list(reversed(self._initialization_order))

        for context_name in close_order:
            try:
                if self._registry.has_context(context_name):
                    context = self._registry.get_context(context_name)
                    await context.async_close()
                    logger.debug(f"Closed context: '{context_name}'")
            except Exception as e:
                logger.error(f"Error closing context '{context_name}': {e}")

        # 确保所有上下文都被关闭
        await self._registry.async_close_all()

    def is_initialized(self) -> bool:
        """检查是否已初始化"""
        return self._initialized

    def get_registry(self) -> ContextRegistry:
        """获取上下文注册表

        Returns:
            ContextRegistry: 上下文注册表实例
        """
        return self._registry

    def get_context_info(self) -> Dict[str, Any]:
        """获取应用上下文的详细信息

        Returns:
            Dict[str, Any]: 包含应用上下文详细信息的字典
        """
        return {
            'initialized': self._initialized,
            'context_count': len(self._registry),
            'initialization_order': self._initialization_order.copy(),
            'dependencies': self._dependencies.copy(),
            'context_states': self._registry.get_context_states()
        }

    @contextmanager
    def sync_context(self, *context_names: str):
        """同步上下文管理器，用于批量获取多个上下文

        Args:
            *context_names: 要获取的上下文名称列表

        Example:
            with app_context.sync_context('database', 'cache') as (db, cache):
                # 使用 db 和 cache
                pass
        """
        instances = []
        try:
            for name in context_names:
                instance = self.sync_get_instance(name)
                instances.append(instance)

            if len(instances) == 1:
                yield instances[0]
            else:
                yield tuple(instances)
        finally:
            # 注意：这里不自动关闭，因为可能被其他地方使用
            pass

    @asynccontextmanager
    async def async_context(self, *context_names: str):
        """异步上下文管理器，用于批量获取多个上下文

        Args:
            *context_names: 要获取的上下文名称列表

        Example:
            async with app_context.async_context('database', 'cache') as (db, cache):
                # 使用 db 和 cache
                pass
        """
        instances = []
        try:
            for name in context_names:
                instance = await self.async_get_instance(name)
                instances.append(instance)

            if len(instances) == 1:
                yield instances[0]
            else:
                yield tuple(instances)
        finally:
            # 注意：这里不自动关闭，因为可能被其他地方使用
            pass

    async def reset_context(self, context_name: str) -> None:
        """重置指定的上下文

        Args:
            context_name: 要重置的上下文名称

        Raises:
            KeyError: 如果上下文不存在
        """
        context = self._registry.get_context(context_name)
        await context.async_reset()
        logger.info(f"Context '{context_name}' reset successfully")

    async def restart_context(self, context_name: str) -> None:
        """重启指定的上下文（重置后立即初始化）

        Args:
            context_name: 要重启的上下文名称

        Raises:
            KeyError: 如果上下文不存在
        """
        await self.reset_context(context_name)
        await self.async_get_instance(context_name)  # 触发重新初始化
        logger.info(f"Context '{context_name}' restarted successfully")

    def list_contexts(self, state_filter: Optional[ContextState] = None) -> List[str]:
        """列出所有上下文名称

        Args:
            state_filter: 可选的状态过滤器，只返回指定状态的上下文

        Returns:
            List[str]: 上下文名称列表
        """
        if state_filter is None:
            return list(self._registry.get_all_contexts().keys())

        return [
            name for name, context in self._registry.get_all_contexts().items()
            if context.get_state() == state_filter
        ]


# 全局应用上下文实例
app_context = ApplicationContextManager()


async def initialize_app_context(config: Settings) -> None:
    """
    初始化全局应用上下文
    :param config:
    :return:
    """

    await app_context.initialize(config)


def get_context(name: str) -> BaseContextManager:
    """获取上下文的便捷方法

    Args:
        name: 上下文名称

    Returns:
        BaseContextManager: 对应的上下文管理器

    Raises:
        KeyError: 如果上下文不存在
    """
    return app_context.get_context(name)


async def async_get_instance(name: str) -> Any:
    """异步获取上下文实例的便捷方法

    Args:
        name: 上下文名称

    Returns:
        Any: 上下文实例

    Raises:
        KeyError: 如果上下文不存在
        ContextError: 如果初始化失败
    """
    return await app_context.async_get_instance(name)


def sync_get_instance(name: str) -> Any:
    """同步获取上下文实例的便捷方法

    Args:
        name: 上下文名称

    Returns:
        Any: 上下文实例

    Raises:
        KeyError: 如果上下文不存在
        ContextError: 如果初始化失败
    """
    return app_context.sync_get_instance(name)


async def close_app_context() -> None:
    """关闭全局应用上下文的便捷方法"""
    await app_context.async_close()


def register_context(
        context: BaseContextManager,
        dependencies: Optional[List[str]] = None,
        initialize_order: Optional[int] = None
) -> None:
    """注册上下文的便捷方法

    Args:
        context: 要注册的上下文管理器
        dependencies: 该上下文依赖的其他上下文名称列表
        initialize_order: 初始化顺序（数字越小越早初始化）

    Example:
        # 注册一个依赖数据库的缓存上下文
        register_context(cache_manager, dependencies=['database'], initialize_order=10)
    """
    app_context.register_context(context, dependencies, initialize_order)


async def health_check(include_details: bool = False) -> Union[Dict[str, bool], Dict[str, Dict[str, Any]]]:
    """执行健康检查的便捷方法

    Args:
        include_details: 是否包含详细的健康检查信息

    Returns:
        Union[Dict[str, bool], Dict[str, Dict[str, Any]]]: 健康检查结果
    """
    return await app_context.health_check(include_details)
