"""Publish-owned immutable delivery projections."""


async def preview_migration_plan(manifest):
    from bisheng.app_publish.domain.services.schema_evolution_service import migration_plan, tables_of

    return migration_plan([], tables_of(manifest))


async def declared_scopes(capabilities):
    from bisheng.app_publish.domain.services.capability_bus_service import derive_scopes, parse_declaration

    return derive_scopes(parse_declaration(capabilities or {}))
