"""App Context Manager

Global context manager with integrated lazy loading and caching
Provides easy dependency injection and lifecycle management
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
    """App Context Manager

    Responsible for managing the entire application infrastructure service lifecycle and providing a unified access interface
    Supports dependency injection, bulk operations, and health checks
    """

    def __init__(self):
        self._registry = ContextRegistry()
        self._initialized = False
        self._initialization_lock = asyncio.Lock()
        self._initialization_order: List[str] = []
        self._dependencies: Dict[str, List[str]] = {}

    async def initialize(self, config: Settings) -> None:
        """Initialize app context

        Args:
            config: Optional configuration dictionary for passing to individual context managers

        Raises:
            ContextError: Thrown on initialization failure
        """
        async with self._initialization_lock:
            if self._initialized:
                logger.debug("Application context already initialized")
                return

            try:
                # Register default context manager
                self._register_default_contexts(config or {})

                # Initialize all contexts in dependency order
                await self._initialize_contexts_in_order()

                self._initialized = True
                logger.info("Application context initialized successfully")

            except Exception as e:
                logger.exception(f"Failed to initialize application context: {e}")
                # Clean Up Initialized Resources
                await self.async_close()
                raise ContextError(f"Application context initialization failed: {e}") from e

    def _register_default_contexts(self, config: Settings) -> None:
        """Register default context manager"""
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
            self.register_context(EsConnManager(es_hosts=config.get_telemetry_conf().elasticsearch_url,
                                                name=statistics_es_name,
                                                **config.get_telemetry_conf().ssl_verify))

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
        """Initialize context in dependency order"""
        # If no initialization order is defined, initialize in registration order
        if not self._initialization_order:
            self._initialization_order = list(self._registry.get_all_contexts().keys())

        initialized = set()

        for context_name in self._initialization_order:
            if context_name not in initialized:
                await self._initialize_context_with_dependencies(context_name, initialized)

    async def _initialize_context_with_dependencies(self, context_name: str, initialized: set) -> None:
        """Recursive initialization context and its dependencies"""
        if context_name in initialized:
            return

        # Initialize dependencies first
        dependencies = self._dependencies.get(context_name, [])
        for dep_name in dependencies:
            if dep_name not in initialized:
                await self._initialize_context_with_dependencies(dep_name, initialized)

        # Then initialize the current context
        try:
            context = self._registry.get_context(context_name)
            await context.async_get_instance()  # This will trigger initialization
            initialized.add(context_name)
            logger.debug(f"Initialized context: '{context_name}'")
        except Exception as e:
            logger.error(f"Failed to initialize context '{context_name}': {e}")
            raise

    async def async_get_instance(self, name: str) -> T:
        """Gets the context instance of the specified name asynchronously"""
        context = self.get_context(name)
        return await context.async_get_instance()

    def sync_get_instance(self, name: str) -> T:
        """Synchronously get a contextual instance of the specified name"""
        context = self.get_context(name)
        return context.sync_get_instance()

    def get_context(self, name: str) -> BaseContextManager:
        """Gets the context instance of the specified name"""
        return self._registry.get_context(name)

    def register_context(
            self,
            context: BaseContextManager,
            dependencies: Optional[List[str]] = None,
            initialize_order: Optional[int] = None
    ) -> None:
        """Register a new context manager

        Args:
            context: Context manager to register
            dependencies: A list of other context names that the context depends on
            initialize_order: Initialization order (smaller numbers initialize earlier)

        Raises:
            ValueError: If the context name already exists
        """
        self._registry.register(context)

        # Record dependencies
        if dependencies:
            self._dependencies[context.name] = dependencies

        # Update initialization order
        if initialize_order is not None:
            # Insert to Specified Location
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
        """Log out of the context manager"""
        self._registry.unregister(name)

    async def health_check(self, include_details: bool = False) -> Union[Dict[str, bool], Dict[str, Dict[str, Any]]]:
        """Perform a health check

        Args:
            include_details: Does it contain detailed health check information?

        Returns:
            Union[Dict[str, bool], Dict[str, Dict[str, Any]]]: Health Check Results
        """
        results = await self._registry.health_check()

        if not include_details:
            return results

        # Include details
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
        """Close app context

        Close all contexts in reverse order from initialization
        """
        if not self._initialized:
            return

        try:
            # Close context in reverse order to ensure dependencies are handled correctly
            await self._close_contexts_in_reverse_order()

            # Cleanup status
            self._initialized = False
            self._initialization_order.clear()
            self._dependencies.clear()

            logger.info("Application context closed successfully")
        except Exception as e:
            logger.error(f"Error closing application context: {e}")
            raise

    async def _close_contexts_in_reverse_order(self) -> None:
        """Close all contexts in reverse order"""
        close_order = list(reversed(self._initialization_order))

        for context_name in close_order:
            try:
                if self._registry.has_context(context_name):
                    context = self._registry.get_context(context_name)
                    await context.async_close()
                    logger.debug(f"Closed context: '{context_name}'")
            except Exception as e:
                logger.error(f"Error closing context '{context_name}': {e}")

        # Ensure all contexts are closed
        await self._registry.async_close_all()

    def is_initialized(self) -> bool:
        """Check if initialized"""
        return self._initialized

    def get_registry(self) -> ContextRegistry:
        """Get Context Registry

        Returns:
            ContextRegistry: Context Registry Instance
        """
        return self._registry

    def get_context_info(self) -> Dict[str, Any]:
        """Get app context details

        Returns:
            Dict[str, Any]: Dictionary with app context details
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
        """Synchronize context manager for batch fetching multiple contexts

        Args:
            *context_names: List of context names to get

        Example:
            with app_context.sync_context('database', 'cache') as (db, cache):
                # Use db And cache
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
            # Note: This does not close automatically as it may be used elsewhere
            pass

    @asynccontextmanager
    async def async_context(self, *context_names: str):
        """Asynchronous context manager for batch fetching multiple contexts

        Args:
            *context_names: List of context names to get

        Example:
            async with app_context.async_context('database', 'cache') as (db, cache):
                # Use db And cache
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
            # Note: This does not close automatically as it may be used elsewhere
            pass

    async def reset_context(self, context_name: str) -> None:
        """Reset Specified Context

        Args:
            context_name: Context name to reset

        Raises:
            KeyError: If the context does not exist
        """
        context = self._registry.get_context(context_name)
        await context.async_reset()
        logger.info(f"Context '{context_name}' reset successfully")

    async def restart_context(self, context_name: str) -> None:
        """Restart the specified context (initialize immediately after reset)

        Args:
            context_name: Context name to restart

        Raises:
            KeyError: If the context does not exist
        """
        await self.reset_context(context_name)
        await self.async_get_instance(context_name)  # Trigger reinitialization
        logger.info(f"Context '{context_name}' restarted successfully")

    def list_contexts(self, state_filter: Optional[ContextState] = None) -> List[str]:
        """List all context names

        Args:
            state_filter: Optional status filter that returns only the context of the specified status

        Returns:
            List[str]: Context Name List
        """
        if state_filter is None:
            return list(self._registry.get_all_contexts().keys())

        return [
            name for name, context in self._registry.get_all_contexts().items()
            if context.get_state() == state_filter
        ]


# Global App Context Instance
app_context = ApplicationContextManager()


async def initialize_app_context(config: Settings) -> None:
    """
    Initialize global app context
    :param config:
    :return:
    """

    await app_context.initialize(config)


def get_context(name: str) -> BaseContextManager:
    """Convenient way to get context

    Args:
        name: Context Name

    Returns:
        BaseContextManager: Corresponding context manager

    Raises:
        KeyError: If the context does not exist
    """
    return app_context.get_context(name)


async def async_get_instance(name: str) -> Any:
    """Convenient way to get contextual instances asynchronously

    Args:
        name: Context Name

    Returns:
        Any: Contextual instances

    Raises:
        KeyError: If the context does not exist
        ContextError: If initialization fails
    """
    return await app_context.async_get_instance(name)


def sync_get_instance(name: str) -> Any:
    """Convenient way to get contextual instances synchronously

    Args:
        name: Context Name

    Returns:
        Any: Contextual instances

    Raises:
        KeyError: If the context does not exist
        ContextError: If initialization fails
    """
    return app_context.sync_get_instance(name)


async def close_app_context() -> None:
    """Convenient way to turn off global app context"""
    await app_context.async_close()


def register_context(
        context: BaseContextManager,
        dependencies: Optional[List[str]] = None,
        initialize_order: Optional[int] = None
) -> None:
    """Convenient way to register a context

    Args:
        context: Context manager to register
        dependencies: A list of other context names that the context depends on
        initialize_order: Initialization order (smaller numbers initialize earlier)

    Example:
        # Register a cache context that depends on the database
        register_context(cache_manager, dependencies=['database'], initialize_order=10)
    """
    app_context.register_context(context, dependencies, initialize_order)


async def health_check(include_details: bool = False) -> Union[Dict[str, bool], Dict[str, Dict[str, Any]]]:
    """Convenient way to perform a health check

    Args:
        include_details: Does it contain detailed health check information?

    Returns:
        Union[Dict[str, bool], Dict[str, Dict[str, Any]]]: Health Check Results
    """
    return await app_context.health_check(include_details)
