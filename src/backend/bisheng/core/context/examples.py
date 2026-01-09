"""
Context Manager Usage Example

Demonstrates the various usage scenarios and features of the optimized Context Manager
"""
import asyncio
from typing import Any, Dict

from bisheng.core.context import (
    # Primary
    BaseContextManager,
    FunctionContextManager,
    ContextState,

    # Application Management
    initialize_app_context,
    get_context,
    async_get_instance,
    sync_get_instance,
    register_context,
    health_check,
    close_app_context,

    # Exception Class
    ContextError,
    ContextInitializationError,
)


# 1. Examples of basic use
async def basic_usage_example():
    """Examples of basic use"""
    print("=== Examples of basic use ===")

    # Initialize app context
    config = {
        'database': {
            'url': 'sqlite:///example.db',
            'engine_config': {'pool_size': 10}
        }
    }
    await initialize_app_context(config)

    # Get Database Instance
    database_context = get_context('database')
    db_instance = await database_context.async_get_instance()
    print(f"Database instance: {db_instance}")

    # Check context status
    print(f"Database state: {database_context.get_state()}")
    print(f"Database info: {database_context.get_info()}")


# 2. Context Manager Usage Example
async def context_manager_example():
    """Context Manager Usage Example"""
    print("\n=== Context manager example ===")

    # Using the Asynchronous Context Manager
    database_context = get_context('database')
    async with database_context.async_context() as db:
        print(f"Using database: {type(db)}")
        # Database instances are safe to use here

    # Using the Synchronization Context Manager
    with database_context.sync_context() as db:
        print(f"Using database (sync): {type(db)}")


# 3. Example of a custom context manager
class CacheManager(BaseContextManager[Dict[str, Any]]):
    """Example: Cache Manager"""

    name = "cache"

    def __init__(self, max_size: int = 1000, **kwargs):
        super().__init__(**kwargs)
        self.max_size = max_size

    async def _async_initialize(self) -> Dict[str, Any]:
        """Initialize Cache"""
        cache = {}
        print(f"Cache initialized with max_size: {self.max_size}")
        return cache

    def _sync_initialize(self) -> Dict[str, Any]:
        """Synchronous Initialization Cache"""
        cache = {}
        print(f"Cache initialized (sync) with max_size: {self.max_size}")
        return cache

    async def _async_cleanup(self) -> None:
        """Clear cache"""
        if self._instance:
            self._instance.clear()
            print("Cache cleared")

    def _sync_cleanup(self) -> None:
        """Synchronous Cleanup Cache"""
        if self._instance:
            self._instance.clear()
            print("Cache cleared (sync)")

    async def health_check(self) -> bool:
        """Cache Health Check"""
        try:
            instance = await self.async_get_instance()
            return isinstance(instance, dict)
        except Exception:
            return False


# 4. Functional context manager example
async def init_redis_connection():
    """impersonation Redis Connection Initialization"""
    print("Connecting to Redis...")
    await asyncio.sleep(0.1)  # Analog network latency
    return {"connection": "redis://localhost:6379", "status": "connected"}


async def cleanup_redis_connection(connection):
    """impersonation Redis Connection cleanup"""
    print("Closing Redis connection...")
    connection["status"] = "closed"


# 5. Complete usage examples
async def complete_example():
    """Complete usage examples"""
    print("\n=== Full Usage Example ===")

    try:
        # 1. Register Custom Context Manager
        cache_manager = CacheManager(max_size=500, timeout=10.0, retry_count=2)
        register_context(
            cache_manager,
            dependencies=['database'],  # Dependent database
            initialize_order=20  # Initialize after database
        )

        # 2. Register Functional Context Manager
        redis_manager = FunctionContextManager(
            name="redis",
            init_func=init_redis_connection,
            cleanup_func=cleanup_redis_connection,
            timeout=5.0
        )
        register_context(redis_manager, initialize_order=30)

        # 3. Reinitialize to ensure that the context of the new registration is initialized
        await initialize_app_context()

        # 4. Get all contextual instances
        contexts = {
            'database': await async_get_instance('database'),
            'cache': await async_get_instance('cache'),
            'redis': await async_get_instance('redis')
        }

        print("All contexts initialized:")
        for name, instance in contexts.items():
            print(f"  {name}: {type(instance)}")

        # 5. Perform a health check
        health_results = await health_check(include_details=True)
        print("\nHealth check results:")
        for name, result in health_results.items():
            if isinstance(result, dict):
                print(f"  {name}: healthy={result.get('healthy')}, state={result.get('state')}")
            else:
                print(f"  {name}: {result}")

        # 6. Demonstrate error handling
        try:
            # Attempt to get non-existent context
            await async_get_instance('nonexistent')
        except KeyError as e:
            print(f"\nExpected error: {e}")

        # 7. Demo Reset Function
        cache_context = get_context('cache')
        print(f"\nCache state before reset: {cache_context.get_state()}")

        await cache_context.async_reset()
        print(f"Cache state after reset: {cache_context.get_state()}")

        # Re-fetching will trigger a reinitialization
        cache_instance = await cache_context.async_get_instance()
        print(f"Cache state after re-init: {cache_context.get_state()}")

    except ContextError as e:
        print(f"Context error: {e}")
    except Exception as e:
        print(f"Unexpected error: {e}")

    finally:
        # Clean up resources
        await close_app_context()
        print("\nApplication context closed")


# 6. Examples of performance and concurrent testing
async def concurrency_example():
    """Example of concurrent access"""
    print("\n=== Example of concurrent access ===")

    await initialize_app_context()

    async def worker(worker_id: int):
        """Work corridor"""
        try:
            # Get the same context instance concurrently
            db = await async_get_instance('database')
            print(f"Worker {worker_id} got database: {id(db)}")

            # Simulate some work
            await asyncio.sleep(0.1)
            return f"Worker {worker_id} completed"

        except Exception as e:
            return f"Worker {worker_id} failed: {e}"

    # Create multiple concurrent workflows
    workers = [worker(i) for i in range(10)]
    results = await asyncio.gather(*workers)

    print("Concurrent access results:")
    for result in results:
        print(f"  {result}")

    await close_app_context()


# 7. Examples of monitoring and diagnostics
async def monitoring_example():
    """Examples of monitoring and diagnostics"""
    print("\n=== Examples of monitoring and diagnostics ===")

    await initialize_app_context()

    # Register some test contexts
    register_context(CacheManager(name="cache1"))
    register_context(CacheManager(name="cache2"))

    # Get app context
    from bisheng.core.context.manager import app_context
    context_info = app_context.get_context_info()

    print("Application context info:")
    print(f"  Initialized: {context_info['initialized']}")
    print(f"  Context count: {context_info['context_count']}")
    print(f"  Initialization order: {context_info['initialization_order']}")
    print(f"  Dependencies: {context_info['dependencies']}")

    # Get the status of each context
    states = context_info['context_states']
    print("\nContext states:")
    for name, state in states.items():
        print(f"  {name}: {state.value if hasattr(state, 'value') else state}")

    # Perform detailed health checks
    detailed_health = await health_check(include_details=True)
    print("\nDetailed health check:")
    for name, details in detailed_health.items():
        if isinstance(details, dict):
            print(f"  {name}:")
            print(f"    Healthy: {details.get('healthy')}")
            print(f"    State: {details.get('state')}")
            print(f"    Error: {details.get('error', 'None')}")
        else:
            print(f"  {name}: {details}")

    await close_app_context()


# The main function.
async def main():
    """Run all examples"""
    print("Post Context Manager Optimization Demo\n")

    await basic_usage_example()
    await context_manager_example()
    await complete_example()
    await concurrency_example()
    await monitoring_example()

    print("\n=== All sample runs completed ===")


if __name__ == "__main__":
    asyncio.run(main())