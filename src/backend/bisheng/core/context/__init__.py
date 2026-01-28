
"""Application Context Management Module

Provide a common context management framework, including:
- Thread-safe lazy loading mechanism
- Automatic Caching and Instance Lifecycle Management
- Dependency injection and initialization sequence control
- Retry mechanism and timeout handling
- Health check and monitoring functions
- Convenient context manager support

Usage examples:
    # basic use
    from bisheng.core.context import initialize_app_context, get_context

    await initialize_app_context()
    db = await get_context('database').async_get_instance()

    # Using the Context Manager
    async with get_context('database').async_context() as db:
        # Use db
        pass
"""

from .base import (
    # Core classes and statuses
    BaseContextManager,
    FunctionContextManager,
    ContextRegistry,
    ContextState,

    # Exception Class
    ContextError,
    ContextInitializationError,
    ContextTimeoutError,
    ContextStateError,
)
from .manager import (
    # APP MANAGER
    ApplicationContextManager,
    app_context,

    # Initialization and Lifecycle Management
    initialize_app_context,
    close_app_context,

    # Context Access and Management
    get_context,
    async_get_instance,
    sync_get_instance,
    register_context,

    # Monitoring and Diagnostics
    health_check,
)

__all__ = [
    # Core Base Classes and States
    'BaseContextManager',
    'FunctionContextManager',
    'ContextRegistry',
    'ContextState',

    # Exception Class
    'ContextError',
    'ContextInitializationError',
    'ContextTimeoutError',
    'ContextStateError',

    # APP MANAGER
    'ApplicationContextManager',
    'app_context',

    # PRODUCT LIFECYCLE MANAGEMENT
    'initialize_app_context',
    'close_app_context',

    # Context Access and Management
    'get_context',
    'async_get_instance',
    'sync_get_instance',
    'register_context',

    # Monitoring and Diagnostics
    'health_check',
]