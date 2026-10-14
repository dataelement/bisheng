"""Entry-neutral execution context for assistant conversations."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

AssistantMessageContent = str | list[dict[str, Any]]
CancellationCheck = Callable[[], bool | Awaitable[bool]]


class AssistantEntryPoint(StrEnum):
    INTERNAL = "internal"
    EPLUS = "eplus"


@dataclass(frozen=True, slots=True)
class AssistantRobotScope:
    bot_config_id: int
    space_ids: tuple[int, ...]
    scope_version: int


@dataclass(frozen=True, slots=True)
class AssistantExecutionContext:
    entry_point: AssistantEntryPoint
    user_id: int
    external_user_id: str | None
    content: AssistantMessageContent
    robot_scope: AssistantRobotScope | None = None
    cancellation_check: CancellationCheck | None = None

    async def raise_if_cancelled(self) -> None:
        if self.cancellation_check is None:
            return
        result = self.cancellation_check()
        cancelled = await result if inspect.isawaitable(result) else result
        if cancelled:
            raise asyncio.CancelledError("assistant execution cancelled")
