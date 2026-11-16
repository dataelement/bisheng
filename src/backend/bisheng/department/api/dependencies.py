from bisheng.department.domain.services.directory_scope import organization_directory_scope


async def bind_directory_scope():
    async with organization_directory_scope():
        yield
