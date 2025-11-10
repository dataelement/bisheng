"""
上下文管理器使用示例

展示了优化后的上下文管理器的各种使用场景和功能
"""
import asyncio
from typing import Any, Dict

from bisheng.core.context import (
    # 基础类
    BaseContextManager,
    FunctionContextManager,
    ContextState,

    # 应用管理
    initialize_app_context,
    get_context,
    async_get_instance,
    sync_get_instance,
    register_context,
    health_check,
    close_app_context,

    # 异常类
    ContextError,
    ContextInitializationError,
)


# 1. 基础使用示例
async def basic_usage_example():
    """基础使用示例"""
    print("=== 基础使用示例 ===")

    # 初始化应用上下文
    config = {
        'database': {
            'url': 'sqlite:///example.db',
            'engine_config': {'pool_size': 10}
        }
    }
    await initialize_app_context(config)

    # 获取数据库实例
    database_context = get_context('database')
    db_instance = await database_context.async_get_instance()
    print(f"Database instance: {db_instance}")

    # 检查上下文状态
    print(f"Database state: {database_context.get_state()}")
    print(f"Database info: {database_context.get_info()}")


# 2. 上下文管理器使用示例
async def context_manager_example():
    """上下文管理器使用示例"""
    print("\n=== 上下文管理器示例 ===")

    # 使用异步上下文管理器
    database_context = get_context('database')
    async with database_context.async_context() as db:
        print(f"Using database: {type(db)}")
        # 这里可以安全使用数据库实例

    # 使用同步上下文管理器
    with database_context.sync_context() as db:
        print(f"Using database (sync): {type(db)}")


# 3. 自定义上下文管理器示例
class CacheManager(BaseContextManager[Dict[str, Any]]):
    """示例：缓存管理器"""

    name = "cache"

    def __init__(self, max_size: int = 1000, **kwargs):
        super().__init__(**kwargs)
        self.max_size = max_size

    async def _async_initialize(self) -> Dict[str, Any]:
        """初始化缓存"""
        cache = {}
        print(f"Cache initialized with max_size: {self.max_size}")
        return cache

    def _sync_initialize(self) -> Dict[str, Any]:
        """同步初始化缓存"""
        cache = {}
        print(f"Cache initialized (sync) with max_size: {self.max_size}")
        return cache

    async def _async_cleanup(self) -> None:
        """清理缓存"""
        if self._instance:
            self._instance.clear()
            print("Cache cleared")

    def _sync_cleanup(self) -> None:
        """同步清理缓存"""
        if self._instance:
            self._instance.clear()
            print("Cache cleared (sync)")

    async def health_check(self) -> bool:
        """缓存健康检查"""
        try:
            instance = await self.async_get_instance()
            return isinstance(instance, dict)
        except Exception:
            return False


# 4. 函数式上下文管理器示例
async def init_redis_connection():
    """模拟 Redis 连接初始化"""
    print("Connecting to Redis...")
    await asyncio.sleep(0.1)  # 模拟网络延迟
    return {"connection": "redis://localhost:6379", "status": "connected"}


async def cleanup_redis_connection(connection):
    """模拟 Redis 连接清理"""
    print("Closing Redis connection...")
    connection["status"] = "closed"


# 5. 完整的使用示例
async def complete_example():
    """完整的使用示例"""
    print("\n=== 完整使用示例 ===")

    try:
        # 1. 注册自定义上下文管理器
        cache_manager = CacheManager(max_size=500, timeout=10.0, retry_count=2)
        register_context(
            cache_manager,
            dependencies=['database'],  # 依赖数据库
            initialize_order=20  # 在数据库之后初始化
        )

        # 2. 注册函数式上下文管理器
        redis_manager = FunctionContextManager(
            name="redis",
            init_func=init_redis_connection,
            cleanup_func=cleanup_redis_connection,
            timeout=5.0
        )
        register_context(redis_manager, initialize_order=30)

        # 3. 重新初始化以确保新注册的上下文被初始化
        await initialize_app_context()

        # 4. 获取所有上下文实例
        contexts = {
            'database': await async_get_instance('database'),
            'cache': await async_get_instance('cache'),
            'redis': await async_get_instance('redis')
        }

        print("All contexts initialized:")
        for name, instance in contexts.items():
            print(f"  {name}: {type(instance)}")

        # 5. 执行健康检查
        health_results = await health_check(include_details=True)
        print("\nHealth check results:")
        for name, result in health_results.items():
            if isinstance(result, dict):
                print(f"  {name}: healthy={result.get('healthy')}, state={result.get('state')}")
            else:
                print(f"  {name}: {result}")

        # 6. 演示错误处理
        try:
            # 尝试获取不存在的上下文
            await async_get_instance('nonexistent')
        except KeyError as e:
            print(f"\nExpected error: {e}")

        # 7. 演示重置功能
        cache_context = get_context('cache')
        print(f"\nCache state before reset: {cache_context.get_state()}")

        await cache_context.async_reset()
        print(f"Cache state after reset: {cache_context.get_state()}")

        # 重新获取会触发重新初始化
        cache_instance = await cache_context.async_get_instance()
        print(f"Cache state after re-init: {cache_context.get_state()}")

    except ContextError as e:
        print(f"Context error: {e}")
    except Exception as e:
        print(f"Unexpected error: {e}")

    finally:
        # 清理资源
        await close_app_context()
        print("\nApplication context closed")


# 6. 性能和并发测试示例
async def concurrency_example():
    """并发访问示例"""
    print("\n=== 并发访问示例 ===")

    await initialize_app_context()

    async def worker(worker_id: int):
        """工作协程"""
        try:
            # 并发获取同一个上下文实例
            db = await async_get_instance('database')
            print(f"Worker {worker_id} got database: {id(db)}")

            # 模拟一些工作
            await asyncio.sleep(0.1)
            return f"Worker {worker_id} completed"

        except Exception as e:
            return f"Worker {worker_id} failed: {e}"

    # 创建多个并发工作协程
    workers = [worker(i) for i in range(10)]
    results = await asyncio.gather(*workers)

    print("Concurrent access results:")
    for result in results:
        print(f"  {result}")

    await close_app_context()


# 7. 监控和诊断示例
async def monitoring_example():
    """监控和诊断示例"""
    print("\n=== 监控和诊断示例 ===")

    await initialize_app_context()

    # 注册一些测试上下文
    register_context(CacheManager(name="cache1"))
    register_context(CacheManager(name="cache2"))

    # 获取应用上下文信息
    from bisheng.core.context.manager import app_context
    context_info = app_context.get_context_info()

    print("Application context info:")
    print(f"  Initialized: {context_info['initialized']}")
    print(f"  Context count: {context_info['context_count']}")
    print(f"  Initialization order: {context_info['initialization_order']}")
    print(f"  Dependencies: {context_info['dependencies']}")

    # 获取各个上下文的状态
    states = context_info['context_states']
    print("\nContext states:")
    for name, state in states.items():
        print(f"  {name}: {state.value if hasattr(state, 'value') else state}")

    # 执行详细的健康检查
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


# 主函数
async def main():
    """运行所有示例"""
    print("上下文管理器优化后功能演示\n")

    await basic_usage_example()
    await context_manager_example()
    await complete_example()
    await concurrency_example()
    await monitoring_example()

    print("\n=== 所有示例运行完成 ===")


if __name__ == "__main__":
    asyncio.run(main())