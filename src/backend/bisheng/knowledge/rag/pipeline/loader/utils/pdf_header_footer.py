import re
from collections import defaultdict
from typing import Dict, Iterable, List


def normalize_header_footer_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def is_probable_page_marker(text: str) -> bool:
    normalized = normalize_header_footer_text(text).lower()
    if not normalized:
        return False
    patterns = [
        r"^\d+$",
        r"^\d+\s*/\s*\d+$",
        r"^page\s*\d+$",
        r"^page\s*\d+\s*/\s*\d+$",
        r"^第\s*\d+\s*页$",
    ]
    return any(re.fullmatch(pattern, normalized) for pattern in patterns)


def filter_repeated_header_footer_blocks(
        blocks: Iterable[Dict],
        top_ratio: float = 0.12,
        bottom_ratio: float = 0.12,
) -> List[Dict]:
    blocks = list(blocks)
    if not blocks:
        return []

    page_heights: Dict[int, float] = defaultdict(float)
    for block in blocks:
        bbox = block.get("bbox") or []
        page = int(block.get("page", 0))
        if len(bbox) >= 4:
            page_heights[page] = max(page_heights[page], float(bbox[3]))

    repeated_top: Dict[str, set] = defaultdict(set)
    repeated_bottom: Dict[str, set] = defaultdict(set)
    for block in blocks:
        bbox = block.get("bbox") or []
        if len(bbox) < 4:
            continue
        text = normalize_header_footer_text(block.get("text", ""))
        if not text:
            continue
        page = int(block.get("page", 0))
        page_height = page_heights.get(page) or float(bbox[3]) or 0
        if page_height <= 0:
            continue
        y0 = float(bbox[1])
        y1 = float(bbox[3])
        if y0 <= page_height * top_ratio:
            repeated_top[text].add(page)
        if y1 >= page_height * (1 - bottom_ratio):
            repeated_bottom[text].add(page)

    repeated_top = {text for text, pages in repeated_top.items() if len(pages) >= 2}
    repeated_bottom = {text for text, pages in repeated_bottom.items() if len(pages) >= 2}

    filtered_blocks: List[Dict] = []
    for block in blocks:
        bbox = block.get("bbox") or []
        if len(bbox) < 4:
            filtered_blocks.append(block)
            continue

        page = int(block.get("page", 0))
        page_height = page_heights.get(page) or float(bbox[3]) or 0
        if page_height <= 0:
            filtered_blocks.append(block)
            continue

        text = normalize_header_footer_text(block.get("text", ""))
        y0 = float(bbox[1])
        y1 = float(bbox[3])
        in_top_zone = y0 <= page_height * top_ratio
        in_bottom_zone = y1 >= page_height * (1 - bottom_ratio)

        should_skip = False
        if text:
            if in_top_zone and text in repeated_top:
                should_skip = True
            elif in_bottom_zone and text in repeated_bottom:
                should_skip = True
            elif (in_top_zone or in_bottom_zone) and is_probable_page_marker(text):
                should_skip = True

        if not should_skip:
            filtered_blocks.append(block)

    return filtered_blocks
