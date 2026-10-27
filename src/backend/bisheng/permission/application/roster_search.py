"""Search the authorized roster across SQL cursor pages, resolving labels in batches."""


async def search_source_page(
    *, runtime, subjects, actor, target, after_id, page_size, keyword, subject_type, model_names
):
    query = keyword.strip().casefold()
    selected = []
    while True:
        rows, has_more = await runtime.list_permission_sources_page(
            actor=actor,
            target=target,
            after_id=after_id,
            limit=200,
        )
        if not rows:
            return selected, False
        names = (
            await subjects.display_names(tuple(dict.fromkeys((r.subject_type, r.subject_id) for r in rows)))
            if query
            else {}
        )
        for index, row in enumerate(rows):
            after_id = row.source_id
            if subject_type and row.subject_type != subject_type:
                continue
            values = (
                names.get((row.subject_type, row.subject_id)),
                row.subject_id,
                model_names.get(row.model_key),
                row.source_type,
                row.inherited_from,
            )
            if query and query not in " ".join(str(value) for value in values if value).casefold():
                continue
            selected.append(row)
            if len(selected) == page_size:
                return selected, has_more or index < len(rows) - 1
        if not has_more:
            return selected, False
