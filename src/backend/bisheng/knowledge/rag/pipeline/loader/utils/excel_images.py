"""Extract pictures embedded in an xlsx workbook, grouped by the sheet they sit on.

openpyxl is not used here: it only exposes images through the private
``worksheet._images`` and drops anchors it does not understand. Reading the OPC
package directly is both complete and cheap.

A picture belongs to exactly one sheet, and that ownership is only discoverable
through the relationship chain:

    workbook.xml <sheet r:id>
      -> workbook.xml.rels          rId  -> worksheets/sheetN.xml
      -> sheetN.xml.rels            drawing -> drawings/drawingM.xml
      -> drawingM.xml.rels          r:embed -> media/imageX.png

Sheet order and file numbering are unrelated (deleting a sheet leaves gaps in
sheetN.xml), so the chain must be followed instead of pairing them positionally.
"""

import posixpath
import zipfile
from dataclasses import dataclass
from xml.etree import ElementTree

from loguru import logger

RELS_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
IMAGE_EXTENSIONS = frozenset({"png", "jpg", "jpeg", "gif", "bmp", "tiff", "tif", "jfif"})


@dataclass
class ExcelImage:
    """One embedded picture and the sheet it is anchored to."""

    sheet_name: str
    # Media part name inside the package, e.g. "image1.png". Unique per workbook.
    media_name: str
    ext: str
    content: bytes


def _local_name(tag: str) -> str:
    """Strip the ``{namespace}`` prefix ElementTree keeps on every tag."""
    return tag.rsplit("}", 1)[-1]


def _find_all(root: ElementTree.Element, local_name: str) -> list[ElementTree.Element]:
    """Find descendants by local name — OOXML namespace prefixes are arbitrary."""
    return [el for el in root.iter() if _local_name(el.tag) == local_name]


def _resolve(base_dir: str, target: str) -> str:
    """Resolve a relationship target (often "../drawings/x.xml") to a package path."""
    if target.startswith("/"):
        return target.lstrip("/")
    return posixpath.normpath(posixpath.join(base_dir, target))


def _rels_path(part_path: str) -> str:
    base_dir, name = posixpath.split(part_path)
    return posixpath.join(base_dir, "_rels", f"{name}.rels")


def _read_xml(zf: zipfile.ZipFile, path: str) -> ElementTree.Element | None:
    try:
        return ElementTree.fromstring(zf.read(path))
    except KeyError:
        return None
    except ElementTree.ParseError:
        logger.warning("excel image extraction: malformed xml part {}", path)
        return None


def _read_relationships(zf: zipfile.ZipFile, part_path: str) -> dict[str, tuple[str, str]]:
    """Map rId -> (relationship type, resolved package path)."""
    root = _read_xml(zf, _rels_path(part_path))
    if root is None:
        return {}

    base_dir = posixpath.dirname(part_path)
    rels: dict[str, tuple[str, str]] = {}
    for rel in _find_all(root, "Relationship"):
        rel_id = rel.get("Id")
        target = rel.get("Target")
        if not rel_id or not target or rel.get("TargetMode") == "External":
            continue
        rels[rel_id] = (rel.get("Type") or "", _resolve(base_dir, target))
    return rels


def _drawing_media_paths(zf: zipfile.ZipFile, drawing_path: str) -> list[str]:
    """Package paths of the media referenced by one drawing, in document order."""
    root = _read_xml(zf, drawing_path)
    if root is None:
        return []

    rels = _read_relationships(zf, drawing_path)
    paths: list[str] = []
    for blip in _find_all(root, "blip"):
        rel_id = blip.get(f"{{{RELS_NS}}}embed")
        if not rel_id or rel_id not in rels:
            continue
        # The same picture may be anchored more than once on a sheet; one copy is enough.
        media_path = rels[rel_id][1]
        if media_path not in paths:
            paths.append(media_path)
    return paths


def extract_excel_images(xlsx_path: str) -> list[ExcelImage]:
    """Return every embedded picture together with its owning sheet.

    Returns an empty list for anything that is not a readable xlsx package
    (legacy .xls is an OLE container, not a zip) — callers treat picture
    extraction as best effort and must not fail the file over it.
    """
    try:
        with zipfile.ZipFile(xlsx_path) as zf:
            return _extract(zf)
    except (zipfile.BadZipFile, OSError) as e:
        logger.warning("excel image extraction skipped for {}: {}", xlsx_path, e)
        return []


def _extract(zf: zipfile.ZipFile) -> list[ExcelImage]:
    workbook = _read_xml(zf, "xl/workbook.xml")
    if workbook is None:
        return []

    workbook_rels = _read_relationships(zf, "xl/workbook.xml")
    images: list[ExcelImage] = []

    for sheet_el in _find_all(workbook, "sheet"):
        sheet_name = sheet_el.get("name")
        rel_id = sheet_el.get(f"{{{RELS_NS}}}id")
        if not sheet_name or not rel_id or rel_id not in workbook_rels:
            continue

        sheet_path = workbook_rels[rel_id][1]
        drawing_rels = [
            target for rel_type, target in _read_relationships(zf, sheet_path).values() if rel_type.endswith("/drawing")
        ]

        for drawing_path in drawing_rels:
            for media_path in _drawing_media_paths(zf, drawing_path):
                media_name = posixpath.basename(media_path)
                ext = media_name.rsplit(".", 1)[-1].lower() if "." in media_name else ""
                if ext not in IMAGE_EXTENSIONS:
                    continue
                try:
                    content = zf.read(media_path)
                except KeyError:
                    logger.warning("excel image extraction: missing media part {}", media_path)
                    continue
                images.append(
                    ExcelImage(
                        sheet_name=sheet_name,
                        media_name=media_name,
                        ext=ext,
                        content=content,
                    )
                )

    return images
