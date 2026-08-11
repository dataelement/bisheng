"""python-docx helpers for building .docx inside the BiSheng code interpreter.

Use from a build script:

    import sys
    sys.path.insert(0, "skills/bisheng-docx/scripts")
    from docx_helpers import set_run_font, apply_chinese_defaults, add_table

Every function here exists because plain python-docx gets the Chinese case
wrong or cannot express the construct at all:

* ``run.font.name`` writes only ``w:ascii``/``w:hAnsi`` — Chinese glyphs keep
  falling back to the theme font. The CJK face lives in ``w:eastAsia`` and has
  to be set through the XML.
* Table column widths must be written to **every cell**; setting them on the
  column object alone is silently ignored by Word.
* A table of contents, page numbers, and a horizontal rule are all field codes
  or borders with no python-docx API at all.
"""

from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

# Fonts a Chinese user's Word certainly has. Rendering happens on their machine,
# so an exotic face here becomes a substitution there.
CN_FONT = "微软雅黑"
CN_FONT_SERIF = "宋体"
CN_FONT_HEADING = "微软雅黑"
LATIN_FONT = "Times New Roman"

HEADER_FILL = "1F4E79"
BAND_FILL = "F2F6FA"


def set_run_font(run, name: str | None = None, size_pt: float | None = None, bold=None, color: str | None = None):
    """Set a run's font so it applies to Chinese too.

    ``run.font.name`` only writes ``w:ascii`` and ``w:hAnsi``; without a
    matching ``w:eastAsia`` entry Word renders CJK in the theme font and the
    document silently ignores the face you asked for.
    """
    if name:
        run.font.name = name
        rpr = run._element.get_or_add_rPr()
        rfonts = rpr.find(qn("w:rFonts"))
        if rfonts is None:
            rfonts = OxmlElement("w:rFonts")
            rpr.insert(0, rfonts)
        rfonts.set(qn("w:ascii"), name)
        rfonts.set(qn("w:hAnsi"), name)
        rfonts.set(qn("w:eastAsia"), name)
    if size_pt is not None:
        run.font.size = Pt(size_pt)
    if bold is not None:
        run.font.bold = bold
    if color:
        run.font.color.rgb = RGBColor.from_string(color)
    return run


def _style_font(style, cn_name: str, size_pt: float | None = None):
    style.font.name = cn_name
    rpr = style.element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.insert(0, rfonts)
    rfonts.set(qn("w:ascii"), cn_name)
    rfonts.set(qn("w:hAnsi"), cn_name)
    rfonts.set(qn("w:eastAsia"), cn_name)
    if size_pt is not None:
        style.font.size = Pt(size_pt)


def apply_chinese_defaults(doc, body_font: str = CN_FONT, heading_font: str = CN_FONT_HEADING, body_pt: float = 11):
    """Make Normal and Heading 1–4 render correctly in Chinese.

    Word's stock Heading styles are Calibri Light in a blue nobody asked for;
    left alone they make every generated document look identically foreign.
    """
    _style_font(doc.styles["Normal"], body_font, body_pt)
    doc.styles["Normal"].paragraph_format.line_spacing = 1.5
    doc.styles["Normal"].paragraph_format.space_after = Pt(6)

    sizes = {1: 20, 2: 16, 3: 14, 4: 12}
    for level, size in sizes.items():
        try:
            style = doc.styles[f"Heading {level}"]
        except KeyError:
            continue
        _style_font(style, heading_font, size)
        style.font.bold = True
        # Word's stock Heading 4 (and several template variants) are italic.
        # Left alone, a level-4 Chinese heading renders as slanted serif and
        # looks like a different document.
        style.font.italic = False
        style.font.color.rgb = RGBColor.from_string("1F1F1F")
        style.paragraph_format.space_before = Pt(12 if level > 1 else 18)
        style.paragraph_format.space_after = Pt(6)


def setup_page(doc, width_cm: float = 21.0, height_cm: float = 29.7, margin_cm: float = 2.54, landscape: bool = False):
    """A4 portrait by default; pass landscape=True to swap the dimensions."""
    for section in doc.sections:
        section.page_width = Cm(height_cm if landscape else width_cm)
        section.page_height = Cm(width_cm if landscape else height_cm)
        section.left_margin = section.right_margin = Cm(margin_cm)
        section.top_margin = section.bottom_margin = Cm(margin_cm)
    return doc.sections[0]


def content_width_cm(section) -> float:
    """Usable width between the margins, in cm — the cap for tables and images."""
    return (section.page_width - section.left_margin - section.right_margin) / 360000


def _field(paragraph, instruction: str, placeholder: str = ""):
    """Insert a Word field code. Fields are how TOC and page numbers work."""
    run = paragraph.add_run()
    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    run._element.append(begin)

    run = paragraph.add_run()
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = instruction
    run._element.append(instr)

    run = paragraph.add_run()
    sep = OxmlElement("w:fldChar")
    sep.set(qn("w:fldCharType"), "separate")
    run._element.append(sep)

    if placeholder:
        paragraph.add_run(placeholder)

    run = paragraph.add_run()
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    run._element.append(end)
    return paragraph


def enable_update_fields(doc):
    """Ask Word to refresh every field when the document is opened.

    Without this the TOC shows the placeholder text until someone presses F9,
    which reads as a broken document.
    """
    settings = doc.settings.element
    existing = settings.find(qn("w:updateFields"))
    if existing is None:
        existing = OxmlElement("w:updateFields")
        settings.append(existing)
    existing.set(qn("w:val"), "true")


def add_toc(doc, levels: str = "1-3", title: str = "目录"):
    """Insert a table of contents field. Requires built-in Heading styles."""
    if title:
        heading = doc.add_paragraph()
        run = heading.add_run(title)
        set_run_font(run, CN_FONT_HEADING, 18, bold=True)
        heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
    paragraph = doc.add_paragraph()
    _field(paragraph, f' TOC \\o "{levels}" \\h \\z \\u ', "（打开文档时自动生成；若未显示请按 Ctrl+A 后 F9）")
    enable_update_fields(doc)
    return paragraph


def add_page_number_footer(section, template: str = "第 {PAGE} 页 / 共 {NUMPAGES} 页", size_pt: float = 9):
    """Page numbers in the footer, as live fields rather than baked-in text."""
    footer = section.footer
    paragraph = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for chunk in _split_template(template):
        if chunk in ("PAGE", "NUMPAGES"):
            _field(paragraph, f" {chunk} ", "1")
        else:
            paragraph.add_run(chunk)
    for run in paragraph.runs:
        set_run_font(run, CN_FONT, size_pt, color="808080")
    return paragraph


def _split_template(template: str):
    parts, buffer, index = [], "", 0
    while index < len(template):
        if template[index] == "{":
            close = template.find("}", index)
            if close > 0:
                if buffer:
                    parts.append(buffer)
                    buffer = ""
                parts.append(template[index + 1 : close])
                index = close + 1
                continue
        buffer += template[index]
        index += 1
    if buffer:
        parts.append(buffer)
    return parts


def set_cell_shading(cell, hex_fill: str):
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_fill)
    tc_pr.append(shd)


def add_table(doc, headers, rows, widths_cm=None, style: str = "Table Grid", font_pt: float = 10, banded=True):
    """Add a table with widths Word will actually honour.

    python-docx exposes ``column.width``, but Word ignores it unless the same
    width is written to every cell in that column and autofit is off — the
    single most common "why is my table squashed" bug.
    """
    table = doc.add_table(rows=1, cols=len(headers))
    if style:
        try:
            table.style = style
        except KeyError:
            pass  # style missing from the template; grid lines are cosmetic
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = widths_cm is None

    header_cells = table.rows[0].cells
    for index, title in enumerate(headers):
        cell = header_cells[index]
        cell.text = ""
        run = cell.paragraphs[0].add_run(str(title))
        set_run_font(run, CN_FONT, font_pt, bold=True, color="FFFFFF")
        cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER
        set_cell_shading(cell, HEADER_FILL)

    for row_index, record in enumerate(rows):
        cells = table.add_row().cells
        for index, value in enumerate(record):
            cell = cells[index]
            cell.text = ""
            run = cell.paragraphs[0].add_run("" if value is None else str(value))
            set_run_font(run, CN_FONT, font_pt)
            if isinstance(value, (int, float)):
                cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.RIGHT
            if banded and row_index % 2 == 1:
                set_cell_shading(cell, BAND_FILL)

    if widths_cm:
        for row in table.rows:
            for index, width in enumerate(widths_cm):
                if index < len(row.cells):
                    row.cells[index].width = Cm(width)
    repeat_header_row(table)
    return table


def repeat_header_row(table):
    """Repeat row 0 on every page the table spills onto.

    Word only does this when the row carries ``w:tblHeader``; without it a long
    table's second page is a wall of numbers with no column names.
    """
    if not table.rows:
        return table
    tr_pr = table.rows[0]._tr.get_or_add_trPr()
    if tr_pr.find(qn("w:tblHeader")) is None:
        tr_pr.append(OxmlElement("w:tblHeader"))
    return table


def add_hr(doc, color: str = "BFBFBF", size: int = 6):
    """A horizontal rule as a paragraph bottom border.

    Never use a one-row table for this — it breaks text flow and screen readers.
    """
    paragraph = doc.add_paragraph()
    p_pr = paragraph._p.get_or_add_pPr()
    borders = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), str(size))
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), color)
    borders.append(bottom)
    p_pr.append(borders)
    return paragraph


def add_image_fitted(doc, image_path: str, section=None, max_width_cm: float | None = None, caption: str | None = None):
    """Insert an image capped at the text width, optionally captioned.

    Only ever shrinks: forcing every picture to the full text width blows a
    600px chart up to 16cm and it renders visibly soft.
    """
    if max_width_cm is None:
        max_width_cm = content_width_cm(section or doc.sections[0])
    paragraph = doc.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    picture = paragraph.add_run().add_picture(image_path)
    limit = Cm(max_width_cm)
    if picture.width > limit:
        picture.height = int(picture.height * limit / picture.width)
        picture.width = limit
    if caption:
        cap = doc.add_paragraph()
        cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
        set_run_font(cap.add_run(caption), CN_FONT, 9, color="808080")
    return paragraph


def first_line_indent(paragraph, chars: float = 2, font_pt: float = 11):
    """Chinese body text is indented by two characters, not by a tab."""
    paragraph.paragraph_format.first_line_indent = Pt(chars * font_pt)
    return paragraph


def add_body(doc, text: str, indent: bool = True, font_pt: float = 11):
    """A body paragraph with the Chinese conventions already applied."""
    paragraph = doc.add_paragraph()
    set_run_font(paragraph.add_run(text), CN_FONT, font_pt)
    if indent:
        first_line_indent(paragraph, 2, font_pt)
    return paragraph


def add_heading_cn(doc, text: str, level: int = 1):
    """A heading that keeps the built-in style (so the TOC finds it) but renders
    in a Chinese face."""
    heading = doc.add_heading(level=level)
    run = set_run_font(
        heading.add_run(text), CN_FONT_HEADING, {1: 20, 2: 16, 3: 14, 4: 12}.get(level, 12), bold=True, color="1F1F1F"
    )
    run.font.italic = False  # stock Heading 4 is italic; override at run level too
    return heading
