"""Deletion-event fan-out — the seam that keeps F055 out of F054's imports.

Dependency direction is F055 → F054, never back (RULE-5 and plain sense: the
domain must not know about the publishing pipeline). But AC-43 requires that
deleting an application cancels its in-flight approval, which only F055 knows
how to do. So F054 publishes an event and F055 subscribes to it from its own
composition root.

Two properties are load bearing:

* **A failing hook never rolls the deletion back.** By the time hooks run the
  execution body and the volume are already gone; undoing the state change
  would leave "the app exists but its data does not" — a zombie that is worse
  than a stale approval row. Failures are recorded as ``app.delete_hook_failed``
  and the deletion stands.
* **Registration is idempotent by function identity.** Both composition roots
  (API process and workers) install the same subscribers, and a worker that
  re-initialises would otherwise cancel the same approval twice.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from loguru import logger

#: ``(app_id, actor_user_id, tenant_id) -> Awaitable[None]``
AppDeletedHook = Callable[..., Awaitable[None]]

_hooks: list[AppDeletedHook] = []


def register_app_deleted_hook(hook: AppDeletedHook) -> None:
    """Subscribe to "an application was deleted". Re-registering the same callable is a no-op."""
    if hook not in _hooks:
        _hooks.append(hook)


def clear_app_deleted_hooks() -> None:
    """Drop every subscriber — composition-root reset and test isolation only."""
    _hooks.clear()


async def on_app_deleted(*, app_id: str, actor_user_id: int, tenant_id: int) -> list[Exception]:
    """Run every subscriber; return the failures instead of raising them.

    Returning rather than raising is what lets the caller audit each failure
    against the deletion that already happened — see the module docstring.
    """
    failures: list[Exception] = []
    for hook in list(_hooks):
        try:
            await hook(app_id=app_id, actor_user_id=actor_user_id, tenant_id=tenant_id)
        except Exception as exc:
            logger.exception("app_runtime.on_app_deleted hook failed app_id={} hook={}", app_id, hook)
            failures.append(exc)
    return failures
