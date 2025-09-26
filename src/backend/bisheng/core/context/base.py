import asyncio
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, TypeVar, Generic, Callable, Awaitable, Union
from enum import Enum
from threading import Lock, Event
from contextlib import asynccontextmanager, contextmanager

from bisheng.utils.logger import logger

T = TypeVar('T')


class ContextState(Enum):
    """上下文状态枚举"""
    UNINITIALIZED = "uninitialized"  # 未初始化
    INITIALIZING = "initializing"  # 初始化中
    READY = "ready"  # 已就绪
    ERROR = "error"  # 错误状态
    CLOSING = "closing"  # 关闭中
    CLOSED = "closed"  # 已关闭


class ContextError(Exception):
    """上下文相关异常基类"""
    pass


class ContextInitializationError(ContextError):
    """上下文初始化异常"""
    pass


class ContextTimeoutError(ContextError):
    """上下文操作超时异常"""
    pass


class ContextStateError(ContextError):
    """上下文状态异常"""
    pass


class BaseContextManager(ABC, Generic[T]):
    """基础上下文管理器抽象类

    定义了所有上下文管理器必须实现的接口
    提供线程安全的懒加载、缓存和生命周期管理
    """

    name: str
    _default_timeout: float = 30.0  # 默认超时时间
    _default_retry_count: int = 3   # 默认重试次数

    def __init__(self, name: str = None, timeout: float = None, retry_count: int = None):
        self.name = name or getattr(self.__class__, 'name', self.__class__.__name__.lower())
        self.timeout = timeout or self._default_timeout
        self.retry_count = retry_count or self._default_retry_count

        self.state = ContextState.UNINITIALIZED
        self._instance: Optional[T] = None
        self._error: Optional[Exception] = None

        # 同步和异步锁
        self._sync_lock = Lock()
        self._async_lock = asyncio.Lock()

        # 同步等待事件
        self._sync_ready_event = Event()
        self._async_ready_event = asyncio.Event()

    @abstractmethod
    async def _async_initialize(self) -> T:
        """异步初始化资源（抽象方法）"""
        pass

    @abstractmethod
    def _sync_initialize(self) -> T:
        """同步初始化资源（抽象方法）"""
        pass

    @abstractmethod
    async def _async_cleanup(self) -> None:
        """异步清理资源（抽象方法）"""
        pass

    @abstractmethod
    def _sync_cleanup(self) -> None:
        """同步清理资源（抽象方法）"""
        pass

    def _validate_state_for_access(self) -> None:
        """验证状态是否允许访问实例"""
        if self.state == ContextState.ERROR:
            error_msg = f"Context '{self.name}' is in error state"
            if self._error:
                error_msg += f": {self._error}"
            raise ContextStateError(error_msg)

        if self.state == ContextState.CLOSED:
            raise ContextStateError(f"Context '{self.name}' is closed and cannot be accessed")

    async def _wait_for_initialization_async(self) -> None:
        """异步等待初始化完成"""
        try:
            await asyncio.wait_for(self._async_ready_event.wait(), timeout=self.timeout)
        except asyncio.TimeoutError:
            raise ContextTimeoutError(f"Context '{self.name}' initialization timeout after {self.timeout}s")

    def _wait_for_initialization_sync(self) -> None:
        """同步等待初始化完成"""
        if not self._sync_ready_event.wait(timeout=self.timeout):
            raise ContextTimeoutError(f"Context '{self.name}' initialization timeout after {self.timeout}s")

    async def async_get_instance(self) -> T:
        """异步获取上下文实例

        Returns:
            T: 初始化后的上下文实例

        Raises:
            ContextStateError: 上下文处于错误状态或已关闭
            ContextTimeoutError: 初始化超时
            ContextInitializationError: 初始化失败
        """
        # 快速路径：实例已就绪
        if self.state == ContextState.READY and self._instance is not None:
            return self._instance

        self._validate_state_for_access()

        async with self._async_lock:
            # 双检锁模式
            if self.state == ContextState.READY and self._instance is not None:
                return self._instance

            # 如果正在初始化，等待完成
            if self.state == ContextState.INITIALIZING:
                await self._wait_for_initialization_async()
                self._validate_state_for_access()
                if self.state == ContextState.READY and self._instance is not None:
                    return self._instance

            # 开始初始化
            return await self._perform_initialization_async()

    async def _perform_initialization_async(self) -> T:
        """执行异步初始化逻辑"""
        self.state = ContextState.INITIALIZING
        self._async_ready_event.clear()

        last_error = None
        for attempt in range(self.retry_count):
            try:
                logger.debug(f"Initializing context '{self.name}' (attempt {attempt + 1}/{self.retry_count})")
                self._instance = await self._async_initialize()
                self.state = ContextState.READY
                self._async_ready_event.set()
                self._sync_ready_event.set()
                logger.debug(f"Context '{self.name}' initialized successfully")
                return self._instance
            except Exception as e:
                last_error = e
                if attempt < self.retry_count - 1:
                    wait_time = 2 ** attempt  # 指数退避
                    logger.warning(f"Context '{self.name}' init attempt {attempt + 1} failed: {e}, retrying in {wait_time}s")
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"Context '{self.name}' initialization failed after {self.retry_count} attempts: {e}")

        # 所有重试都失败
        self.state = ContextState.ERROR
        self._error = last_error
        self._async_ready_event.set()  # 通知等待者失败
        self._sync_ready_event.set()
        raise ContextInitializationError(f"Failed to initialize context '{self.name}': {last_error}") from last_error

    def sync_get_instance(self) -> T:
        """同步获取上下文实例

        Returns:
            T: 初始化后的上下文实例

        Raises:
            ContextStateError: 上下文处于错误状态、已关闭或初始化超时
            ContextInitializationError: 初始化失败
        """
        # 快速路径：实例已就绪
        if self.state == ContextState.READY and self._instance is not None:
            return self._instance

        self._validate_state_for_access()

        with self._sync_lock:
            # 双检锁模式
            if self.state == ContextState.READY and self._instance is not None:
                return self._instance

            # 如果正在初始化，等待完成
            if self.state == ContextState.INITIALIZING:
                self._wait_for_initialization_sync()
                self._validate_state_for_access()
                if self.state == ContextState.READY and self._instance is not None:
                    return self._instance

            # 开始初始化
            return self._perform_initialization_sync()

    def _perform_initialization_sync(self) -> T:
        """执行同步初始化逻辑"""
        self.state = ContextState.INITIALIZING
        self._sync_ready_event.clear()
        self._async_ready_event.clear()

        last_error = None
        for attempt in range(self.retry_count):
            try:
                logger.debug(f"Initializing context '{self.name}' (attempt {attempt + 1}/{self.retry_count})")
                self._instance = self._sync_initialize()
                self.state = ContextState.READY
                self._sync_ready_event.set()
                self._async_ready_event.set()
                logger.debug(f"Context '{self.name}' initialized successfully")
                return self._instance
            except Exception as e:
                last_error = e
                if attempt < self.retry_count - 1:
                    wait_time = 2 ** attempt  # 指数退避
                    logger.warning(f"Context '{self.name}' init attempt {attempt + 1} failed: {e}, retrying in {wait_time}s")
                    time.sleep(wait_time)
                else:
                    logger.error(f"Context '{self.name}' initialization failed after {self.retry_count} attempts: {e}")

        # 所有重试都失败
        self.state = ContextState.ERROR
        self._error = last_error
        self._sync_ready_event.set()  # 通知等待者失败
        self._async_ready_event.set()
        raise ContextInitializationError(f"Failed to initialize context '{self.name}': {last_error}") from last_error

    async def async_close(self) -> None:
        """异步关闭上下文管理器

        安全地释放资源并将状态设置为已关闭
        """
        if self.state in [ContextState.CLOSING, ContextState.CLOSED]:
            return

        async with self._async_lock:
            if self.state in [ContextState.CLOSING, ContextState.CLOSED]:
                return

            self.state = ContextState.CLOSING

            try:
                if self._instance is not None:
                    logger.debug(f"Closing context '{self.name}'")
                    await self._async_cleanup()
                    self._instance = None
                    logger.debug(f"Context '{self.name}' closed successfully")
            except Exception as e:
                logger.error(f"Error closing context '{self.name}': {e}")
                # 即使清理失败，也要标记为已关闭以避免资源泄漏
            finally:
                self.state = ContextState.CLOSED
                self._error = None
                # 确保事件被设置，防止等待者无限等待
                self._async_ready_event.set()
                self._sync_ready_event.set()

    def sync_close(self) -> None:
        """同步关闭上下文管理器

        安全地释放资源并将状态设置为已关闭
        """
        if self.state in [ContextState.CLOSING, ContextState.CLOSED]:
            return

        with self._sync_lock:
            if self.state in [ContextState.CLOSING, ContextState.CLOSED]:
                return

            self.state = ContextState.CLOSING

            try:
                if self._instance is not None:
                    logger.debug(f"Closing context '{self.name}'")
                    self._sync_cleanup()
                    self._instance = None
                    logger.debug(f"Context '{self.name}' closed successfully")
            except Exception as e:
                logger.error(f"Error closing context '{self.name}': {e}")
                # 即使清理失败，也要标记为已关闭以避免资源泄漏
            finally:
                self.state = ContextState.CLOSED
                self._error = None
                # 确保事件被设置，防止等待者无限等待
                self._async_ready_event.set()
                self._sync_ready_event.set()

    async def async_reset(self) -> None:
        """重置上下文管理器

        关闭当前实例并重置为未初始化状态，下次访问时会重新初始化
        """
        await self.async_close()
        async with self._async_lock:
            self.state = ContextState.UNINITIALIZED
            self._error = None
            self._async_ready_event.clear()
            self._sync_ready_event.clear()

    def sync_reset(self) -> None:
        """重置上下文管理器

        关闭当前实例并重置为未初始化状态，下次访问时会重新初始化
        """
        self.sync_close()
        with self._sync_lock:
            self.state = ContextState.UNINITIALIZED
            self._error = None
            self._async_ready_event.clear()
            self._sync_ready_event.clear()

    def is_ready(self) -> bool:
        """检查是否已就绪

        Returns:
            bool: True 如果上下文已初始化且可用，False 否则
        """
        return self.state == ContextState.READY and self._instance is not None

    def get_state(self) -> ContextState:
        """获取当前状态

        Returns:
            ContextState: 当前上下文状态
        """
        return self.state

    def get_error(self) -> Optional[Exception]:
        """获取最后的错误信息

        Returns:
            Optional[Exception]: 如果处于错误状态，返回错误信息，否则返回 None
        """
        return self._error

    def get_info(self) -> Dict[str, Any]:
        """获取上下文信息

        Returns:
            Dict[str, Any]: 包含上下文详细信息的字典
        """
        return {
            'name': self.name,
            'state': self.state.value,
            'is_ready': self.is_ready(),
            'timeout': self.timeout,
            'retry_count': self.retry_count,
            'error': str(self._error) if self._error else None,
            'has_instance': self._instance is not None
        }

    @contextmanager
    def sync_context(self):
        """同步上下文管理器

        使用 with 语句自动获取和释放资源

        Example:
            with my_context.sync_context() as instance:
                # 使用 instance
                pass
        """
        instance = self.sync_get_instance()
        try:
            yield instance
        finally:
            # 注意：这里不自动关闭，因为可能被其他地方使用
            pass

    @asynccontextmanager
    async def async_context(self):
        """异步上下文管理器

        使用 async with 语句自动获取和释放资源

        Example:
            async with my_context.async_context() as instance:
                # 使用 instance
                pass
        """
        instance = await self.async_get_instance()
        try:
            yield instance
        finally:
            # 注意：这里不自动关闭，因为可能被其他地方使用
            pass

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(name='{self.name}', state='{self.state.value}')>"


class FunctionContextManager(BaseContextManager[T]):
    """基于函数的上下文管理器

    允许通过函数来定义初始化和清理逻辑
    """

    def __init__(
            self,
            name: str,
            init_func: Union[Callable[[], Awaitable[T]], Callable[[], T]],
            cleanup_func: Optional[Union[Callable[[T], Awaitable[None]], Callable[[T], None]]] = None,
            **kwargs
    ):
        super().__init__(name, **kwargs)
        self.init_func = init_func
        self.cleanup_func = cleanup_func
        self._is_async = asyncio.iscoroutinefunction(init_func)

    async def _async_initialize(self) -> T:
        """使用初始化函数初始化实例"""
        if not self._is_async:
            # 如果初始化函数不是异步的，在线程池中执行
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self.init_func)
        return await self.init_func()

    def _sync_initialize(self) -> T:
        """同步初始化"""
        if self._is_async:
            raise TypeError(f"Cannot call async init_func '{self.init_func.__name__}' in sync context")
        return self.init_func()

    async def _async_cleanup(self) -> None:
        """使用清理函数清理实例"""
        if self.cleanup_func and self._instance:
            if asyncio.iscoroutinefunction(self.cleanup_func):
                await self.cleanup_func(self._instance)
            else:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self.cleanup_func, self._instance)

    def _sync_cleanup(self) -> None:
        """同步清理"""
        if self.cleanup_func and self._instance:
            if asyncio.iscoroutinefunction(self.cleanup_func):
                raise TypeError(f"Cannot call async cleanup_func '{self.cleanup_func.__name__}' in sync context")
            self.cleanup_func(self._instance)


class ContextRegistry:
    """上下文注册表

    管理多个上下文管理器的注册和生命周期
    """

    def __init__(self):
        self._contexts: Dict[str, BaseContextManager] = {}
        self._lock = Lock()

    def register(self, context_manager: BaseContextManager) -> None:
        """注册上下文管理器

        Args:
            context_manager: 要注册的上下文管理器

        Raises:
            ValueError: 如果同名上下文已存在
        """
        with self._lock:
            if context_manager.name in self._contexts:
                raise ValueError(f"Context '{context_manager.name}' already registered")
            self._contexts[context_manager.name] = context_manager
            logger.debug(f"Registered context: '{context_manager.name}'")

    def unregister(self, name: str) -> None:
        """注销上下文管理器

        Args:
            name: 要注销的上下文名称
        """
        with self._lock:
            if name in self._contexts:
                context = self._contexts[name]
                # 先关闭上下文再删除
                try:
                    context.sync_close()
                except Exception as e:
                    logger.warning(f"Error closing context '{name}' during unregister: {e}")
                del self._contexts[name]
                logger.debug(f"Unregistered context: '{name}'")

    def get_context(self, name: str) -> BaseContextManager:
        """获取上下文管理器

        Args:
            name: 上下文名称

        Returns:
            BaseContextManager: 对应的上下文管理器

        Raises:
            KeyError: 如果上下文不存在
        """
        if name not in self._contexts:
            raise KeyError(f"Context '{name}' not found. Available contexts: {list(self._contexts.keys())}")
        return self._contexts[name]

    def has_context(self, name: str) -> bool:
        """检查是否存在指定名称的上下文

        Args:
            name: 上下文名称

        Returns:
            bool: 如果存在则返回 True，否则返回 False
        """
        return name in self._contexts

    async def async_get_instance(self, name: str) -> Any:
        """异步获取上下文实例"""
        context = self.get_context(name)
        return await context.async_get_instance()

    def sync_get_instance(self, name: str) -> Any:
        """同步获取上下文实例"""
        context = self.get_context(name)
        return context.sync_get_instance()

    async def async_close_all(self) -> None:
        """异步关闭所有上下文管理器"""
        contexts = list(self._contexts.values())

        # 并行关闭所有上下文以提高性能
        close_tasks = [context.async_close() for context in contexts]
        results = await asyncio.gather(*close_tasks, return_exceptions=True)

        # 记录关闭过程中的错误
        for context, result in zip(contexts, results):
            if isinstance(result, Exception):
                logger.error(f"Error closing context '{context.name}': {result}")

    def sync_close_all(self) -> None:
        """同步关闭所有上下文管理器"""
        for context in self._contexts.values():
            try:
                context.sync_close()
            except Exception as e:
                logger.error(f"Error closing context '{context.name}': {e}")

    def get_all_contexts(self) -> Dict[str, BaseContextManager]:
        """获取所有上下文管理器的副本

        Returns:
            Dict[str, BaseContextManager]: 包含所有上下文管理器的字典副本
        """
        return self._contexts.copy()

    def get_ready_contexts(self) -> Dict[str, BaseContextManager]:
        """获取所有已就绪的上下文管理器

        Returns:
            Dict[str, BaseContextManager]: 包含所有已就绪上下文管理器的字典
        """
        return {
            name: context
            for name, context in self._contexts.items()
            if context.is_ready()
        }

    def get_context_states(self) -> Dict[str, ContextState]:
        """获取所有上下文的状态

        Returns:
            Dict[str, ContextState]: 上下文名称到状态的映射
        """
        return {
            name: context.get_state()
            for name, context in self._contexts.items()
        }

    async def health_check(self) -> Dict[str, bool]:
        """执行所有上下文的健康检查

        Returns:
            Dict[str, bool]: 上下文名称到健康状态的映射
        """
        results = {}
        for name, context in self._contexts.items():
            try:
                # 如果上下文有自定义的健康检查方法，优先使用
                if hasattr(context, 'health_check') and callable(getattr(context, 'health_check')):
                    health_check_func = getattr(context, 'health_check')
                    if asyncio.iscoroutinefunction(health_check_func):
                        results[name] = await health_check_func()
                    else:
                        results[name] = health_check_func()
                else:
                    # 否则使用基本的就绪状态检查
                    results[name] = context.is_ready()
            except Exception as e:
                logger.error(f"Health check failed for context '{name}': {e}")
                results[name] = False
        return results

    def clear(self) -> None:
        """清空所有上下文（先关闭再删除）"""
        with self._lock:
            # 先关闭所有上下文
            self.sync_close_all()
            # 清空注册表
            self._contexts.clear()
            logger.debug("All contexts cleared from registry")

    def __len__(self) -> int:
        """返回已注册的上下文数量"""
        return len(self._contexts)

    def __contains__(self, name: str) -> bool:
        """支持 'name' in registry 语法"""
        return name in self._contexts

    def __iter__(self):
        """支持迭代上下文名称"""
        return iter(self._contexts.keys())

    def __repr__(self) -> str:
        return f"<ContextRegistry(contexts={list(self._contexts.keys())})>"