"""App-publish withdrawal; target and actual operator are supplied by the authorized business service."""


async def withdraw_app_publish(expected, *, operator_user_id, operator_user_name, reason, actor_metadata):
    from bisheng.approval.domain.services.approval_center_service import ApprovalCenterService

    return await ApprovalCenterService.withdraw_app_publish(
        expected,
        operator_user_id=operator_user_id,
        operator_user_name=operator_user_name,
        reason=reason,
        actor_metadata=actor_metadata,
    )
