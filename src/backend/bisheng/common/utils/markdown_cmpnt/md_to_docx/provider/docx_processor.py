# noinspection PyProtectedMember
#
import io
import re
from socket import socket
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from bs4 import BeautifulSoup
from docx import Document
from docx.enum.text import *
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls
from docx.shared import Inches, RGBColor, Pt
from docx.table import Table
from docx.text.paragraph import Paragraph
from docx.text.run import Run

from bisheng.common.utils.markdown_cmpnt.md_to_docx.provider.docx_plus import add_hyperlink
from bisheng.common.utils.markdown_cmpnt.md_to_docx.provider.style_manager import StyleManager
from bisheng.common.utils.markdown_cmpnt.md_to_docx.utils.style_enum import MDX_STYLE


class DocxProcessor:
    def __init__(self, style_conf: dict, debug_state: bool = False, show_image_desc: bool = True):
        """
        初始化DocxProcessor
        :param style_conf: 样式配置字典
        :param debug_state: 是否开启调试模式
        :param show_image_desc: 是否显示图片的描述，即 `![desc](src/img)` 中 desc的内容
        """
        self.document = Document()
        self.debug_state = debug_state
        self.show_image_desc = show_image_desc
        if style_conf is not None:
            StyleManager(self.document, style_conf).init_styles()

    def debug(self, *args):
        """调试输出"""
        if self.debug_state:
            print(*args)

    # h1, h2, ...
    def add_heading(self, content: str, tag: str):
        level: int = int(tag.__getitem__(1))
        p = self.document.add_paragraph(content, style="Heading%d" % level)
        # 强制设置标题不分页
        p.paragraph_format.page_break_before = False
        p.paragraph_format.keep_with_next = True
        return p

    def add_run(self, p: Paragraph, content: str, char_style: str = "plain"):
        # fixme 行内的样式超过一个的句子会被忽略，如：
        # <u>**又加粗又*斜体*又下划线**</u>
        self.debug("[%s]:" % char_style, content)
        run = p.add_run(content)

        # 标准化标签名 - 将 HTML5 标签映射到标准样式
        style_map = {
            'b': 'strong',      # <b> -> 粗体
            'i': 'em',          # <i> -> 斜体
            'del': 'strike',    # <del> -> 删除线
            'mark': 'highlight' # <mark> -> 高亮
        }
        char_style = style_map.get(char_style, char_style)

        # 不应当使用形如 run.bold = (char_style=="strong") 的方式
        # 因为没有显式加粗，不意味着整体段落不加粗。
        if char_style == "strong":
            run.bold = True
        if char_style == "em":
            run.italic = True
        if char_style == "u":
            run.underline = True
        if char_style == "strike":
            run.font.strike = True
        if char_style == "sub":
            run.font.subscript = True
        if char_style == "sup":
            run.font.superscript = True
        run.font.highlight_color = WD_COLOR_INDEX.YELLOW if char_style == "highlight" else None

        # if char_style == "code":
        #     run.font.name = "Consolas"

    def add_code_block(self, pre_tag):
        # TODO 代码块样式
        # TODO 设置代码块（表格）中的中文字体，似乎只能通过指定 已设置好中文字体的样式 来达到目的
        code_table = self.document.add_table(0, 1, style=MDX_STYLE.TABLE)
        row_cells = code_table.add_row().cells

        # 安全检查：确保代码块有内容
        if pre_tag.contents and len(pre_tag.contents) > 0 and pre_tag.contents[0].string:
            code_text = pre_tag.contents[0].string.rstrip('\n')
            run = row_cells[0].paragraphs[0].add_run(code_text)
            run.font.name = "Consolas"
        else:
            # 如果代码块为空，添加空白占位
            run = row_cells[0].paragraphs[0].add_run("")
            run.font.name = "Consolas"

    def add_picture(self, img_tag, parent_paragraph: Paragraph = None):
        """
        添加图片到文档
        :param img_tag: 图片标签
        :param parent_paragraph: 父段落。如果提供,图片将内嵌在该段落中;否则创建新的独立段落
        """
        # 如果没有提供父段落,创建新的独立段落(居中显示)
        if parent_paragraph is None:
            p: Paragraph = self.document.add_paragraph()
            p.alignment = WD_PARAGRAPH_ALIGNMENT.CENTER
            p.paragraph_format.first_line_indent = 0
        else:
            # 使用提供的父段落(内嵌模式)
            p = parent_paragraph

        run: Run = p.add_run()

        img_src: str
        scale: float = 100  # 优先级最高，单位 %
        width_px: int = 100
        height_px: int = 100

        # 设置宽度
        if img_tag.get("style"):
            style_content: str = img_tag["style"]
            img_attr: list = style_content.strip().split(";")
            # print(img_attr)
            attr: str
            for attr in img_attr:
                if attr.find("width") != -1:
                    # TODO 处理 style 中的宽度和高度属性
                    width_px = int(re.findall(r"\d+", attr)[0])
                if attr.find("height") != -1:
                    height_px = int(re.findall(r"\d+", attr)[0])
                if attr.find("zoom") != -1:
                    scale = int(re.findall(r"\d+", attr)[0])

        if img_tag["src"] != "":
            img_src = img_tag["src"]
            # 网络图片
            if img_src.startswith("http://") or img_src.startswith("https://"):
                print("[IMAGE] fetching:", img_src)
                try:
                    image_bytes = urlopen(img_src, timeout=10).read()
                    data_stream = io.BytesIO(image_bytes)
                    run.add_picture(data_stream, width=Inches(5.7 * scale / 100))
                except HTTPError as e:
                    print(f"[HTTP ERROR] {e.code}: {img_src}")
                except socket.timeout:
                    print(f"[TIMEOUT] Image load timeout: {img_src}")
                except URLError as e:
                    print(f"[URL ERROR] Failed to fetch image: {e.reason} - {img_src}")
                except Exception as e:
                    print(f"[RESOURCE ERROR] {type(e).__name__}: {e} - {img_src}")
            else:
                # 本地图片
                try:
                    run.add_picture(img_src, width=Inches(5.7 * scale / 100))
                except FileNotFoundError:
                    print(f"[FILE ERROR] Image not found: {img_src}")
                except Exception as e:
                    print(f"[RESOURCE ERROR] Failed to load image: {type(e).__name__}: {e} - {img_src}")
        else:
            # 网络图片
            img_src = img_tag["title"]
            print("[IMAGE] fetching:", img_src)
            try:
                image_bytes = urlopen(img_src, timeout=10).read()
                data_stream = io.BytesIO(image_bytes)
                run.add_picture(data_stream, width=Inches(5.7 * scale / 100))
            except HTTPError as e:
                print(f"[HTTP ERROR] {e.code}: {img_src}")
            except socket.timeout:
                print(f"[TIMEOUT] Image load timeout: {img_src}")
            except URLError as e:
                print(f"[URL ERROR] Failed to fetch image: {e.reason} - {img_src}")
            except Exception as e:
                print(f"[RESOURCE ERROR] {type(e).__name__}: {e} - {img_src}")

        # 如果选择展示图片描述，那么描述会在图片下方显示
        # 注意：只有在独立段落模式下才添加描述(避免打断段落流)
        if parent_paragraph is None and self.show_image_desc and img_tag.get("alt"):
            # TODO 图片描述的显示样式
            desc: Paragraph = self.document.add_paragraph(img_tag["alt"], style=MDX_STYLE.CAPTION)
            desc.alignment = WD_PARAGRAPH_ALIGNMENT.CENTER
            desc.style.font.color.rgb = RGBColor(11, 11, 11)
            desc.style.font.bold = False
            desc.paragraph_format.first_line_indent = 0

    def add_table(self, table_root):
        # 统计列数 - 优先从 thead 获取，否则从 tbody 第一行获取
        col_count: int = 0
        has_thead = False

        if table_root.thead and table_root.thead.tr:
            has_thead = True
            for col in table_root.thead.tr.contents:
                if col.name in ['th', 'td']:
                    col_count += 1
        elif table_root.tbody:
            # 从 tbody 第一行统计列数
            first_row = table_root.tbody.find('tr')
            if first_row:
                for col in first_row.contents:
                    if col.name in ['th', 'td']:
                        col_count += 1

        if col_count == 0:
            # 容错：如果没有找到列数，默认为1
            col_count = 1

        table = self.document.add_table(0, col_count, style=MDX_STYLE.TABLE)  # TODO 表格样式

        # 表格头行（如果存在）
        if has_thead:
            head_row_cells = table.add_row().cells
            i = 0
            for col in table_root.thead.tr.contents:
                if col.name in ['th', 'td']:
                    cell_text = col.get_text(strip=True)
                    head_row_cells[i].paragraphs[0].add_run(cell_text).bold = True
                    i += 1

        # 数据行
        if table_root.tbody:
            for tr in table_root.tbody:
                if tr.name != 'tr':
                    continue
                row_cells = table.add_row().cells
                i = 0
                for td in tr.contents:
                    if td.name in ['th', 'td']:
                        cell_text = td.get_text(strip=True)
                        row_cells[i].text = cell_text
                        i += 1

    def add_number_list(self, number_list):
        # print(number_list.contents, "\n")
        for item in number_list.children:
            if item.name != 'li':  # 跳过非 li 标签
                continue

            # 获取直接文本内容(不包括子标签)
            direct_text = ''.join([str(s) for s in item.find_all(text=True, recursive=False)]).strip()

            # 检查是否有段落标签
            has_paragraph_tag = item.find('p') is not None

            # 如果有直接文本,添加段落
            if direct_text:
                self.add_paragraph(item, p_style=MDX_STYLE.LIST_NUMBER) \
                    .style.paragraph_format.space_after = Pt(1)  # TODO 数字列表样式
            # 如果没有直接文本但有 <p> 标签,处理 <p> 标签
            elif has_paragraph_tag:
                para_count = 0
                for child in item.children:
                    if hasattr(child, 'name') and child.name == 'p':
                        if para_count == 0:
                            # 第一个 <p> 使用列表样式
                            self.add_paragraph(child, p_style=MDX_STYLE.LIST_NUMBER) \
                                .style.paragraph_format.space_after = Pt(1)
                        else:
                            # 后续 <p> 使用续行样式
                            self.add_paragraph(child, p_style=MDX_STYLE.LIST_CONTINUE) \
                                .style.paragraph_format.space_after = Pt(1)
                        para_count += 1

            # 处理嵌套的有序列表
            if hasattr(item, "ol") and item.ol is not None:
                sub_num: int = 1  # 子序号
                for item2 in item.ol.children:
                    if item2.name != 'li':
                        continue
                    self.add_paragraph(item2, prefix="(%d). " % sub_num, p_style=MDX_STYLE.LIST_CONTINUE) \
                        .style.paragraph_format.first_line_indent = 0  # TODO 数字列表样式
                    sub_num += 1

            # 处理嵌套的无序列表
            if hasattr(item, "ul") and item.ul is not None:
                for item2 in item.ul.children:
                    if item2.name != 'li':
                        continue
                    self.add_paragraph(item2, prefix="•  ", p_style=MDX_STYLE.LIST_CONTINUE) \
                        .style.paragraph_format.space_after = Pt(1)

    def add_bullet_list(self, bullet_list):
        # 有可能是 list
        text = str(bullet_list.contents[1].string).strip()
        if text.startswith("[ ]") or text.startswith("[x]"):
            self.add_todo_list(bullet_list)
            return
        for item in bullet_list.children:
            if item.name != 'li':  # 跳过非 li 标签
                continue

            # 获取直接文本内容(不包括子标签)
            direct_text = ''.join([str(s) for s in item.find_all(text=True, recursive=False)]).strip()

            # 检查是否有段落标签
            has_paragraph_tag = item.find('p') is not None

            # 如果有直接文本,添加段落
            if direct_text:
                self.add_paragraph(item, p_style=MDX_STYLE.LIST_BULLET) \
                    .style.paragraph_format.space_after = Pt(1)
            # 如果没有直接文本但有 <p> 标签,处理 <p> 标签
            elif has_paragraph_tag:
                para_count = 0
                for child in item.children:
                    if hasattr(child, 'name') and child.name == 'p':
                        if para_count == 0:
                            # 第一个 <p> 使用列表样式
                            self.add_paragraph(child, p_style=MDX_STYLE.LIST_BULLET) \
                                .style.paragraph_format.space_after = Pt(1)
                        else:
                            # 后续 <p> 使用续行样式
                            self.add_paragraph(child, p_style=MDX_STYLE.LIST_CONTINUE) \
                                .style.paragraph_format.space_after = Pt(1)
                        para_count += 1

            # 处理 ul 子列表
            if hasattr(item, "ul") and item.ul is not None:
                for item2 in item.ul.children:
                    if item2.string == "\n" or (not item2.string):
                        continue
                    self.add_paragraph(item2, prefix="•  ", p_style=MDX_STYLE.LIST_CONTINUE) \
                        .style.paragraph_format.space_after = Pt(1)

            # 处理 ol 子列表
            if hasattr(item, "ol") and item.ol is not None:
                sub_num = 1
                for item2 in item.ol.children:
                    if item2.name != 'li':
                        continue
                    self.add_paragraph(item2, prefix=f"{sub_num}. ", p_style=MDX_STYLE.LIST_CONTINUE) \
                        .style.paragraph_format.space_after = Pt(1)
                    sub_num += 1

    # 伪TODO list
    def add_todo_list(self, todo_list):
        # list_para.style.font.name = "Consolas"
        for item in todo_list.children:
            if item.string == "\n" or (not item.string):
                continue
            text: str = item.string
            list_para = self.document.add_paragraph(style=MDX_STYLE.PLAIN_LIST)
            if text.startswith("[x]"):
                list_para.add_run("[ √ ]").font.name = "Consolas"
                list_para.add_run(text.replace("[x]", " ", 1))
            elif text.startswith("[ ]"):
                list_para.add_run("[   ]").font.name = "Consolas"
                list_para.add_run(text.replace("[ ]", " ", 1))

    # 分割线
    def add_split_line(self):
        p = self.document.add_paragraph()
        p.paragraph_format.space_before = Pt(6)
        p.paragraph_format.space_after = Pt(6)
        border_elm = parse_xml(
            r'<w:pBdr {}><w:bottom w:val="single" w:sz="6" w:space="1" w:color="auto"/></w:pBdr>'.format(nsdecls('w')))
        p._p.get_or_add_pPr().append(border_elm)

    # 超链接
    def add_link(self, p: Paragraph, text: str, href: str):
        self.debug("[link]:", text, "[href]:", href)
        add_hyperlink(p, href, text)
        # run = p.add_run(text)

    def add_paragraph(self, children, p_style: str = None, prefix: str = ""):
        """
        children: list|str
        一个段落内的元素（包括图片）。根据有无样式来划分，组成一个列表。
        有样式文字如加粗、斜体、图片、等。
        如`I am plain _while_ he is **bold**`将转为：
        ["I am plain", "while", "he is", "bold"]
        """
        p = self.document.add_paragraph(prefix, style=p_style)
        if type(children) == str:
            p.add_run(children)
            return p
        for elem in children.contents:  # 遍历一个段落内的所有元素
            if elem.name == "a":
                self.add_link(p, elem.string, elem["href"])
            elif elem.name == "img":
                self.add_picture(elem, parent_paragraph=p)  # 传递当前段落
            elif elem.name is not None:  # 有字符样式的子串
                self.add_run(p, elem.string, elem.name)
            elif not elem.string == "\n":  # 无字符样式的子串
                self.add_run(p, elem)
        return p

    # from docx.enum.style import WD_STYLE
    def add_blockquote(self, children):
        # TODO 将引用块放在1x1的表格中，优化引用块的显示效果
        #  设置左侧缩进，上下行距
        table: Table = self.document.add_table(0, 1)
        row_cells = table.add_row().cells

        # 支持多个段落
        para_count = 0
        for child in children.contents:
            # 跳过换行符
            if isinstance(child, str) and child.strip() == "":
                continue

            # 处理段落标签
            if hasattr(child, 'name') and child.name == 'p':
                if para_count > 0:
                    # 添加新段落
                    row_cells[0].add_paragraph()
                p = row_cells[0].paragraphs[para_count]

                for elem in child.contents:  # 遍历一个段落内的所有元素
                    if elem.name == "a":
                        self.add_link(p, elem.string, elem["href"])
                    elif elem.name == "img":
                        self.add_picture(elem, parent_paragraph=p)  # 传递当前段落
                    elif elem.name is not None:  # 有字符样式的子串
                        self.add_run(p, elem.string, elem.name)
                    elif elem.string and elem.string != "\n":  # 无字符样式的子串
                        self.add_run(p, elem.string)
                para_count += 1
            # 处理直接文本节点
            elif isinstance(child, str) and child.strip():
                if para_count == 0:
                    p = row_cells[0].paragraphs[0]
                    para_count = 1
                else:
                    p = row_cells[0].add_paragraph()
                    para_count += 1
                p.add_run(child.strip())

        shading_elm_1 = parse_xml(r'<w:shd {} w:fill="efefef"/>'.format(nsdecls('w')))
        table.rows[0].cells[0]._tc.get_or_add_tcPr().append(shading_elm_1)

    def html2docx(self, html_str: str):
        # 打开HTML

        soup = BeautifulSoup(html_str, 'html.parser')

        # 安全地查找 body 标签
        body_tag = soup.find('body')
        if body_tag is None:
            # 如果没有 body,使用整个 soup
            body_tag = soup

        # 标题
        title_text = ""
        # 逐个解析标签，并写到word中
        for root in body_tag.children:
            # 跳过纯文本节点和换行
            if isinstance(root, str):
                if root.strip():
                    # 处理直接文本节点
                    self.document.add_paragraph(root.strip(), style=MDX_STYLE.PLAIN_TEXT)
                continue

            # debug("<%s>" % root.name)
            if root.name == "p":  # 普通段落
                self.add_paragraph(root, p_style=MDX_STYLE.PLAIN_TEXT)
            elif root.name == "blockquote":  # 引用块
                self.add_blockquote(root)
            elif root.name == "ol":  # 数字列表
                self.add_number_list(root)
            elif root.name == "ul":  # 无序列表 或 List
                self.add_bullet_list(root)
            elif root.name == "table":  # 表格
                self.add_table(root)
            elif root.name == "hr":
                self.add_split_line()
            elif root.name == "pre":
                self.add_code_block(root)
            elif root.name in ["h1", "h2", "h3", "h4", "h5", "h6"]:
                if title_text == "":
                    title_text = root.string or ""
                self.add_heading(root.string or "", root.name)

        docx_bytes = io.BytesIO()

        self.document.save(docx_bytes)

        docx_bytes.seek(0)

        return docx_bytes.getbuffer(), title_text
