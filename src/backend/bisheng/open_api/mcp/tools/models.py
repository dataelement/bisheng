"""Category ③ — the callable model list (`model:invoke`).

The *names* come from F051's resolver and from nowhere else. A second naming
rule here would be a second answer to "what do I pass as ``model``", and the one
thing this tool exists for is that the name it prints is the name the model
protocol face will accept (AC-13's "three sources, one rule": this tool, F051's
resolution, F055's pre-check).

So the resolver is imported lazily and the registry gates the tool on it: on a
tree where F051 has not landed, the tool is absent from ``tools/list`` rather
than present and answering with names nobody can call.
"""

from __future__ import annotations

import importlib
import importlib.util
from typing import Any

from pydantic import BaseModel, Field

from bisheng.common.errcode.mcp_face import McpUnknownToolError

#: F051 owns the resolver. ``design.md`` D10 named the module
#: ``model_name_resolver``; the implementation landed it as ``model_catalog``.
#: Both spellings are probed rather than one guessed, so this tool lights up
#: whichever way that feature merged — and stays dark if neither is there.
RESOLVER_MODULES = (
    "bisheng.llm.domain.services.model_catalog",
    "bisheng.llm.domain.services.model_name_resolver",
)
RESOLVER_FUNCTION = "resolve_callable_names"


def _resolver():
    for name in RESOLVER_MODULES:
        try:
            if importlib.util.find_spec(name) is None:
                continue
            module = importlib.import_module(name)
        except (ImportError, ValueError):
            continue
        resolve = getattr(module, RESOLVER_FUNCTION, None)
        if callable(resolve):
            return resolve
    return None


def resolver_available() -> bool:
    """Whether F051's name resolver has landed on this tree."""

    return _resolver() is not None


class CallableModel(BaseModel):
    name: str
    qualified_name: str | None = None
    #: What to pass as ``model`` on the protocol face: the bare name when it is
    #: unambiguous, the provider-qualified one when it is not.
    callable_name: str
    model_type: str | None = None
    is_chat: bool = False
    server_name: str | None = None


class ModelListResult(BaseModel):
    models: list[CallableModel] = Field(default_factory=list)


async def bisheng_model_list() -> ModelListResult:
    """List this tenant's enabled models and the exact name to call each one by."""

    from bisheng.open_api.domain.context import get_current_open_api_principal

    resolve = _resolver()
    if resolve is None:  # pragma: no cover — the registry keeps the tool hidden
        raise McpUnknownToolError()
    principal = get_current_open_api_principal()
    rows = await resolve(principal.tenant_id)
    return ModelListResult(models=[CallableModel(**_row_payload(row)) for row in rows or []])


def _row_payload(row: Any) -> dict[str, Any]:
    if isinstance(row, dict):
        get = row.get
    else:

        def get(key, default=None):
            return getattr(row, key, default)

    name = get("name", "") or ""
    qualified_name = get("qualified_name", None)
    callable_name = get("callable_name", None)
    if not callable_name:
        # AC-13: ambiguous names must be published in their qualified form, or
        # the list hands out a name the protocol face will refuse.
        callable_name = qualified_name if get("is_ambiguous", False) else name
    return {
        "name": name,
        "qualified_name": qualified_name,
        "callable_name": callable_name or name,
        "model_type": get("model_type", None),
        "is_chat": bool(get("is_chat", False)),
        "server_name": get("server_name", None),
    }


__all__ = ["RESOLVER_FUNCTION", "RESOLVER_MODULES", "bisheng_model_list", "resolver_available"]
