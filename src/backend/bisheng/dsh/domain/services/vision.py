"""Owner image capability and tenant restrictions, shared by both chat modes."""

import json
from typing import Annotated

from pydantic import Field

from bisheng.common.errcode.dsh import (
    DshAuthorizationUnavailableError,
    DshInvalidRequestError,
    DshModelNotAllowedError,
)
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.dsh.domain.repositories.settings import DshSettingsRepository
from bisheng.dsh.domain.schemas.contracts import DshContract


class VisionSetting(DshContract):
    vision: bool = Field(default=False, strict=True)


class VisionBatchRequest(DshContract):
    model_ids: list[Annotated[int, Field(strict=True, gt=0, le=9223372036854775807)]] = Field(max_length=200)


def repository(model_id: int):
    tenant = get_current_tenant_id()
    if tenant is None:
        raise DshAuthorizationUnavailableError()
    return DshSettingsRepository(f"dsh_vision:{tenant}:{model_id}")


async def legacy_visual(model_id: int, tenant_id: int) -> bool | None:
    """Only an owner's local record is evidence; inherited JSON is not a grant."""
    from bisheng.core.database import get_async_db_session
    from bisheng.dsh.domain.services.profile import profile_scope
    from bisheng.llm.domain.repositories.model_default_repository import ModelDefaultRepository

    with profile_scope(tenant_id):
        async with get_async_db_session() as session:
            own = await ModelDefaultRepository().aget_own(session, "linsight_llm")
    if own is None:
        return None
    payload = json.loads(own.payload_json)
    values = [
        item["visual"]
        for item in payload.get("models", [])
        if str(item.get("id")) == str(model_id) and type(item.get("visual")) is bool
    ]
    # Duplicate historical entries must not widen capability either.
    return all(values) if values else None


async def _declaration(model_id: int, tenant_id: int) -> bool | None:
    from bisheng.dsh.domain.services.profile import profile_scope

    with profile_scope(tenant_id):
        raw = await repository(model_id).read()
    stored = json.loads(raw) if raw else None
    explicit = VisionSetting.model_validate({"vision": stored["vision"]}).vision if stored else None
    if stored and stored.get("authority_version") == 1:
        return explicit
    legacy = await legacy_visual(model_id, tenant_id)
    if explicit is False or legacy is False:
        return False
    return explicit if explicit is not None else legacy


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
