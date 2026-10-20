"""Directory failures are isolated from committed audit facts."""

from loguru import logger


async def project_audit_groups(queries, tenant, cursor=""):
    ids = await queries.execute(tenant, lambda repository: repository.projection_candidates(cursor=cursor))
    changed = 0
    for request_id in ids:
        try:
            changed += await queries.execute(
                tenant, lambda repository, request_id=request_id: repository.project_request(request_id)
            )
        except Exception as error:
            # This independent, rebuildable projection must not undo captured facts.
            logger.warning("DSH audit group projection failed ({})", type(error).__name__)
    return (ids[-1] if len(ids) == 100 else None), changed
