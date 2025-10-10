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
        # 设置heading 1~4
        for i in range(1, 5):
            s = SimpleStyle("Heading%d" % i, "Heading %d" % i,
                            self.style_conf["h%d" % i])
            self.set_style(s)
        # TODO 还有什么样式设置呢？
        #  图片描述Caption、表格样式(?)

        # s = SimpleStyle("Normal", "Normal", self.style_conf["normal"])
        s = SimpleStyle(MDX_STYLE.PLAIN_TEXT, "Normal", self.style_conf["normal"])
        self.set_style(s)

    # 通用的样式设置
    def set_style(self, _style: SimpleStyle):
        new_style: _ParagraphStyle
        if _style.style_name not in self.styles:
            new_style: _ParagraphStyle = self.styles.add_style(_style.style_name, _style.style_type)
            new_style.base_style = self.styles[_style.base_style_name]
        else:
            new_style = self.styles[_style.style_name]

        new_style.quick_style = True

        # ##### 字体相关 #####
        # 设置字体、颜色、大小
        new_style.font.name = _style.font_default  # 只设置name是设置西文字体
        new_style.font.size = Pt(_style.font_size)
        new_style._element.rPr.rFonts.set(qn('w:eastAsia'), _style.font_east_asia)  # 要额外设置中文字体
        new_style.font.color.rgb = RGBColor.from_string(_style.font_color)
        # 加粗、斜体、下划线、删除线
        new_style.font.bold = _style.font_bold
        new_style.font.italic = _style.font_italic
        new_style.font.underline = _style.font_underline
        new_style.font.strike = _style.font_strike

        # ##### 段落相关 #####
        # 设置缩进、段前/段后空格、段内行距
        new_style.paragraph_format.first_line_indent = (Pt(_style.font_size) * int(_style.first_line_indent))
        new_style.paragraph_format.space_before = Pt(_style.space_before)
        new_style.paragraph_format.space_after = Pt(_style.space_after)
        new_style.paragraph_format.line_spacing = _style.line_spacing

        # ##### 其他 #####
        # 去除段落前面左上角的黑点
        new_style.paragraph_format.keep_together = False
        # 标题样式保持 keep_with_next 为 True，避免标题单独分页
        if not _style.style_name.startswith("Heading"):
            new_style.paragraph_format.keep_with_next = False
        # 标题不在前面分页
        if _style.style_name.startswith("Heading"):
            new_style.paragraph_format.page_break_before = False
        # 显示在快捷样式窗口上
        new_style.quick_style = True
        return

