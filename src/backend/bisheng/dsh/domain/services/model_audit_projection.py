"""Directory failures are isolated from committed audit facts."""

from loguru import logger


async def project_audit_groups(queries, tenant, cursor="", *, limit=100):
    if type(limit) is not int or not 1 <= limit <= 200:
        raise ValueError("Audit projection batch exceeds bounds")
    ids = await queries.execute(tenant, lambda repository: repository.projection_candidates(cursor=cursor, limit=limit))
    changed = 0
    for request_id in ids:
        try:
            changed += await queries.execute(
                tenant, lambda repository, request_id=request_id: repository.project_request(request_id)
            )
        except Exception as error:
            # This independent, rebuildable projection must not undo captured facts.
            logger.warning("DSH audit group projection failed ({})", type(error).__name__)
    return (ids[-1] if len(ids) == limit else None), changed
