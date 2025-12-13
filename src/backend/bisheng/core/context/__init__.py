
"""应用上下文管理模块

提供通用的上下文管理框架，包括：
- 线程安全的懒加载机制
- 自动缓存和实例生命周期管理
- 依赖注入和初始化顺序控制
- 重试机制和超时处理
- 健康检查和监控功能
- 便捷的上下文管理器支持

使用示例：
    # 基本使用
    from bisheng.core.context import initialize_app_context, get_context

    await initialize_app_context()
    db = await get_context('database').async_get_instance()

    # 使用上下文管理器
    async with get_context('database').async_context() as db:
        # 使用 db
        pass
"""

from .base import (
    # 核心类和状态
    BaseContextManager,
    FunctionContextManager,
    ContextRegistry,
    ContextState,

    # 异常类
    ContextError,
    ContextInitializationError,
    ContextTimeoutError,
    ContextStateError,
)
from .manager import (
    # 应用管理器
    ApplicationContextManager,
    app_context,

    # 初始化和生命周期管理
    initialize_app_context,
    close_app_context,

    # 上下文访问和管理
    get_context,
    async_get_instance,
    sync_get_instance,
    register_context,

    # 监控和诊断
    health_check,
)

__all__ = [
    # 核心基类和状态
    'BaseContextManager',
    'FunctionContextManager',
    'ContextRegistry',
    'ContextState',

    # 异常类
    'ContextError',
    'ContextInitializationError',
    'ContextTimeoutError',
    'ContextStateError',

    # 应用管理器
    'ApplicationContextManager',
    'app_context',

    # 生命周期管理
    'initialize_app_context',
    'close_app_context',

    # 上下文访问和管理
    'get_context',
    'async_get_instance',
    'sync_get_instance',
    'register_context',

    # 监控和诊断
    'health_check',
]