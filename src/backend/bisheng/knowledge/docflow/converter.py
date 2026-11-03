"""Deterministic Markdown emission with spans in the FINAL output string."""

import html
import math
import statistics
from dataclasses import dataclass, field

from .client import DocFlowError

CONVERTER_VERSION = "1"


def rectangle(position):
    if not isinstance(position, list) or len(position) not in (4, 8):
        return None
    try:
        values = [float(number) for number in position]
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(number) for number in values):
        return None
    if len(values) == 8:
        return [min(values[::2]), min(values[1::2]), max(values[::2]), max(values[1::2])]
    return values if values[2] >= values[0] and values[3] >= values[1] else None


@dataclass
class Converted:
    text: str = ""
    spans: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    recognized_char_count: int = 0

    def literal(self, value):
        self.text += value

    def source(self, value, page, bbox, kind="text", html_cell=False):
        # Escape markup without allowing recognized text to inject headings,
        # HTML, links or table delimiters. Offsets include the escaped content.
        escaped = html.escape(value, quote=False)
        if not html_cell:
            escaped = escaped.replace("\\", "\\\\")
            for character in ("|", "*", "_", "`", "[", "]", "#"):
                escaped = escaped.replace(character, "\\" + character)
        self.recognized_char_count += len(value.strip())
        start = len(self.text)
        self.text += escaped
        if escaped and bbox:
            self.spans.append(
                {"start": start, "end": len(self.text), "page": page, "bbox": bbox, "type": kind, "text": escaped}
            )


def _rows(lines):
    """Top-edge grouping avoids attaching tall values to English sublabels."""
    rows = []
    for line in sorted(lines, key=lambda value: (value["bbox"][1], value["bbox"][0])):
        bbox = line["bbox"]
        candidate = None
        for row in rows:
            if abs(bbox[1] - row["top"]) > 0.65 * min(bbox[3] - bbox[1], row["height"]):
                continue
            if any(min(bbox[2], part["bbox"][2]) > max(bbox[0], part["bbox"][0]) for part in row["parts"]):
                continue
            candidate = row
            break
        if candidate is None:
            rows.append({"top": bbox[1], "height": bbox[3] - bbox[1], "parts": [line]})
        else:
            candidate["parts"].append(line)
            candidate["top"] = min(candidate["top"], bbox[1])
    return sorted(rows, key=lambda value: value["top"])


def _regions(lines):
    """Conservative whitespace cuts for paragraph columns, not form labels."""
    if len(lines) < 4:
        return [lines]
    left = min(line["bbox"][0] for line in lines)
    right = max(line["bbox"][2] for line in lines)
    height = statistics.median(line["bbox"][3] - line["bbox"][1] for line in lines)
    by_x = sorted(lines, key=lambda line: line["bbox"][0])
    edge = by_x[0]["bbox"][2]
    for index, line in enumerate(by_x[1:], 1):
        if line["bbox"][0] - edge > max(height * 2, (right - left) * 0.06):
            first, second = by_x[:index], by_x[index:]
            # Require sustained, wide text on both sides. Short labels and stamp
            # fragments must stay in their original rows rather than become columns.
            if min(len(first), len(second)) >= 4 and all(
                statistics.median(part["bbox"][2] - part["bbox"][0] for part in side) >= (right - left) * 0.22
                for side in (first, second)
            ):
                return _regions(first) + _regions(second)
        edge = max(edge, line["bbox"][2])
    by_y = sorted(lines, key=lambda line: line["bbox"][1])
    edge = by_y[0]["bbox"][3]
    cuts = []
    for index, line in enumerate(by_y[1:], 1):
        gap = line["bbox"][1] - edge
        if gap > height * 1.25:
            cuts.append((gap, -abs(index - len(by_y) / 2), index))
        edge = max(edge, line["bbox"][3])
    if cuts:
        index = max(cuts)[2]
        return _regions(by_y[:index]) + _regions(by_y[index:])
    return [lines]


def _tables(file, page_number):
    """Accept explicit row/cell grids only, never infer a schema from KIE keys."""
    tables = []
    for table in (file.get("data") or {}).get("tables") or []:
        raw_rows = table.get("rows") or table.get("items")
        if not isinstance(raw_rows, list) or not raw_rows:
            continue
        rows = []
        valid = True
        for raw_row in raw_rows:
            cells = raw_row.get("cells") if isinstance(raw_row, dict) else raw_row
            if not isinstance(cells, list) or not cells:
                valid = False
                break
            row = []
            for raw_cell in cells:
                if not isinstance(raw_cell, dict):
                    valid = False
                    break
                value = raw_cell.get("text", raw_cell.get("value", ""))
                position = raw_cell.get("position")
                cell_page = raw_cell.get("page", table.get("page", 0))
                if isinstance(position, list) and position and isinstance(position[0], dict):
                    if len(position) != 1:
                        valid = False
                        break
                    cell_page = position[0].get("page", cell_page)
                    position = position[0].get("vertices")
                bbox = rectangle(position)
                if bbox is None or bbox[2] <= bbox[0] or bbox[3] <= bbox[1] or not isinstance(value, (str, int, float)):
                    valid = False
                    break
                if int(cell_page) != page_number - 1:
                    valid = False
                    break
                rowspan, colspan = raw_cell.get("rowspan", 1), raw_cell.get("colspan", 1)
                if (
                    not isinstance(rowspan, int)
                    or not isinstance(colspan, int)
                    or not (1 <= rowspan <= 100 and 1 <= colspan <= 100)
                ):
                    valid = False
                    break
                row.append({"text": str(value), "bbox": bbox, "rowspan": rowspan, "colspan": colspan})
            if not valid:
                break
            rows.append(row)
        if valid and rows:
            cells = [cell for row in rows for cell in row]
            bbox = [
                min(cell["bbox"][0] for cell in cells),
                min(cell["bbox"][1] for cell in cells),
                max(cell["bbox"][2] for cell in cells),
                max(cell["bbox"][3] for cell in cells),
            ]
            tables.append(
                {"bbox": bbox, "rows": rows, "kind": "table", "text": "", "has_header": table.get("has_header") is True}
            )
    return tables


def convert_results(files, *, filter_page_header_footer=False):
    """Convert complete OCR lines. Never replace full text with configured KIE fields.

    Arbitrary DocFlow `data.tables.items` schemas are deliberately not guessed.
    Explicit document-line block types (title/heading/list) are honored; otherwise
    conservative geometry groups text. All OCR lines remain in the output.
    """
    output = Converted()
    page_number = 0
    for file in files:
        document = file.get("document") or (file.get("data") or {}).get("document")
        pages = document.get("pages", []) if isinstance(document, dict) else document
        if not isinstance(pages, list) or not pages:
            raise DocFlowError("DocFlow conversion: full document pages are missing; enable with_document")
        expected = int(file.get("total_page_num") or len(pages))
        if expected != len(pages):
            raise DocFlowError("DocFlow conversion: incomplete page results")
        for local_page, page in enumerate(pages, 1):
            page_number += 1
            if output.text:
                output.literal("\n\n")
            lines = []
            unmapped = []
            tables = _tables(file, local_page)
            if (file.get("data") or {}).get("tables") and not tables:
                output.warnings.append("structured_tables_unmapped: preserving source OCR lines")
            for raw in page.get("lines", []):
                if isinstance(raw, str):
                    value, bbox, kind = raw, None, "text"
                else:
                    value = raw.get("text") or raw.get("content") or ""
                    bbox = rectangle(raw.get("position"))
                    kind = str(raw.get("type") or raw.get("block_type") or "text").lower()
                if not isinstance(value, str) or not value.strip():
                    continue
                if filter_page_header_footer and kind in ("header", "footer"):
                    continue
                entry = {"text": value.strip(), "bbox": bbox, "kind": kind}
                # Suppress only OCR text actually accounted for by an overlapping
                # source cell. Identical text outside the cell must survive.
                covered = False
                if bbox:
                    for table in tables:
                        for cell in (cell for row in table["rows"] for cell in row):
                            cb = cell["bbox"]
                            inside = (
                                bbox[0] >= cb[0] - 2
                                and bbox[1] >= cb[1] - 2
                                and bbox[2] <= cb[2] + 2
                                and bbox[3] <= cb[3] + 2
                            )
                            if inside and "".join(value.split()) in "".join(cell["text"].split()):
                                covered = True
                if covered:
                    continue
                if bbox and bbox[3] > bbox[1]:
                    lines.append(entry)
                else:
                    unmapped.append(entry)
            heights = [line["bbox"][3] - line["bbox"][1] for line in lines]
            median_height = statistics.median(heights) if heights else 1
            rows = [row for region in _regions(lines + tables) for row in _rows(region)]
            left = min((line["bbox"][0] for line in lines), default=0)
            right = max((line["bbox"][2] for line in lines), default=1)
            previous_bottom = None
            for row_index, row in enumerate(rows):
                if row_index:
                    gap = row["top"] - previous_bottom
                    output.literal("\n\n" if gap > median_height * 0.8 or gap < -median_height else "\n")
                parts = sorted(row["parts"], key=lambda line: line["bbox"][0])
                for index, part in enumerate(parts):
                    if index:
                        output.literal("　")
                    bbox, kind = part["bbox"], part["kind"]
                    if kind == "table":
                        simple = len({len(cells) for cells in part["rows"]}) == 1 and all(
                            cell["rowspan"] == cell["colspan"] == 1 for cells in part["rows"] for cell in cells
                        )
                        if simple:
                            output.literal("\n\n")
                            if not part["has_header"]:
                                output.literal("|" + " |" * len(part["rows"][0]) + "\n")
                                output.literal("|" + " --- |" * len(part["rows"][0]) + "\n")
                            for row_number, cells in enumerate(part["rows"]):
                                output.literal("| ")
                                for cell_number, cell in enumerate(cells):
                                    if cell_number:
                                        output.literal(" | ")
                                    output.source(cell["text"], page_number, cell["bbox"], "Table")
                                output.literal(" |\n")
                                if row_number == 0 and part["has_header"]:
                                    output.literal("|" + " --- |" * len(cells) + "\n")
                            output.literal("\n")
                            continue
                        output.literal("\n\n<table>\n")
                        for cells in part["rows"]:
                            output.literal("<tr>")
                            for cell in cells:
                                output.literal(f'<td rowspan="{cell["rowspan"]}" colspan="{cell["colspan"]}">')
                                output.source(cell["text"], page_number, cell["bbox"], "Table", html_cell=True)
                                output.literal("</td>")
                            output.literal("</tr>\n")
                        output.literal("</table>\n\n")
                        continue
                    explicit_heading = kind in ("title", "heading", "doc_title", "paragraph_title")
                    inferred_heading = (
                        len(parts) == 1
                        and row_index < 2
                        and bbox[3] - bbox[1] > median_height * 1.5
                        and bbox[2] - bbox[0] > (right - left) * 0.6
                    )
                    if explicit_heading or inferred_heading:
                        output.literal("# " if kind in ("doc_title", "title") or row_index == 0 else "## ")
                        kind = "Title"
                    output.source(part["text"], page_number, bbox, kind)
                previous_bottom = max(part["bbox"][3] for part in parts)
            if unmapped:
                output.warnings.append(f"page_{page_number}: lines_without_coordinates")
                for part in unmapped:
                    if output.text:
                        output.literal("\n")
                    output.source(part["text"], page_number, None)
    if not output.recognized_char_count:
        raise DocFlowError("DocFlow conversion: no recognized text")
    return output
