from typing import Self

from pydantic import BaseModel, ConfigDict, Field

from bisheng.common.constants.enums.telemetry import ApplicationTypeEnum

from ..models import LLMDao, LLMModel, LLMServer
from ..share_fallback import (
    aget_model_by_id_with_share_fallback,
    aget_server_by_id_with_share_fallback,
    get_model_by_id_with_share_fallback,
    get_server_by_id_with_share_fallback,
)


class BishengBase(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, validate_by_name=True, validate_by_alias=True)

    model_id: int = Field(description="Saved by backend servicemodelUniqueness quantificationID")
    model_name: str = Field(default="", description="model name in mysql")

    # field for telemetry logging
    app_id: str = Field(..., description="application id")
    app_type: ApplicationTypeEnum = Field(..., description="application type")
    app_name: str = Field(..., description="application name")
    user_id: int = Field(..., description="invoke user id")

    # bishengStrongly related business parameters
    model_info: LLMModel | None = Field(default=None, description="Model Configuration Information")
    server_info: LLMServer | None = Field(default=None, description="Service Provider Information")

    @classmethod
    async def get_class_instance(cls, **kwargs: dict) -> Self:
        model_id: int | None = kwargs.pop("model_id", None)
        model_info, server_info = await cls.get_model_server_info(model_id)
        instance = cls(
            model_id=model_id,
            model_name=model_info.model_name,
            model_info=model_info,
            server_info=server_info,
            **kwargs,
        )
        return instance

    @classmethod
    def get_class_instance_from_snapshot(
        cls, *, model_info: LLMModel, server_info: LLMServer, disable_retries: bool = False, **kwargs
    ) -> Self:
        """Build from an already authorized snapshot without another cached read."""
        if "model_id" in kwargs or "model_name" in kwargs:
            raise ValueError("Snapshot identity cannot be overridden")
        if model_info is None or server_info is None or model_info.server_id != server_info.id:
            raise ValueError("Model and provider snapshots must match")
        model_info = model_info.model_copy(deep=True)
        if disable_retries:
            import json

            config = dict(model_info.config or {})
            user_kwargs = config.get("user_kwargs") or {}
            if isinstance(user_kwargs, str):
                user_kwargs = json.loads(user_kwargs)
            config["user_kwargs"] = {**user_kwargs, "max_retries": 0}
            model_info.config = config
        return cls(
            model_id=model_info.id,
            model_name=model_info.model_name,
            model_info=model_info.model_copy(deep=True),
            server_info=server_info.model_copy(deep=True),
            **kwargs,
        )

    @classmethod
    async def get_model_server_info(cls, model_id: int | None) -> tuple[LLMModel | None, LLMServer | None]:
        # Root-share fallback handles the system-default case where the
        # model_id resolved via tenant_system_model_config points to a
        # Root-owned row that the child's tenant filter would otherwise hide.
        if not model_id:
            return None, None
        model_info = await aget_model_by_id_with_share_fallback(model_id, cache=True)
        if not model_info:
            return None, None
        server_info = await aget_server_by_id_with_share_fallback(
            model_info.server_id,
            cache=True,
        )
        return model_info, server_info

    @classmethod
    def get_model_server_info_sync(cls, model_id: int | None) -> tuple[LLMModel | None, LLMServer | None]:
        if not model_id:
            return None, None
        model_info = get_model_by_id_with_share_fallback(model_id, cache=True)
        if not model_info:
            return None, None
        server_info = get_server_by_id_with_share_fallback(
            model_info.server_id,
            cache=True,
        )
        return model_info, server_info

    async def update_model_status(self, status: int, remark: str = ""):
        """Update model status"""
        if self.model_info.status != status:
            self.model_info.status = status
            await LLMDao.aupdate_model_status(
                self.model_id, status, remark[-500:]
            )  # Limit note length to500characters.

    def sync_update_model_status(self, status: int, remark: str = ""):
        """Update model status"""
        if self.model_info.status != status:
            self.model_info.status = status
            LLMDao.update_model_status(self.model_id, status, remark[-500:])

    def get_server_info_config(self):
        if self.server_info and self.server_info.config:
            return self.server_info.config
        return {}

    def get_model_info_config(self):
        if self.model_info and self.model_info.config:
            return self.model_info.config
        return {}
