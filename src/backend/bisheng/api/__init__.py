"""Lazy exports for API routers.

Avoid importing the entire API tree on package import. This keeps lightweight
domain/service scripts from triggering router initialization and circular
imports when they only need nested schema modules under ``bisheng.api``.
"""

from __future__ import annotations

from typing import Any

__all__ = ['router', 'router_rpc']


def __getattr__(name: str) -> Any:
    if name in __all__:
        from bisheng.api.router import router, router_rpc

        exports = {
            'router': router,
            'router_rpc': router_rpc,
        }
        return exports[name]
    raise AttributeError(name)
