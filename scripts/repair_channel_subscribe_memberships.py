"""One-off compensation for channel-subscribe approvals stuck by the
find_membership ACTIVE-only filter bug.

For each affected instance the approval was marked EXECUTED but the applicant's
membership stayed PENDING and no ReBAC grant was written, so the channel never
appeared in the user's subscription list. This re-runs the (now fixed)
ChannelSubscribeScenarioHandler.on_approved() to flip the membership to ACTIVE
and write the OpenFGA relation.

Idempotent: re-running on an already-ACTIVE membership is a no-op upsert.

Run from src/backend with the same config the backend uses:
    config=config.yaml uv run python ../../scripts/repair_channel_subscribe_memberships.py
"""

from __future__ import annotations

import asyncio
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("repair_channel_subscribe")

# Affected instance ids discovered via the §11 diagnostic query.
INSTANCE_IDS = [248, 250, 251, 252]
TENANT_ID = 1


async def main() -> None:
    from bisheng.approval.domain.repositories.approval_instance_repository import ApprovalInstanceRepository
    from bisheng.approval.domain.services.approval_runtime_handler_factory import build_runtime_handler
    from bisheng.common.services.config_service import settings
    from bisheng.core.context import close_app_context, initialize_app_context
    from bisheng.core.context.tenant import set_current_tenant_id

    await initialize_app_context(config=settings)
    set_current_tenant_id(TENANT_ID)

    try:
        for instance_id in INSTANCE_IDS:
            instance = await ApprovalInstanceRepository.get_instance(instance_id)
            if instance is None:
                logger.warning("instance %s not found, skipping", instance_id)
                continue
            if instance.scenario_code != "channel_subscribe_request":
                logger.warning(
                    "instance %s is %s, not channel_subscribe_request, skipping",
                    instance_id, instance.scenario_code,
                )
                continue
            payload = instance.payload_snapshot or {}
            handler = await build_runtime_handler(instance.scenario_code)
            result = await handler.on_approved(instance_id, payload)
            logger.info(
                "repaired instance=%s channel_id=%s applicant=%s -> %s",
                instance_id, payload.get("channel_id"), payload.get("applicant_user_id"), result,
            )
    finally:
        await close_app_context()


if __name__ == "__main__":
    asyncio.run(main())
