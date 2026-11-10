"""Normalize citation output without rewriting provider-specific stored coordinates."""

import json


def normalize_citation_coordinates(
    bbox: str | None, page: int | None, *, default_base: int | None = None
) -> tuple[str | None, int | None]:
    """Consume an explicit origin (or a known file provider), exactly once.

    Unlabelled temporary citations have no trustworthy provider identity, so
    their historical coordinates are left alone. The marker lives inside the
    existing bbox JSON field and survives the temporary-index field whitelist.
    """
    if not bbox:
        parsed = {}
    else:
        try:
            parsed = json.loads(bbox)
        except (TypeError, ValueError):
            return bbox, page
        if not isinstance(parsed, dict):
            return bbox, page
    base = parsed.get("page_base", default_base)
    if type(base) is not int or base != 1:
        return bbox, page

    boxes = parsed.get("chunk_bboxes")
    if boxes is None:
        # The legacy per-file bbox artifact is keyed by page/rectangle rather
        # than chunk_bboxes. Present that fallback in the shared viewer's shape.
        boxes = [value for value in parsed.values() if isinstance(value, dict) and "bbox" in value and "page" in value]
        if boxes:
            parsed = {"chunk_bboxes": boxes}
    if isinstance(boxes, list):
        for box in boxes:
            if isinstance(box, dict) and type(box.get("page")) is int and box["page"] >= 1:
                box["page"] -= 1
    if type(page) is int and page >= 1:
        page -= 1
    parsed["page_base"] = 0
    return json.dumps(parsed, ensure_ascii=False), page
