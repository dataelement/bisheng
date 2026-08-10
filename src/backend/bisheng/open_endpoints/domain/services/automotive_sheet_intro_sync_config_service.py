from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from bisheng.common.errcode.automotive_sheet_intro_sync import AutomotiveSheetIntroSyncInvalidConfigError
from bisheng.common.errcode.developer_token import DeveloperTokenDisabledError, DeveloperTokenMissingError
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.developer_token.domain.models import DeveloperToken
from bisheng.developer_token.domain.repositories.developer_token_repository import DeveloperTokenRepository
from bisheng.developer_token.domain.schemas import DeveloperTokenFileSyncRule
from bisheng.developer_token.domain.services.developer_token_service import DeveloperTokenService
from bisheng.open_endpoints.domain.repositories.interfaces.automotive_sheet_intro_sync_config_repository import (
    AutomotiveSheetIntroSyncConfigRepository,
)
from bisheng.open_endpoints.domain.schemas.automotive_sheet_intro_sync import (
    AutomotiveSheetIntroSyncConfig,
    default_automotive_sheet_intro_sync_config,
    strip_legacy_automotive_sheet_intro_sync_config_keys,
)


def build_file_sync_rule_from_token(token: DeveloperToken) -> DeveloperTokenFileSyncRule:
    if token.file_sync_rule is None:
        raise AutomotiveSheetIntroSyncInvalidConfigError(
            msg="developer token file sync rule is not configured",
        )
    return DeveloperTokenService._normalize_file_sync_rule(token.file_sync_rule)


class AutomotiveSheetIntroSyncConfigService:
    def __init__(self, config_repository: AutomotiveSheetIntroSyncConfigRepository) -> None:
        self.config_repository = config_repository

    @staticmethod
    def _assert_tenant_scope(tenant_id: int) -> None:
        current = get_current_tenant_id()
        if current is None or int(current) != int(tenant_id):
            raise AutomotiveSheetIntroSyncInvalidConfigError(msg="tenant context mismatch")

    async def get_config(self, tenant_id: int) -> AutomotiveSheetIntroSyncConfig:
        self._assert_tenant_scope(tenant_id)
        record = await self.config_repository.get(tenant_id)
        if record is None or not str(record.value or "").strip():
            return default_automotive_sheet_intro_sync_config()
        try:
            payload = json.loads(record.value)
        except json.JSONDecodeError as exc:
            raise AutomotiveSheetIntroSyncInvalidConfigError(msg="stored config is invalid JSON") from exc
        if not isinstance(payload, dict):
            raise AutomotiveSheetIntroSyncInvalidConfigError(msg="stored config must be a JSON object")
        defaults = default_automotive_sheet_intro_sync_config().model_dump(mode="json")
        merged = {**defaults, **strip_legacy_automotive_sheet_intro_sync_config_keys(payload)}
        return AutomotiveSheetIntroSyncConfig.model_validate(merged)

    async def save_config(
        self,
        tenant_id: int,
        payload: AutomotiveSheetIntroSyncConfig | dict[str, Any],
    ) -> AutomotiveSheetIntroSyncConfig:
        self._assert_tenant_scope(tenant_id)
        try:
            raw_payload = (
                payload.model_dump(mode="json")
                if isinstance(payload, AutomotiveSheetIntroSyncConfig)
                else dict(payload)
            )
            config = AutomotiveSheetIntroSyncConfig.model_validate(
                strip_legacy_automotive_sheet_intro_sync_config_keys(raw_payload)
            )
        except ValidationError as exc:
            raise AutomotiveSheetIntroSyncInvalidConfigError(msg="config validation failed") from exc

        if config.enabled:
            await self._validate_enabled_config(tenant_id, config)

        await self.config_repository.write_value(
            tenant_id,
            json.dumps(config.model_dump(mode="json"), ensure_ascii=False),
        )
        return config

    async def _validate_enabled_config(self, tenant_id: int, config: AutomotiveSheetIntroSyncConfig) -> None:
        token_id = int(config.developer_token_id or 0)
        token = await DeveloperTokenRepository.get_token_by_id(token_id)
        if token is None or int(token.tenant_id) != int(tenant_id):
            raise DeveloperTokenMissingError()
        if not bool(token.enabled):
            raise DeveloperTokenDisabledError()

        rule = build_file_sync_rule_from_token(token)
        await DeveloperTokenService._validate_file_sync_rule(
            int(tenant_id),
            int(token.user_id),
            rule,
        )
        folder_id = None
        if rule.target_space.folder_mode == "fixed":
            folder_id = rule.target_space.folder_id
        knowledge_id = rule.target_space.knowledge_id
        if rule.target_space.mode != "fixed" or knowledge_id is None:
            raise AutomotiveSheetIntroSyncInvalidConfigError(
                msg="developer token file sync rule must use a fixed target space",
            )
        await DeveloperTokenService._validate_file_sync_target(
            tenant_id=int(tenant_id),
            user_id=int(token.user_id),
            knowledge_id=int(knowledge_id),
            folder_id=folder_id,
        )
