"""Export baking for Linsight task-mode reports (F069 P2).

A stored report keeps its hidden citation markers so the in-app preview can
render badges. When the report leaves the platform — docx / pdf export tools
run by the agent, the workbench convert endpoint, the batch zip download — the
markers are baked into visible ``[n]`` numbers with a references section.

The sources listed are the ones the EXPORTER may see: the persisted
``message_citation`` rows are run through ``CitationResolveService`` with the
exporter's identity (the same INV-7 ``view_file`` filter the badge tooltips
use), and anything the service withholds or cannot find is stripped instead of
numbered (spec AC-21 / AC-22). Nothing here ever raises into an export: on any
failure the text falls back to the plain strip behaviour and a warning is
logged with ``citations_baked=false``.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from bisheng.citation.domain.services.citation_handle_service import (
    render_citations_for_export,
    strip_citation_handles,
)
from bisheng.citation.domain.services.citation_prompt_helper import (
    extract_citation_ids_from_text,
    strip_citation_markers,
)


async def resolve_items_for_export(citation_ids: list[str], login_user: Any) -> list[Any]:
    """Resolve the ids the exporter may see (permission-filtered).

    Uses the DB-backed repository so an old report still resolves after the
    30-day Redis cache is gone. ``login_user`` may be None (anonymous): the
    resolve service then keeps public web sources only.
    """
    if not citation_ids:
        return []
    from bisheng.citation.domain.repositories.implementations.message_citation_repository_impl import (
        MessageCitationRepositoryImpl,
    )
    from bisheng.citation.domain.services.citation_resolve_service import CitationResolveService
    from bisheng.core.database import get_async_db_session

    from bisheng.core.context.tenant import current_tenant_id, get_current_tenant_id

    # The tenant-aware repository needs the ContextVar; requests and the
    # worker set it, but a caller outside both (scripts, future jobs) does not.
    # Borrow the exporter's tenant for the duration of the lookup.
    token = None
    exporter_tenant = getattr(login_user, "tenant_id", None)
    if get_current_tenant_id() is None and exporter_tenant is not None:
        token = current_tenant_id.set(int(exporter_tenant))
    try:
        async with get_async_db_session() as session:
            service = CitationResolveService(MessageCitationRepositoryImpl(session))
            response = await service.resolve_citations_with_reasons(list(citation_ids), login_user)
    finally:
        if token is not None:
            current_tenant_id.reset(token)
    return list(getattr(response, "items", None) or [])


def strip_all_citations(text: str) -> str:
    """The pre-P2 export behaviour: no marker, no id, no short handle survives."""
    return strip_citation_handles(strip_citation_markers(text or ""))


async def bake_citations_for_export(text: str, login_user: Any) -> str:
    """Hidden markers -> visible ``[n]`` + references, or plain strip on failure."""
    if not text:
        return text or ""
    try:
        citation_ids = sorted(cid for cid in extract_citation_ids_from_text(text) if cid)
        if not citation_ids:
            return strip_all_citations(text)
        items = await resolve_items_for_export(citation_ids, login_user)
        result = render_citations_for_export(text, items)
        logger.info(
            f"citations_baked=true numbered={result.numbered} unresolved={len(result.unresolved)} "
            f"user={getattr(login_user, 'user_id', None)}"
        )
        return result.text
    except Exception:
        logger.opt(exception=True).warning("citations_baked=false; falling back to stripping citation markers")
        return strip_all_citations(text)


async def build_export_user(user_id: Any, tenant_id: Any) -> Any:
    """UserPayload for a worker-side export (the task owner); None when unknown."""
    if user_id is None:
        return None
    try:
        from bisheng.common.dependencies.user_deps import UserPayload
        from bisheng.utils.http_middleware import _check_is_global_super

        return UserPayload(
            user_id=int(user_id),
            user_name="",
            user_role=[],
            tenant_id=int(tenant_id) if tenant_id is not None else None,
            is_global_super=await _check_is_global_super(int(user_id)),
        )
    except Exception:
        logger.opt(exception=True).warning(f"export user build failed user_id={user_id}; exporting as anonymous")
        return None
