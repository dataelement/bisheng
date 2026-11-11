"""Strict admission for the whole persisted channel/current automation source."""

import json
from dataclasses import dataclass, field
from datetime import datetime

from bisheng.channel.application.automation_identity import assert_channel_automation_identity
from bisheng.channel.domain.repositories.reference_source_repository import ChannelReferenceSourceRepository
from bisheng.common.dependencies.user_deps import UserPayload
from bisheng.common.errcode.knowledge import ResourceReferenceInvalidError
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.core.database import get_async_db_session
from bisheng.permission.application.business_authorization import require_business_action
from bisheng.resource_reference.application.source_access import get_reference_read_runtime
from bisheng.resource_reference.application.source_contracts import SourceReadRequest, SourceReferenceReadResult


@dataclass(frozen=True)
class PreparedChannelDelivery:
    identity: UserPayload = field(repr=False)
    read: SourceReferenceReadResult
    config_id: str

    @property
    def channel(self):
        return json.loads(self.read.snapshot.payload_json)["channel"]

    @property
    def config(self):
        return next(row for row in json.loads(self.read.snapshot.payload_json)["sync"] if row["id"] == self.config_id)


class ChannelSyncExecutionAdmission:
    @classmethod
    async def prepare(cls, identity, channel_id: str, sync_config_id: str, detected_at: int, *, session=None):
        tenant_id = get_current_tenant_id()
        if type(detected_at) is not int or detected_at < 0:
            raise ResourceReferenceInvalidError(reason="channel_delivery_time_invalid")
        await assert_channel_automation_identity(identity, channel_id, sync_config_id, tenant_id=tenant_id)

        async def admit(active):
            runtime = await get_reference_read_runtime()
            scope = await runtime.verifier.aissue_scope(
                active, SourceReadRequest("channel_sync", channel_id, "current"), identity
            )
            # AC-92: all saved choices, including disabled branches, remain in
            # this complete set. A selected target is never a subset permit.
            result = await runtime.arequire_source_valid(active, scope, identity)
            payload = json.loads(result.snapshot.payload_json)
            config = next((row for row in payload["sync"] if row["id"] == sync_config_id), None)
            if (
                payload["channel"]["tenant_id"] != tenant_id
                or config is None
                or config["user_id"] != identity.user_id
                or not config["is_enabled"]
            ):
                raise ResourceReferenceInvalidError(reason="channel_delivery_configuration_invalid")
            effective_at = max(
                datetime.fromisoformat(config[key]).timestamp() for key in ("create_time", "update_time")
            )
            if effective_at > detected_at:
                raise ResourceReferenceInvalidError(reason="channel_delivery_configuration_not_effective")
            if config["sub_channel_name"] and not any(
                rule.get("channel_type") == "sub" and rule.get("name") == config["sub_channel_name"]
                for rule in payload["channel"]["filter_rules"]
                if isinstance(rule, dict)
            ):
                raise ResourceReferenceInvalidError(reason="channel_delivery_rule_missing")
            await ChannelReferenceSourceRepository().aload_delivery_target(
                active,
                config["knowledge_space_id"],
                config["folder_id"],
                identity.user_id,
            )
            await require_business_action(
                identity,
                resource_type="folder" if config["folder_id"] is not None else "knowledge_space",
                resource_id=int(
                    config["folder_id"] if config["folder_id"] is not None else config["knowledge_space_id"]
                ),
                action="upload_file",
            )
            await assert_channel_automation_identity(identity, channel_id, sync_config_id, tenant_id=tenant_id)
            return PreparedChannelDelivery(identity, result, sync_config_id)

        if session is not None:
            if not session.in_transaction():
                raise ResourceReferenceInvalidError(reason="channel_delivery_transaction_required")
            return await admit(session)
        async with get_async_db_session() as owned, owned.begin():
            return await admit(owned)
