"""Optional owned upload preparation around the original SPACE registration."""

from loguru import logger

from bisheng.common.errcode.knowledge import KnowledgeOperationPlanConflictError, KnowledgeProcessingJobNotFoundError
from bisheng.knowledge.domain.services.upload_preview_service import UploadPreviewService, digest


async def register_owned_upload(space_service, space_id, request, *, folder=False):
    preview = UploadPreviewService(space_service)
    context = request.upload_context
    paths = [i.file_path for i in request.items] if folder else request.file_path
    if (
        len(set(paths)) != len(paths)
        or set(paths) != {i.file_path for i in context.items}
        or len(paths) != len(context.items)
    ):
        raise KnowledgeOperationPlanConflictError()
    if len({i.upload_id for i in context.items}) != len(context.items):
        raise KnowledgeOperationPlanConflictError()
    request_digest = digest(request.model_dump(mode="json"))
    receipts = []
    for item in context.items:
        receipt = await preview.read(space_id, item.upload_id)
        if receipt["parent_id"] != request.parent_id or receipt["file_path"] != item.file_path:
            raise KnowledgeProcessingJobNotFoundError()
        receipts.append(receipt)
    if all(r["state"] == "COMMITTED" and r.get("request_digest") == request_digest for r in receipts):
        return [row for r in receipts for row in r["rows"]]
    if any(r["state"] != "OPEN" for r in receipts):
        raise KnowledgeOperationPlanConflictError()
    entries = {}
    frozen = []
    try:
        for receipt, item in zip(receipts, context.items, strict=True):
            entries[item.file_path] = await preview.freeze(receipt, item, context.mode, request_digest)
            frozen.append(item.upload_id)
    except BaseException:
        # No business registration has started; only this request's reservations can be released.
        for upload_id in frozen:

            def release(value):
                if value["state"] == "COMMITTING" and value.get("request_digest") == request_digest:
                    value["state"] = "OPEN"

            try:
                await preview.repository.mutate(upload_id, release)
            except Exception:
                logger.exception("Upload reservation release failed for upload={}", upload_id)
        raise
    if folder:
        result = await space_service.upload_folder_items(
            space_id, request.items, request.parent_id, processing_overrides=request.overrides, _upload_entries=entries
        )
    else:
        result = await space_service.add_file(
            space_id,
            request.file_path,
            request.parent_id,
            processing_overrides=request.overrides,
            _upload_entries=entries,
        )
    # An exception after entering registration keeps COMMITTING: never infer safe retry from a lost ACK.
    for item in context.items:

        def complete(value, rows=entries[item.file_path].rows):
            if value["state"] != "COMMITTING" or value.get("request_digest") != request_digest:
                raise KnowledgeOperationPlanConflictError()
            value.update(state="COMMITTED", rows=rows)

        await preview.repository.mutate(item.upload_id, complete)
    return result
