"""F028 — Generate the pypandoc reference docx template for conversation export.

Pypandoc's ``--reference-doc=<path>`` option lets us define the look-and-feel
of the generated Word/PDF by supplying a docx whose **styles** (not content)
are reused by pandoc. This script produces such a docx and writes it into the
backend assets directory.

Re-run after editing this script to refresh the template:

    cd src/backend
    uv run python ../../scripts/gen_conversation_export_template.py

The generated file is checked into the repository at
``src/backend/bisheng/workstation/assets/conversation_export_template.docx``.
UX may hand-edit that docx directly in Word/LibreOffice and commit the
result; pandoc will pick up the manual styling. The script remains the
canonical "first-version" producer in case the binary file is ever lost.
"""

from __future__ import annotations

import sys
from pathlib import Path

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor


# --- Constants -------------------------------------------------------------

DEFAULT_OUTPUT = (
    Path(__file__).resolve().parent.parent
    / "src"
    / "backend"
    / "bisheng"
    / "workstation"
    / "assets"
    / "conversation_export_template.docx"
)

# Font stack rationale:
# - LibreOffice (which renders the PDF inside the bisheng-backend Docker
#   image) does NOT replicate Word's automatic "fall back to a CJK face when
#   the declared font has no glyph" behaviour. If the docx declares Microsoft
#   YaHei / Calibri / Consolas — fonts that ship with Windows but not with
#   the Linux image — CJK glyphs render as tofu boxes, line spacing breaks
#   and tables collapse. So we declare fonts that the image actually has.
# - ``WenQuanYi Zen Hei`` is provided by the ``fonts-wqy-zenhei`` Debian
#   package baked into the bisheng-backend image; it has full CJK coverage.
# - ``Liberation Sans`` / ``Liberation Mono`` ship with LibreOffice itself,
#   so they are guaranteed available wherever PDF rendering runs and look
#   nearly identical to Calibri / Consolas.
# - Real Word users opening the docx will not have these exact faces but
#   Word's own font substitution handles that gracefully.
ZH_FONT = "WenQuanYi Zen Hei"
EN_FONT = "Liberation Sans"
MONO_FONT = "Liberation Mono"


# --- Helpers ---------------------------------------------------------------


def _set_cjk_font(run_or_style_element, font_name: str) -> None:
    """Set the East-Asian font for a paragraph/run/style via rFonts/w:eastAsia.

    python-docx does not expose East-Asian font through ``Font.name``; that
    setter only writes the ascii/hAnsi axes. We have to drop down to the
    underlying ``<w:rFonts>`` XML element and set ``w:eastAsia`` ourselves so
    Chinese characters render in Microsoft YaHei (Win) / fonts-wqy-zenhei
    (Linux fallback) instead of a generic CJK fallback.
    """
    r_pr = run_or_style_element.get_or_add_rPr()
    r_fonts = r_pr.find(qn("w:rFonts"))
    if r_fonts is None:
        r_fonts = r_pr.makeelement(qn("w:rFonts"), {})
        r_pr.append(r_fonts)
    r_fonts.set(qn("w:eastAsia"), font_name)
    r_fonts.set(qn("w:ascii"), EN_FONT)
    r_fonts.set(qn("w:hAnsi"), EN_FONT)


def _configure_style(
    style,
    *,
    size_pt: int,
    bold: bool = False,
    color: RGBColor | None = None,
    mono: bool = False,
) -> None:
    font = style.font
    font.name = MONO_FONT if mono else EN_FONT
    font.size = Pt(size_pt)
    font.bold = bold
    if color is not None:
        font.color.rgb = color
    _set_cjk_font(style.element, ZH_FONT if not mono else MONO_FONT)


def _set_page_size_a4(section) -> None:
    """A4 portrait, 2.5cm margins all around."""
    section.page_height = Cm(29.7)
    section.page_width = Cm(21.0)
    section.top_margin = Cm(2.5)
    section.bottom_margin = Cm(2.5)
    section.left_margin = Cm(2.5)
    section.right_margin = Cm(2.5)


def _create_or_get_style(doc, name: str, style_type):
    styles = doc.styles
    if name in [s.name for s in styles]:
        return styles[name]
    return styles.add_style(name, style_type)


# --- Template builder ------------------------------------------------------


def build_template(output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    doc = Document()

    # Page setup
    for section in doc.sections:
        _set_page_size_a4(section)

    # --- Built-in styles tuned ---------------------------------------------

    # Normal: 11pt, line spacing handled per-paragraph by pandoc; we keep
    # the style spacing modest.
    normal = doc.styles["Normal"]
    _configure_style(normal, size_pt=11)

    # Heading 1 / 2 / 3 — sizes per spec AC-11
    for name, size in (("Heading 1", 16), ("Heading 2", 14), ("Heading 3", 12)):
        style = doc.styles[name]
        _configure_style(style, size_pt=size, bold=True)

    # --- Custom: BoldLabel -------------------------------------------------
    # The label paragraph that pandoc emits when the markdown looks like
    # ``**Admin:**`` becomes a Normal paragraph with bold runs. We do not
    # need a dedicated paragraph style for that; the bold run within Normal
    # is enough. We still define a *character* style "BoldLabel" so future
    # custom renderers can opt-in via a span.
    try:
        label = _create_or_get_style(doc, "BoldLabel", WD_STYLE_TYPE.CHARACTER)
        _configure_style(label, size_pt=14, bold=True)
    except Exception:  # pragma: no cover - style add failure is non-critical
        # Style addition can collide with python-docx defaults across versions;
        # tolerate and continue — the rendering still works without this style.
        pass

    # --- Source Code (pandoc emits this for fenced code blocks) ------------
    try:
        code_style = _create_or_get_style(doc, "Source Code", WD_STYLE_TYPE.PARAGRAPH)
        _configure_style(code_style, size_pt=10, mono=True, color=RGBColor(0x33, 0x33, 0x33))
        # Light gray background for code blocks. python-docx exposes shading
        # via paragraph_format.element; do it via XML so the style sticks.
        p_pr = code_style.element.get_or_add_pPr()
        shd = p_pr.makeelement(
            qn("w:shd"),
            {qn("w:val"): "clear", qn("w:color"): "auto", qn("w:fill"): "F5F5F5"},
        )
        # Strip any existing shading then append ours.
        for existing in p_pr.findall(qn("w:shd")):
            p_pr.remove(existing)
        p_pr.append(shd)
    except Exception:
        pass

    # --- Verbatim Char (inline code) ---------------------------------------
    try:
        verbatim = _create_or_get_style(doc, "Verbatim Char", WD_STYLE_TYPE.CHARACTER)
        _configure_style(verbatim, size_pt=10, mono=True)
    except Exception:
        pass

    # --- Save --------------------------------------------------------------
    doc.save(output_path)
    print(f"Template written: {output_path}")


def main() -> int:
    output = DEFAULT_OUTPUT
    if len(sys.argv) > 1:
        output = Path(sys.argv[1]).expanduser().resolve()
    build_template(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
