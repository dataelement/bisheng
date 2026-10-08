"""Tenant-owned Desktop image capability, separate from webpage model settings."""

from pydantic import Field

from bisheng.common.errcode.dsh import DshAuthorizationUnavailableError
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.dsh.domain.repositories.settings import DshSettingsRepository
from bisheng.dsh.domain.schemas.contracts import DshContract


class VisionSetting(DshContract):
    vision: bool = Field(default=False, strict=True)


def repository(model_id: int):
    tenant = get_current_tenant_id()
    if tenant is None:
        raise DshAuthorizationUnavailableError()
    return DshSettingsRepository(f"dsh_vision:{tenant}:{model_id}")


async def read_vision(model_id: int) -> VisionSetting:
    raw = await repository(model_id).read()
    return VisionSetting.model_validate_json(raw) if raw else VisionSetting()


async def configure_vision(model_id: int, setting: VisionSetting | None = None):
    from bisheng.llm.domain.services.llm import LLMService

    await LLMService.get_dsh_model_snapshot(model_id)
    if setting is not None:
        await repository(model_id).save(setting.model_dump_json())
    return (await read_vision(model_id)).model_dump()
