"""Owner image capability and tenant restrictions, shared by both chat modes."""

import json
from typing import TYPE_CHECKING, Annotated

from pydantic import Field

from bisheng.common.errcode.dsh import (
    DshAuthorizationUnavailableError,
    DshInvalidRequestError,
    DshModelNotAllowedError,
)
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.dsh.domain.repositories.settings import DshSettingsRepository
from bisheng.dsh.domain.schemas.contracts import DshContract

if TYPE_CHECKING:
    from bisheng.llm.domain.models import LLMModel


class VisionSetting(DshContract):
    vision: bool = Field(default=False, strict=True)


class VisionBatchRequest(DshContract):
    model_ids: list[Annotated[int, Field(strict=True, gt=0, le=9223372036854775807)]] = Field(max_length=200)


def _vision_key(tenant_id: int, model_id: int) -> str:
    return f"dsh_vision:{tenant_id}:{model_id}"


def repository(model_id: int):
    tenant = get_current_tenant_id()
    if tenant is None:
        raise DshAuthorizationUnavailableError()
    return DshSettingsRepository(_vision_key(tenant, model_id))


async def legacy_visual(model_id: int, tenant_id: int) -> bool | None:
    return (await _read_local_visuals(tenant_id)).get(str(model_id))


async def _read_local_visuals(tenant_id: int) -> dict[str, bool]:
    """Only an owner's local record is evidence; inherited JSON is not a grant."""
    from bisheng.core.database import get_async_db_session
    from bisheng.dsh.domain.services.profile import profile_scope
    from bisheng.llm.domain.repositories.model_default_repository import ModelDefaultRepository

    with profile_scope(tenant_id):
        async with get_async_db_session() as session:
            own = await ModelDefaultRepository().aget_own(session, "linsight_llm")
    payload = json.loads(own.payload_json) if own is not None else {}
    # Duplicate historical entries must not widen capability either.
    result = {}
    for item in payload.get("models", []):
        value = item.get("visual")
        if type(value) is bool:
            model_id = str(item.get("id"))
            result[model_id] = result.get(model_id, True) and value
    return result


def _parse_vision_declaration(raw: str | None) -> tuple[bool | None, bool]:
    stored = json.loads(raw) if raw else None
    if not stored:
        return None, False
    return VisionSetting.model_validate({"vision": stored["vision"]}).vision, stored.get("authority_version") == 1


def _merge_legacy_vision(explicit: bool | None, legacy: bool | None) -> bool | None:
    if explicit is False or legacy is False:
        return False
    return explicit if explicit is not None else legacy


async def _declaration(model_id: int, tenant_id: int) -> bool | None:
    from bisheng.dsh.domain.services.profile import profile_scope

    with profile_scope(tenant_id):
        raw = await repository(model_id).read()
    explicit, authoritative = _parse_vision_declaration(raw)
    if authoritative:
        return explicit
    return _merge_legacy_vision(explicit, await legacy_visual(model_id, tenant_id))


async def read_catalog_vision(models: list["LLMModel"]) -> dict[int, bool]:
    """Resolve image capability for already admitted catalog models."""
    if not models:
        return {}
    tenant = get_current_tenant_id()
    if tenant is None:
        raise DshAuthorizationUnavailableError()

    keys = {(scope, model.id): _vision_key(scope, model.id) for model in models for scope in (model.tenant_id, tenant)}
    stored = await DshSettingsRepository.read_many(list(keys.values()))
    declarations = {pair: _parse_vision_declaration(stored.get(key)) for pair, key in keys.items()}
    legacy_scopes = {scope for (scope, _), (_, authoritative) in declarations.items() if not authoritative}
    legacy = {scope: await _read_local_visuals(scope) for scope in sorted(legacy_scopes)}
    resolved = {
        (scope, model_id): explicit
        if authoritative
        else _merge_legacy_vision(explicit, legacy[scope].get(str(model_id)))
        for (scope, model_id), (explicit, authoritative) in declarations.items()
    }

    return {
        model.id: resolved[model.tenant_id, model.id] is True and resolved[tenant, model.id] is not False
        for model in models
    }


async def vision_view(model_id: int, *, snapshot=None) -> dict:
    from bisheng.llm.domain.services.llm import LLMService

    model, _server = snapshot or await LLMService.get_dsh_model_metadata_snapshot(model_id)
    tenant = get_current_tenant_id()
    if tenant is None:
        raise DshAuthorizationUnavailableError()
    owner = model.tenant_id
    owner_vision = await _declaration(model_id, owner)
    restriction = await _declaration(model_id, tenant) if owner != tenant else None
    effective = owner_vision is True and restriction is not False
    can_edit = owner == tenant or owner_vision is True
    return {
        "model_id": model_id,
        "vision": effective,
        "effective": effective,
        "owner_tenant_id": owner,
        "owner_vision": owner_vision is True,
        "source": "local_restriction" if restriction is False else "owner" if owner_vision is not None else "unknown",
        "can_edit": can_edit,
        "read_only": not can_edit,
        "status": "available",
        "reason": None,
    }


async def read_vision(model_id: int, *, snapshot=None) -> VisionSetting:
    return VisionSetting(vision=(await vision_view(model_id, snapshot=snapshot))["vision"])


async def configure_vision(model_id: int, setting: VisionSetting | None = None):
    from bisheng.llm.domain.services.llm import LLMService

    snapshot = await LLMService.get_dsh_model_metadata_snapshot(model_id)
    current = await vision_view(model_id, snapshot=snapshot)
    if setting is not None:
        if setting.vision and not current["owner_vision"] and current["owner_tenant_id"] != get_current_tenant_id():
            raise DshInvalidRequestError()
        # Only an explicit administrator save supersedes ambiguous historical keys.
        await repository(model_id).save(json.dumps({"vision": setting.vision, "authority_version": 1}))
        current = await vision_view(model_id, snapshot=snapshot)
    return current


async def batch_vision(model_ids: list[int]) -> list[dict]:
    result = []
    for model_id in dict.fromkeys(model_ids):
        if type(model_id) is not int or model_id <= 0:
            raise DshInvalidRequestError()
        try:
            result.append(await vision_view(model_id))
        except DshModelNotAllowedError:
            # A known refusal is row metadata; authorization outages still fail the request.
            result.append(
                {
                    "model_id": model_id,
                    "vision": False,
                    "effective": False,
                    "owner_tenant_id": None,
                    "owner_vision": False,
                    "source": "unknown",
                    "can_edit": False,
                    "read_only": True,
                    "status": "unavailable",
                    "reason": "model_not_allowed",
                }
            )
    return result
