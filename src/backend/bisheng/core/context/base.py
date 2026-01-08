import asyncio
import time
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager, contextmanager
from enum import Enum
from threading import Lock, Event
from typing import Any, Dict, Optional, TypeVar, Generic, Callable, Awaitable, Union

from loguru import logger

T = TypeVar('T')


class ContextState(Enum):
    """Context State Enumeration"""
    UNINITIALIZED = "uninitialized"  # Not Initialized
    INITIALIZING = "initializing"  # Initializing
    READY = "ready"  # Working on it...
    ERROR = "error"  # Error State
    CLOSING = "closing"  # closing
    CLOSED = "closed"  # Closed


class ContextError(Exception):
    """Context-dependent exception base class"""
    pass


class ContextInitializationError(ContextError):
    """Context initialization exception"""
    pass


class ContextTimeoutError(ContextError):
    """Context operation timeout exception"""
    pass


class ContextStateError(ContextError):
    """Context status exception"""
    pass


class BaseContextManager(ABC, Generic[T]):
    """Underlying Manager Abstract Class

    Defines the interfaces that all context managers must implement
    Provides thread-safe lazy loading, caching, and lifecycle management
    """

    name: str
    _default_timeout: float = 30.0  # Timeout default
    _default_retry_count: int = 3  # Default number of retries

    def __init__(self, name: str = None, timeout: float = None, retry_count: int = None, **kwargs):
        self.name = name or getattr(self.__class__, 'name', self.__class__.__name__.lower())
        self.timeout = timeout or self._default_timeout
        self.retry_count = retry_count or self._default_retry_count

        self.state = ContextState.UNINITIALIZED
        self._instance: Optional[T] = None
        self._error: Optional[Exception] = None

        # Synchronous and asynchronous locks
        self._sync_lock = Lock()
        self._async_lock = asyncio.Lock()

        # Synchronization Waiting Event
        self._sync_ready_event = Event()
        self._async_ready_event = asyncio.Event()

    @abstractmethod
    async def _async_initialize(self) -> T:
        """Asynchronous initialization resources (abstract methods)"""
        pass

    @abstractmethod
    def _sync_initialize(self) -> T:
        """Synchronous initialization resources (abstract methods)"""
        pass

    @abstractmethod
    async def _async_cleanup(self) -> None:
        """Asynchronous Cleanup Resource (Abstract Method)"""
        pass

    @abstractmethod
    def _sync_cleanup(self) -> None:
        """Synchronous Cleanup Resource (Abstract Method)"""
        pass

    def _validate_state_for_access(self) -> None:
        """Verify that the status allows access to the instance"""
        if self.state == ContextState.ERROR:
            error_msg = f"Context '{self.name}' is in error state"
            if self._error:
                error_msg += f": {self._error}"
            raise ContextStateError(error_msg)

        if self.state == ContextState.CLOSED:
            raise ContextStateError(f"Context '{self.name}' is closed and cannot be accessed")

    async def _wait_for_initialization_async(self) -> None:
        """Asynchronous waiting for initialization to complete"""
        try:
            await asyncio.wait_for(self._async_ready_event.wait(), timeout=self.timeout)
        except asyncio.TimeoutError:
            raise ContextTimeoutError(f"Context '{self.name}' initialization timeout after {self.timeout}s")

    def _wait_for_initialization_sync(self) -> None:
        """Sync waiting for initialization to complete"""
        if not self._sync_ready_event.wait(timeout=self.timeout):
            raise ContextTimeoutError(f"Context '{self.name}' initialization timeout after {self.timeout}s")

    async def async_get_instance(self) -> T:
        """Asynchronous Get Context Instance

        Returns:
            T: Contextual instance after initialization

        Raises:
            ContextStateError: Context is in error state or closed
            ContextTimeoutError: Initialization timeout
            ContextInitializationError: Initialization failed
        """
        # Quick Path: Instance Ready
        if self.state == ContextState.READY and self._instance is not None:
            return self._instance

        self._validate_state_for_access()

        async with self._async_lock:
            # Dual Lock Check Mode
            if self.state == ContextState.READY and self._instance is not None:
                return self._instance

            # If initializing, wait for completion
            if self.state == ContextState.INITIALIZING:
                await self._wait_for_initialization_async()
                self._validate_state_for_access()
                if self.state == ContextState.READY and self._instance is not None:
                    return self._instance

            # Start Initialization
            return await self._perform_initialization_async()

    async def _perform_initialization_async(self) -> T:
        """Execute asynchronous initialization logic"""
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
                    wait_time = 2 ** attempt  # Exponential withdrawal
                    logger.warning(
                        f"Context '{self.name}' init attempt {attempt + 1} failed: {e}, retrying in {wait_time}s")
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"Context '{self.name}' initialization failed after {self.retry_count} attempts: {e}")

        # All retries failed
        self.state = ContextState.ERROR
        self._error = last_error
        self._async_ready_event.set()  # Failed to notify waiter
        self._sync_ready_event.set()
        raise ContextInitializationError(f"Failed to initialize context '{self.name}': {last_error}") from last_error

    def sync_get_instance(self) -> T:
        """Synchronize Get Context Instance

        Returns:
            T: Contextual instance after initialization

        Raises:
            ContextStateError: Context is in error state, closed or initialization timed out
            ContextInitializationError: Initialization failed
        """
        # Quick Path: Instance Ready
        if self.state == ContextState.READY and self._instance is not None:
            return self._instance

        self._validate_state_for_access()

        with self._sync_lock:
            # Dual Lock Check Mode
            if self.state == ContextState.READY and self._instance is not None:
                return self._instance

            # If initializing, wait for completion
            if self.state == ContextState.INITIALIZING:
                self._wait_for_initialization_sync()
                self._validate_state_for_access()
                if self.state == ContextState.READY and self._instance is not None:
                    return self._instance

            # Start Initialization
            return self._perform_initialization_sync()

    def _perform_initialization_sync(self) -> T:
        """Execute Synchronization Initialization Logic"""
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
                    wait_time = 2 ** attempt  # Exponential withdrawal
                    logger.warning(
                        f"Context '{self.name}' init attempt {attempt + 1} failed: {e}, retrying in {wait_time}s")
                    time.sleep(wait_time)
                else:
                    logger.error(f"Context '{self.name}' initialization failed after {self.retry_count} attempts: {e}")

        # All retries failed
        self.state = ContextState.ERROR
        self._error = last_error
        self._sync_ready_event.set()  # Failed to notify waiter
        self._async_ready_event.set()
        raise ContextInitializationError(f"Failed to initialize context '{self.name}': {last_error}") from last_error

    async def async_close(self) -> None:
        """Shutdown context manager asynchronously

        Safely release resources and set status to off
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
                # Mark as closed to avoid resource leakage even if cleanup fails
            finally:
                self.state = ContextState.CLOSED
                self._error = None
                # Ensure events are set to prevent unlimited wait time for waiters
                self._async_ready_event.set()
                self._sync_ready_event.set()

    def sync_close(self) -> None:
        """Sync Close Context Manager

        Safely release resources and set status to off
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
                # Mark as closed to avoid resource leakage even if cleanup fails
            finally:
                self.state = ContextState.CLOSED
                self._error = None
                # Ensure events are set to prevent unlimited wait time for waiters
                self._async_ready_event.set()
                self._sync_ready_event.set()

    async def async_reset(self) -> None:
        """Reset Context Manager

        Close the current instance and reset it to the uninitialized state, it will be reinitialized on the next visit
        """
        await self.async_close()
        async with self._async_lock:
            self.state = ContextState.UNINITIALIZED
            self._error = None
            self._async_ready_event.clear()
            self._sync_ready_event.clear()

    def sync_reset(self) -> None:
        """Reset Context Manager

        Close the current instance and reset it to the uninitialized state, it will be reinitialized on the next visit
        """
        self.sync_close()
        with self._sync_lock:
            self.state = ContextState.UNINITIALIZED
            self._error = None
            self._async_ready_event.clear()
            self._sync_ready_event.clear()

    def is_ready(self) -> bool:
        """Check to see if it's ready

        Returns:
            bool: True If the context is initialized and available,False Otherwise, 
        """
        return self.state == ContextState.READY and self._instance is not None

    def get_state(self) -> ContextState:
        """Fetch the current status

        Returns:
            ContextState: Current Context State
        """
        return self.state

    def get_error(self) -> Optional[Exception]:
        """Get the last error message

        Returns:
            Optional[Exception]: If in error state, return error message, otherwise return None
        """
        return self._error

    def get_info(self) -> Dict[str, Any]:
        """Get Context Information

        Returns:
            Dict[str, Any]: Dictionary with contextual details
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
        """Synchronization Context Manager

        Use with Statements automatically fetch and free resources

        Example:
            with my_context.sync_context() as instance:
                # Use instance
                pass
        """
        instance = self.sync_get_instance()
        try:
            yield instance
        finally:
            # Note: This does not close automatically as it may be used elsewhere
            pass

    @asynccontextmanager
    async def async_context(self):
        """Asynchronous Context Manager

        Use async with Statements automatically fetch and free resources

        Example:
            async with my_context.async_context() as instance:
                # Use instance
                pass
        """
        instance = await self.async_get_instance()
        try:
            yield instance
        finally:
            # Note: This does not close automatically as it may be used elsewhere
            pass

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(name='{self.name}', state='{self.state.value}')>"


class FunctionContextManager(BaseContextManager[T]):
    """Function-based context manager

    Allows initialization and cleanup logic to be defined via functions
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
        """Initialize the instance using the initialization function"""
        if not self._is_async:
            # Execute in thread pool if initialization function is not asynchronous
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self.init_func)
        return await self.init_func()

    def _sync_initialize(self) -> T:
        """Synchronization Initialization"""
        if self._is_async:
            raise TypeError(f"Cannot call async init_func '{self.init_func.__name__}' in sync context")
        return self.init_func()

    async def _async_cleanup(self) -> None:
        """Clean up instances using the cleanup function"""
        if self.cleanup_func and self._instance:
            if asyncio.iscoroutinefunction(self.cleanup_func):
                await self.cleanup_func(self._instance)
            else:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self.cleanup_func, self._instance)

    def _sync_cleanup(self) -> None:
        """Synchronous Cleanup"""
        if self.cleanup_func and self._instance:
            if asyncio.iscoroutinefunction(self.cleanup_func):
                raise TypeError(f"Cannot call async cleanup_func '{self.cleanup_func.__name__}' in sync context")
            self.cleanup_func(self._instance)


class ContextRegistry:
    """Context Registry

    Manage Enrollment and Lifecycle for Multiple Context Managers
    """

    def __init__(self):
        self._contexts: Dict[str, BaseContextManager] = {}
        self._lock = Lock()

    def register(self, context_manager: BaseContextManager) -> None:
        """Register Context Manager

        Args:
            context_manager: Context manager to register

        Raises:
            ValueError: If a context with the same name already exists
        """
        with self._lock:
            if context_manager.name in self._contexts:
                logger.warning(f"Context '{context_manager.name}' is already registered")
                return
            self._contexts[context_manager.name] = context_manager
            logger.debug(f"Registered context: '{context_manager.name}'")

    def unregister(self, name: str) -> None:
        """Log out of the context manager

        Args:
            name: Context name to be logged out
        """
        with self._lock:
            if name in self._contexts:
                context = self._contexts[name]
                # Close context before deleting
                try:
                    context.sync_close()
                except Exception as e:
                    logger.warning(f"Error closing context '{name}' during unregister: {e}")
                del self._contexts[name]
                logger.debug(f"Unregistered context: '{name}'")

    def get_context(self, name: str) -> BaseContextManager:
        """Get Context Manager

        Args:
            name: Context Name

        Returns:
            BaseContextManager: Corresponding context manager

        Raises:
            KeyError: If the context does not exist
        """
        if name not in self._contexts:
            raise KeyError(f"Context '{name}' not found. Available contexts: {list(self._contexts.keys())}")
        return self._contexts[name]

    def has_context(self, name: str) -> bool:
        """Check if there is a context with the specified name

        Args:
            name: Context Name

        Returns:
            bool: Return if present True, otherwise go back to False
        """
        return name in self._contexts

    async def async_get_instance(self, name: str) -> Any:
        """Asynchronous Get Context Instance"""
        context = self.get_context(name)
        return await context.async_get_instance()

    def sync_get_instance(self, name: str) -> Any:
        """Synchronize Get Context Instance"""
        context = self.get_context(name)
        return context.sync_get_instance()

    async def async_close_all(self) -> None:
        """Shut down all context managers asynchronously"""
        contexts = list(self._contexts.values())

        # Shut down all contexts in parallel to improve performance
        close_tasks = [context.async_close() for context in contexts]
        results = await asyncio.gather(*close_tasks, return_exceptions=True)

        # Log errors during shutdown
        for context, result in zip(contexts, results):
            if isinstance(result, Exception):
                logger.error(f"Error closing context '{context.name}': {result}")

    def sync_close_all(self) -> None:
        """Synchronously close all context managers"""
        for context in self._contexts.values():
            try:
                context.sync_close()
            except Exception as e:
                logger.error(f"Error closing context '{context.name}': {e}")

    def get_all_contexts(self) -> Dict[str, BaseContextManager]:
        """Get a copy of all context managers

        Returns:
            Dict[str, BaseContextManager]: Contains a dictionary copy of all context managers
        """
        return self._contexts.copy()

    def get_ready_contexts(self) -> Dict[str, BaseContextManager]:
        """Get all ready context managers

        Returns:
            Dict[str, BaseContextManager]: Dictionary with all ready context managers
        """
        return {
            name: context
            for name, context in self._contexts.items()
            if context.is_ready()
        }

    def get_context_states(self) -> Dict[str, ContextState]:
        """Get the status of all contexts

        Returns:
            Dict[str, ContextState]: Context name to state mapping
        """
        return {
            name: context.get_state()
            for name, context in self._contexts.items()
        }

    async def health_check(self) -> Dict[str, bool]:
        """Perform health checks for all contexts

        Returns:
            Dict[str, bool]: Context name to health state mapping
        """
        results = {}
        for name, context in self._contexts.items():
            try:
                # Prefer to use if there is a custom health check method in context
                if hasattr(context, 'health_check') and callable(getattr(context, 'health_check')):
                    health_check_func = getattr(context, 'health_check')
                    if asyncio.iscoroutinefunction(health_check_func):
                        results[name] = await health_check_func()
                    else:
                        results[name] = health_check_func()
                else:
                    # Otherwise use basic readiness checks
                    results[name] = context.is_ready()
            except Exception as e:
                logger.error(f"Health check failed for context '{name}': {e}")
                results[name] = False
        return results

    def clear(self) -> None:
        """Clear all contexts (close before deleting)"""
        with self._lock:
            # Close all contexts first
            self.sync_close_all()
            # Empty registry
            self._contexts.clear()
            logger.debug("All contexts cleared from registry")

    def __len__(self) -> int:
        """Returns the number of registered contexts"""
        return len(self._contexts)

    def __contains__(self, name: str) -> bool:
        """Support 'name' in registry Grammar"""
        return name in self._contexts

    def __iter__(self):
        """Support for iterative context names"""
        return iter(self._contexts.keys())

    def __repr__(self) -> str:
        return f"<ContextRegistry(contexts={list(self._contexts.keys())})>"
