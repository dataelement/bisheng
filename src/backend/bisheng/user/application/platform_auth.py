"""Password login application seam; credential validation precedes issuance."""


async def validate_password_identity(body, request, response):
    from bisheng.user.domain.models.user import UserLogin
    from bisheng.user.domain.services.user import UserService

    return await UserService.authenticate_password(request, UserLogin(**body))


async def issue_password_session(identity, request, service, body):
    from bisheng.user.domain.services.user import UserService

    data = await service.issue(
        identity.user.user_id,
        identity.tenant_id,
        body.client_id,
        device_label=body.device_label,
        client_version=body.client_version,
    )
    entry, _ = await UserService.complete_password_login(request, identity)
    data["default_entry"] = entry.get("default_entry", data["default_entry"])
    return data
