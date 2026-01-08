import docx
from docx import Document
from docx.oxml.ns import qn
from docx.shared import Inches, RGBColor, Pt
from docx.styles.style import _ParagraphStyle, BaseStyle
from docx.enum.style import WD_STYLE_TYPE
from docx.styles.styles import Styles

from bisheng.common.utils.markdown_cmpnt.md_to_docx.provider.simple_style import SimpleStyle
from bisheng.common.utils.markdown_cmpnt.md_to_docx.utils.style_enum import MDX_STYLE


class StyleManager:

    def __init__(self, doc: Document, yaml_conf: dict):
        self.styles: Styles = doc.styles
        self.style_conf = yaml_conf

    def init_styles(self):
        # Pengaturanheading 1~4
        for i in range(1, 5):
            s = SimpleStyle("Heading%d" % i, "Heading %d" % i,
                            self.style_conf["h%d" % i])
            self.set_style(s)
        # TODO What other styling settings are there?
        #  CaptionsCaptionTable Style(?)

        # s = SimpleStyle("Normal", "Normal", self.style_conf["normal"])
        s = SimpleStyle(MDX_STYLE.PLAIN_TEXT, "Normal", self.style_conf["normal"])
        self.set_style(s)

    # General style settings
    def set_style(self, _style: SimpleStyle):
        new_style: _ParagraphStyle
        if _style.style_name not in self.styles:
            new_style: _ParagraphStyle = self.styles.add_style(_style.style_name, _style.style_type)
            new_style.base_style = self.styles[_style.base_style_name]
        else:
            new_style = self.styles[_style.style_name]

        new_style.quick_style = True

        # ##### Font Related #####
        # Set font, color, size
        new_style.font.name = _style.font_default  # Set onlynameIs Set Western Font
        new_style.font.size = Pt(_style.font_size)
        new_style._element.rPr.rFonts.set(qn('w:eastAsia'), _style.font_east_asia)  # To set additional Chinese fonts
        new_style.font.color.rgb = RGBColor.from_string(_style.font_color)
        # Bold, Italic, Underline, Strikeout
        new_style.font.bold = _style.font_bold
        new_style.font.italic = _style.font_italic
        new_style.font.underline = _style.font_underline
        new_style.font.strike = _style.font_strike

        # ##### Paragraph Related #####
        # Set indent, before paragraph/Space after paragraph, line spacing between paragraphs
        new_style.paragraph_format.first_line_indent = (Pt(_style.font_size) * int(_style.first_line_indent))
        new_style.paragraph_format.space_before = Pt(_style.space_before)
        new_style.paragraph_format.space_after = Pt(_style.space_after)
        new_style.paragraph_format.line_spacing = _style.line_spacing

        # ##### Other _________ #####
        # Remove the black dot in the top left corner before the paragraph
        new_style.paragraph_format.keep_together = False
        # Header Style Retention keep_with_next are True, avoid separate pagination of titles
        if not _style.style_name.startswith("Heading"):
            new_style.paragraph_format.keep_with_next = False
        # Title does not precede pagination
        if _style.style_name.startswith("Heading"):
            new_style.paragraph_format.page_break_before = False
        # Show on shortcut style window
        new_style.quick_style = True
        return

