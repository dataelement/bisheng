import os
import tempfile
from pathlib import Path
from typing import IO, Dict, List, Any, Tuple
from urllib.parse import unquote, urlparse

import requests
from bisheng.utils.minio_client import MinioClient
from bisheng.utils.util import _is_valid_url
from docx import Document
from docx.shared import Inches
from loguru import logger
import pandas as pd


def find_lcs(str1, str2):
    lstr1 = len(str1)
    lstr2 = len(str2)
    record = [[0 for i in range(lstr2 + 1)] for j in range(lstr1 + 1)]  # 多一位
    maxNum = 0
    p = 0
    for i in range(lstr1):
        for j in range(lstr2):
            if str1[i] == str2[j]:
                record[i + 1][j + 1] = record[i][j] + 1
                if record[i + 1][j + 1] > maxNum:
                    maxNum = record[i + 1][j + 1]
                    p = i + 1

    return str1[p - maxNum : p], maxNum


class DocxTemplateRender(object):
    def __init__(self, filepath: str = None, file_content: IO[bytes] = None):
        self.filepath = filepath
        self.file_content = file_content
        if self.filepath:
            self.doc = Document(self.filepath)
        else:
            self.doc = Document(self.file_content)

    def _insert_image(self, paragraph, image_path: str, alt_text: str = "图片"):
        """
        在段落中插入图片

        Args:
            paragraph: Word段落对象
            image_path: 图片文件路径
            alt_text: 图片替代文本
        """
        try:
            if os.path.exists(image_path):
                # 插入图片，设置最大宽度为6英寸
                run = paragraph.runs[0] if paragraph.runs else paragraph.add_run()
                run.add_picture(image_path, width=Inches(6))
                logger.info(f"成功插入图片: {image_path}")
            else:
                # 图片文件不存在，插入错误文本
                if paragraph.runs:
                    paragraph.runs[0].text = f"[图片加载失败: {image_path}]"
                else:
                    paragraph.add_run(f"[图片加载失败: {image_path}]")
                logger.error(f"图片文件不存在: {image_path}")
        except Exception as e:
            # 插入图片失败，显示错误信息
            if paragraph.runs:
                paragraph.runs[0].text = f"[图片插入失败: {str(e)}]"
            else:
                paragraph.add_run(f"[图片插入失败: {str(e)}]")
            logger.error(f"插入图片失败: {image_path}, 错误: {str(e)}")

    def _process_resource_placeholders(self, doc, placeholder_map):
        """
        统一处理文档中的所有资源占位符

        Args:
            doc: Word文档对象
            placeholder_map: 占位符映射字典
        """
        # 处理所有段落中的占位符
        for p in doc.paragraphs:
            paragraph_text = p.text
            if not paragraph_text:
                continue

            # 检查段落中是否包含任何占位符
            found_placeholders = []
            for placeholder, resource_info in placeholder_map.items():
                if placeholder in paragraph_text:
                    found_placeholders.append((placeholder, resource_info))

            # 按长度倒序排列，先处理长的占位符，避免短的占位符被误匹配
            found_placeholders.sort(key=lambda x: len(x[0]), reverse=True)

            # 处理找到的占位符
            for placeholder, resource_info in found_placeholders:
                if resource_info["type"] == "image":
                    # 清空段落文本中的占位符
                    for run in p.runs:
                        if placeholder in run.text:
                            run.text = run.text.replace(placeholder, "")
                    # 插入图片
                    self._insert_image(p, resource_info["path"], resource_info["alt_text"])
                    logger.info(f"处理图片占位符: {placeholder} -> {resource_info['path']}")

                elif resource_info["type"] == "excel":
                    # 插入Excel表格
                    if resource_info["resource_type"] in ["downloaded", "local"]:
                        table_data = self._excel_to_table(resource_info["path"])
                    else:
                        table_data = [["Excel文件加载失败", resource_info["path"]]]

                    # 清空段落文本中的占位符
                    for run in p.runs:
                        if placeholder in run.text:
                            run.text = run.text.replace(placeholder, "")

                    self._insert_table(p, table_data)
                    logger.info(f"处理Excel占位符: {placeholder} -> {resource_info['path']}")

                elif resource_info["type"] == "csv":
                    # 插入CSV表格
                    if resource_info["resource_type"] in ["downloaded", "local"]:
                        table_data = self._csv_to_table(resource_info["path"])
                    else:
                        table_data = [["CSV文件加载失败", resource_info["path"]]]

                    # 清空段落文本中的占位符
                    for run in p.runs:
                        if placeholder in run.text:
                            run.text = run.text.replace(placeholder, "")

                    self._insert_table(p, table_data)
                    logger.info(f"处理CSV占位符: {placeholder} -> {resource_info['path']}")

                elif resource_info["type"] == "markdown_table":
                    # 插入Markdown表格
                    table_data, alignments = self._markdown_table_to_data(resource_info["content"])

                    # 清空段落文本中的占位符
                    for run in p.runs:
                        if placeholder in run.text:
                            run.text = run.text.replace(placeholder, "")

                    self._insert_markdown_table(p, table_data, alignments)
                    logger.info(f"处理Markdown表格占位符: {placeholder}")

        # 处理表格单元格中的占位符
        for table in doc.tables:
            for i, row in enumerate(table.rows):
                for j, cell in enumerate(row.cells):
                    for one in cell.paragraphs:
                        cell_text = one.text
                        if not cell_text:
                            continue

                        # 检查单元格中的占位符
                        for placeholder, resource_info in placeholder_map.items():
                            if placeholder in cell_text:
                                if resource_info["type"] == "image":
                                    # 在表格单元格中插入图片（简化处理）
                                    cell_text = cell_text.replace(placeholder, f"[图片: {resource_info['alt_text']}]")
                                elif resource_info["type"] == "excel":
                                    cell_text = cell_text.replace(placeholder, "[Excel表格]")
                                elif resource_info["type"] == "csv":
                                    cell_text = cell_text.replace(placeholder, "[CSV表格]")
                                elif resource_info["type"] == "markdown_table":
                                    cell_text = cell_text.replace(placeholder, "[Markdown表格]")
                                logger.info(f"处理表格单元格占位符: {placeholder}")

                        # 更新单元格文本
                        if cell_text != one.text:
                            if one.runs:
                                one.runs[0].text = cell_text
                                for r_index in range(1, len(one.runs)):
                                    one.runs[r_index].text = ""
                            else:
                                one.add_run(cell_text)

    def _csv_to_table(self, csv_path: str) -> List[List[str]]:
        """
        将CSV文件转换为表格数据

        Args:
            csv_path: CSV文件路径

        Returns:
            List[List[str]]: 表格数据
        """
        try:
            # 读取CSV文件，自动检测编码和分隔符
            import csv
            import chardet

            # 检测文件编码
            with open(csv_path, "rb") as f:
                raw_data = f.read()
                encoding_result = chardet.detect(raw_data)
                encoding = encoding_result["encoding"] if encoding_result["encoding"] else "utf-8"

            table_data = []

            # 尝试不同的分隔符
            delimiters = [",", ";", "\t", "|"]

            for delimiter in delimiters:
                try:
                    with open(csv_path, "r", encoding=encoding, newline="") as f:
                        # 先读取一小部分来检测分隔符
                        sample = f.read(1024)
                        f.seek(0)

                        sniffer = csv.Sniffer()
                        try:
                            detected_delimiter = sniffer.sniff(sample).delimiter
                        except:
                            detected_delimiter = delimiter

                        reader = csv.reader(f, delimiter=detected_delimiter)
                        table_data = [row for row in reader]

                        # 如果成功读取了数据且有多列，则认为分隔符正确
                        if table_data and len(table_data[0]) > 1:
                            break

                except Exception as e:
                    logger.debug(f"尝试分隔符 '{delimiter}' 失败: {str(e)}")
                    continue

            if not table_data:
                # 如果所有分隔符都失败了，尝试简单的逐行读取
                with open(csv_path, "r", encoding=encoding) as f:
                    lines = f.readlines()
                    table_data = [[line.strip()] for line in lines if line.strip()]

            # 清理数据
            cleaned_data = []
            for row in table_data:
                cleaned_row = [str(cell).strip() if cell is not None else "" for cell in row]
                if any(cleaned_row):  # 只添加非空行
                    cleaned_data.append(cleaned_row)

            logger.info(f"成功解析CSV文件: {csv_path}, 行数: {len(cleaned_data)}")
            return cleaned_data

        except Exception as e:
            logger.error(f"解析CSV文件失败: {csv_path}, 错误: {str(e)}")
            return [["CSV文件解析失败", str(e)]]

    def _excel_to_table(self, excel_path: str) -> List[List[str]]:
        """
        将Excel文件转换为表格数据，保持数据格式和类型

        Args:
            excel_path: Excel文件路径

        Returns:
            List[List[str]]: 表格数据
        """

        try:
            # 读取Excel文件，保持更多原始格式
            df = pd.read_excel(excel_path, sheet_name=0, dtype=str, keep_default_na=False)

            # 限制表格大小，避免过大的表格影响Word文档
            max_rows = 500  # 最大行数
            max_cols = 20  # 最大列数

            if len(df) > max_rows:
                logger.warning(f"Excel文件行数过多({len(df)})，截取前{max_rows}行")
                df = df.head(max_rows)

            if len(df.columns) > max_cols:
                logger.warning(f"Excel文件列数过多({len(df.columns)})，截取前{max_cols}列")
                df = df.iloc[:, :max_cols]

            # 转换为列表格式
            table_data = []

            # 处理表头，清理列名
            headers = []
            for col in df.columns:
                col_str = str(col).strip()
                # 处理Excel自动生成的列名（如Unnamed: 0）
                if col_str.startswith("Unnamed:"):
                    col_str = ""  # 空列名
                headers.append(col_str)
            table_data.append(headers)

            # 添加数据行，智能格式化
            for _, row in df.iterrows():
                row_data = []
                for cell in row:
                    cell_str = str(cell).strip()

                    # 处理空值
                    if cell_str.lower() in ["nan", "none", "null", ""]:
                        cell_str = ""

                    # 处理长数字，保持可读性
                    elif cell_str.replace(".", "").replace("-", "").isdigit():
                        try:
                            # 尝试格式化数字
                            if "." in cell_str:
                                # 浮点数，保留合理的小数位
                                num = float(cell_str)
                                if abs(num) >= 1000:
                                    cell_str = f"{num:,.2f}"  # 千分位分隔符
                                else:
                                    cell_str = f"{num:.2f}".rstrip("0").rstrip(".")
                            else:
                                # 整数，添加千分位分隔符
                                num = int(cell_str)
                                if abs(num) >= 1000:
                                    cell_str = f"{num:,}"
                        except ValueError:
                            pass  # 保持原始字符串

                    # 限制单元格内容长度，避免过长内容影响布局
                    if len(cell_str) > 100:
                        cell_str = cell_str[:97] + "..."

                    row_data.append(cell_str)

                table_data.append(row_data)

            # 确保所有行的列数一致
            if table_data:
                max_cols = max(len(row) for row in table_data)
                for row in table_data:
                    while len(row) < max_cols:
                        row.append("")

            logger.info(f"成功解析Excel文件: {excel_path}, 大小: {len(table_data)}行 x {max_cols}列")
            return table_data

        except Exception as e:
            logger.error(f"解析Excel文件失败: {excel_path}, 错误: {str(e)}")
            return [["Excel文件解析失败", str(e)]]

    def _markdown_table_to_data(self, markdown_table: str) -> Tuple[List[List[str]], List[str]]:
        """
        将Markdown表格转换为表格数据，并解析对齐信息

        Args:
            markdown_table: Markdown表格文本

        Returns:
            tuple: (表格数据, 对齐信息列表)
        """
        try:
            lines = [line.strip() for line in markdown_table.strip().split("\n") if line.strip()]

            if len(lines) < 2:
                logger.warning("Markdown表格格式不完整，至少需要表头和分隔符行")
                return [["格式错误", "表格不完整"]], ["left"]

            table_data = []
            alignments = []
            separator_found = False

            for i, line in enumerate(lines):
                # 检查是否是分隔符行
                if self._is_separator_line(line):
                    alignments = self._parse_alignments(line)
                    separator_found = True
                    continue

                # 解析数据行
                cells = self._parse_table_row(line)
                if cells:
                    # 清理单元格内容
                    cleaned_cells = []
                    for cell in cells:
                        cleaned_cell = self._clean_cell_content(cell)
                        cleaned_cells.append(cleaned_cell)

                    table_data.append(cleaned_cells)

            # 验证表格结构
            if not separator_found:
                logger.warning("Markdown表格缺少分隔符行，使用默认左对齐")
                alignments = ["left"] * (len(table_data[0]) if table_data else 1)

            # 确保所有行的列数一致
            if table_data:
                max_cols = max(len(row) for row in table_data)
                for row in table_data:
                    while len(row) < max_cols:
                        row.append("")

                # 确保对齐信息数量匹配列数
                while len(alignments) < max_cols:
                    alignments.append("left")
                alignments = alignments[:max_cols]

            logger.info(f"成功解析Markdown表格，大小: {len(table_data)}行 x {len(alignments)}列")
            logger.info(f"列对齐方式: {alignments}")
            return table_data, alignments

        except Exception as e:
            logger.error(f"解析Markdown表格失败: {str(e)}")
            return [["Markdown表格解析失败", str(e)]], ["left"]

    def _is_separator_line(self, line: str) -> bool:
        """
        判断是否是Markdown表格的分隔符行

        Args:
            line: 表格行内容

        Returns:
            bool: 是否为分隔符行
        """
        # 移除首尾的|符号
        content = line.strip().strip("|").strip()
        if not content:
            return False

        # 分隔符行应该主要包含-和:字符
        cells = [cell.strip() for cell in content.split("|")]

        for cell in cells:
            if not cell:
                continue
            # 每个单元格应该主要由-和:组成
            clean_cell = cell.replace("-", "").replace(":", "").strip()
            if clean_cell:  # 如果还有其他字符，则不是分隔符行
                return False

        return True

    def _parse_alignments(self, separator_line: str) -> List[str]:
        """
        从分隔符行解析列对齐方式

        Args:
            separator_line: 分隔符行

        Returns:
            List[str]: 对齐方式列表 ("left", "center", "right")
        """
        alignments = []
        content = separator_line.strip().strip("|").strip()
        cells = [cell.strip() for cell in content.split("|")]

        for cell in cells:
            if not cell:
                alignments.append("left")
                continue

            # 判断对齐方式
            if cell.startswith(":") and cell.endswith(":"):
                alignments.append("center")  # :---:
            elif cell.endswith(":"):
                alignments.append("right")  # ---:
            else:
                alignments.append("left")  # --- 或 :---

        return alignments

    def _parse_table_row(self, line: str) -> List[str]:
        """
        解析表格行，处理转义和特殊字符

        Args:
            line: 表格行内容

        Returns:
            List[str]: 单元格内容列表
        """
        # 移除首尾的|符号
        content = line.strip()
        if content.startswith("|"):
            content = content[1:]
        if content.endswith("|"):
            content = content[:-1]

        # 分割单元格，但要处理转义的|
        cells = []
        current_cell = ""
        escaped = False

        for char in content:
            if escaped:
                current_cell += char
                escaped = False
            elif char == "\\":
                escaped = True
                current_cell += char
            elif char == "|":
                cells.append(current_cell.strip())
                current_cell = ""
            else:
                current_cell += char

        # 添加最后一个单元格
        if current_cell or cells:  # 处理空行
            cells.append(current_cell.strip())

        return cells

    def _clean_cell_content(self, cell: str) -> str:
        """
        清理单元格内容，处理Markdown格式

        Args:
            cell: 原始单元格内容

        Returns:
            str: 清理后的内容
        """
        if not cell:
            return ""

        # 移除多余空格
        cleaned = cell.strip()

        # 处理Markdown格式标记（简化处理）
        # 移除粗体标记
        cleaned = cleaned.replace("**", "")
        # 移除斜体标记
        cleaned = cleaned.replace("*", "")
        # 移除代码标记
        cleaned = cleaned.replace("`", "")

        # 处理链接格式 [text](url) -> text
        import re

        cleaned = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", cleaned)

        # 限制长度
        if len(cleaned) > 100:
            cleaned = cleaned[:97] + "..."

        return cleaned

    def _insert_markdown_table(self, paragraph, table_data: List[List[str]], alignments: List[str]):
        """
        专门插入Markdown表格，支持对齐信息

        Args:
            paragraph: Word段落对象
            table_data: 表格数据
            alignments: 对齐信息列表
        """
        try:
            if not table_data:
                paragraph.add_run("[Markdown表格数据为空]")
                return

            rows = len(table_data)
            cols = len(alignments)

            # 创建表格
            table = self.doc.add_table(rows=rows, cols=cols)

            # 设置Markdown表格专用样式
            try:
                # 使用更适合Markdown的样式
                table.style = "Light List - Accent 1"  # 清爽的列表样式
            except:
                try:
                    table.style = "Table Grid"  # 备选样式
                except:
                    pass

            # 填充表格数据并设置对齐
            for i, row_data in enumerate(table_data):
                for j, cell_data in enumerate(row_data):
                    if j < cols:
                        cell = table.cell(i, j)
                        cell.text = str(cell_data)

                        # 根据Markdown对齐信息设置单元格对齐
                        cell_paragraphs = cell.paragraphs
                        if cell_paragraphs and j < len(alignments):
                            alignment = alignments[j]
                            if alignment == "center":
                                cell_paragraphs[0].alignment = 1  # 居中
                            elif alignment == "right":
                                cell_paragraphs[0].alignment = 2  # 右对齐
                            else:  # left
                                cell_paragraphs[0].alignment = 0  # 左对齐

            # Markdown表格样式：第一行通常是表头
            if rows > 0:
                for j, cell in enumerate(table.rows[0].cells):
                    # 表头样式
                    for paragraph in cell.paragraphs:
                        for run in paragraph.runs:
                            run.bold = True

                    # 设置表头背景色（浅灰色，更适合Markdown风格）
                    try:
                        from docx.oxml.shared import qn
                        from docx.oxml import parse_xml

                        shading_elm = parse_xml(
                            r'<w:shd {} w:fill="F2F2F2"/>'.format(
                                'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
                            )
                        )
                        cell._tc.get_or_add_tcPr().append(shading_elm)
                    except:
                        pass

            # 设置表格布局
            try:
                table.autofit = True
                from docx.shared import Inches

                table.width = Inches(6.5)
            except:
                pass

            # 设置更紧凑的行高（Markdown风格）
            try:
                for row in table.rows:
                    row.height = Inches(0.25)  # 比Excel表格更紧凑
                    for cell in row.cells:
                        # 更小的边距
                        cell.margin_left = Inches(0.03)
                        cell.margin_right = Inches(0.03)
                        cell.margin_top = Inches(0.01)
                        cell.margin_bottom = Inches(0.01)
            except:
                pass

            logger.info(f"成功插入Markdown表格，大小: {rows}x{cols}，对齐: {alignments}")

        except Exception as e:
            paragraph.add_run(f"[Markdown表格插入失败: {str(e)}]")
            logger.error(f"插入Markdown表格失败: {str(e)}")

    def _insert_table(self, paragraph, table_data: List[List[str]]):
        """
        在段落后插入高质量的表格

        Args:
            paragraph: Word段落对象
            table_data: 表格数据
        """
        try:
            if not table_data:
                paragraph.add_run("[表格数据为空]")
                return

            # 在段落后添加表格
            rows = len(table_data)
            cols = max(len(row) for row in table_data) if table_data else 1

            # 创建表格
            table = self.doc.add_table(rows=rows, cols=cols)

            # 设置更专业的表格样式
            try:
                # 尝试使用更好的内置样式
                table.style = "Light Shading - Accent 1"  # 浅色阴影样式
            except:
                try:
                    table.style = "Table Grid"  # 备选样式
                except:
                    pass  # 如果样式不存在，使用默认样式

            # 填充表格数据
            for i, row_data in enumerate(table_data):
                for j, cell_data in enumerate(row_data):
                    if j < cols:  # 确保不超出列数
                        cell = table.cell(i, j)
                        cell.text = str(cell_data)

                        # 设置单元格对齐方式
                        cell_paragraphs = cell.paragraphs
                        if cell_paragraphs:
                            # 数字右对齐，文本左对齐
                            cell_text = str(cell_data).strip()
                            if self._is_number(cell_text):
                                cell_paragraphs[0].alignment = 2  # 右对齐
                            else:
                                cell_paragraphs[0].alignment = 0  # 左对齐

            # 设置表头样式（第一行）
            if rows > 0:
                for cell in table.rows[0].cells:
                    # 表头居中对齐
                    for paragraph in cell.paragraphs:
                        paragraph.alignment = 1  # 居中对齐
                        for run in paragraph.runs:
                            run.bold = True

                    # 尝试设置表头背景色（如果支持）
                    try:
                        from docx.oxml.shared import qn
                        from docx.oxml import parse_xml

                        shading_elm = parse_xml(
                            r'<w:shd {} w:fill="D9E2F3"/>'.format(
                                'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
                            )
                        )
                        cell._tc.get_or_add_tcPr().append(shading_elm)
                    except:
                        pass  # 如果设置背景色失败，继续执行

            # 自动调整列宽
            try:
                table.autofit = True
                # 设置表格宽度为页面宽度
                from docx.shared import Inches

                table.width = Inches(6.5)  # 约A4页面宽度
            except:
                pass

            # 设置行高和单元格边距
            try:
                for row in table.rows:
                    row.height = Inches(0.3)  # 设置行高
                    for cell in row.cells:
                        # 设置单元格边距
                        cell.margin_left = Inches(0.05)
                        cell.margin_right = Inches(0.05)
                        cell.margin_top = Inches(0.02)
                        cell.margin_bottom = Inches(0.02)
            except:
                pass

            logger.info(f"成功插入高质量表格，大小: {rows}x{cols}")

        except Exception as e:
            paragraph.add_run(f"[表格插入失败: {str(e)}]")
            logger.error(f"插入表格失败: {str(e)}")

    def _is_number(self, text: str) -> bool:
        """
        判断文本是否为数字

        Args:
            text: 要判断的文本

        Returns:
            bool: 是否为数字
        """
        if not text:
            return False

        # 移除千分位分隔符和空格
        clean_text = text.replace(",", "").replace(" ", "").replace("%", "")

        try:
            float(clean_text)
            return True
        except ValueError:
            return False

    def render(self, template_def, resources: Dict[str, List[Dict[str, Any]]] = None):
        """
        渲染模板，支持图片和表格插入

        Args:
            template_def: 模板定义列表
            resources: 资源信息字典，包含图片、Excel文件和Markdown表格
        """
        doc = self.doc

        # 如果没有传入resources，使用空字典
        if resources is None:
            resources = {"images": [], "excel_files": [], "csv_files": [], "markdown_tables": []}

        # 创建占位符到资源的映射
        placeholder_map = {}

        # 图片占位符映射
        for img_info in resources.get("images", []):
            placeholder_map[img_info["placeholder"]] = {
                "type": "image",
                "path": img_info["local_path"],
                "alt_text": img_info["alt_text"],
                "resource_type": img_info["type"],
            }

        # Excel文件占位符映射
        for excel_info in resources.get("excel_files", []):
            placeholder_map[excel_info["placeholder"]] = {
                "type": "excel",
                "path": excel_info["local_path"],
                "resource_type": excel_info["type"],
            }

        # CSV文件占位符映射
        for csv_info in resources.get("csv_files", []):
            placeholder_map[csv_info["placeholder"]] = {
                "type": "csv",
                "path": csv_info["local_path"],
                "resource_type": csv_info["type"],
            }

        # Markdown表格占位符映射
        for table_info in resources.get("markdown_tables", []):
            placeholder_map[table_info["placeholder"]] = {"type": "markdown_table", "content": table_info["content"]}

        # 原有的文本替换逻辑
        for replace_info in template_def:
            k1 = replace_info[0]
            v1 = replace_info[1]

            # 处理表格中的占位符
            for table in doc.tables:
                for i, row in enumerate(table.rows):
                    for j, cell in enumerate(row.cells):
                        if k1 in cell.text:
                            for one in cell.paragraphs:
                                if k1 in one.text:
                                    # 检查是否包含需要特殊处理的占位符
                                    cell_text = one.text.replace(k1, v1)

                                    # 处理占位符
                                    for placeholder, resource_info in placeholder_map.items():
                                        if placeholder in cell_text:
                                            if resource_info["type"] == "image":
                                                # 在表格单元格中插入图片（简化处理）
                                                cell_text = cell_text.replace(
                                                    placeholder, f"[图片: {resource_info['alt_text']}]"
                                                )
                                            elif resource_info["type"] == "excel":
                                                cell_text = cell_text.replace(placeholder, "[Excel表格]")
                                            elif resource_info["type"] == "csv":
                                                cell_text = cell_text.replace(placeholder, "[CSV表格]")
                                            elif resource_info["type"] == "markdown_table":
                                                cell_text = cell_text.replace(placeholder, "[Markdown表格]")

                                    one.runs[0].text = cell_text
                                    for r_index, r in enumerate(one.runs):
                                        if r_index == 0:
                                            continue
                                        r.text = ""

            # 处理段落中的占位符
            for p in doc.paragraphs:
                if k1 not in p.text:
                    continue

                runs_cnt = len(p.runs)
                s_e = []
                i = 0
                while i < runs_cnt:
                    new_i = i + 1
                    for j in range(i + 1, runs_cnt + 1):
                        part_text = "".join([r.text for r in p.runs[i:j]])
                        if k1 in part_text:
                            # 找到最小的范围内包含k1的runs
                            tmp_i, tmp_j = i, j
                            while tmp_i <= tmp_j:
                                tmp_part_text = "".join([r.text for r in p.runs[tmp_i:tmp_j]])
                                if k1 in tmp_part_text:
                                    tmp_i += 1
                                    continue
                                else:
                                    tmp_i -= 1
                                    break
                            s_e.append((tmp_i, j))
                            new_i = j
                            break
                    i = new_i

                for one in s_e:
                    s, e = one
                    assert e > 0, [r.text for r in p.runs]

                    if e - s == 1:
                        replace_mapping = [(k1, v1)]
                    elif e - s == 2:
                        s_tgt_text = p.runs[s].text
                        comm_str, max_num = find_lcs(k1, s_tgt_text)
                        assert k1.startswith(comm_str)
                        p1 = comm_str
                        p2 = k1[max_num:]
                        n = len(v1)
                        sub_n1 = int(1.0 * len(p1) / (len(p1) + len(p2)) * n)
                        replace_mapping = [(p1, v1[:sub_n1]), (p2, v1[sub_n1:])]
                    elif e - s == 3:
                        m_text = p.runs[s + 1].text
                        head_tail = k1.split(m_text, 1)
                        assert len(head_tail) == 2
                        h_text = head_tail[0]
                        t_text = head_tail[1]
                        replace_mapping = [(h_text, ""), (m_text, v1), (t_text, "")]
                    else:
                        m_texts = [p.runs[i].text for i in range(s + 1, e - 1)]
                        m_text = "".join(m_texts)
                        head_tail = k1.split(m_text, 1)
                        assert len(head_tail) == 2
                        h_text = head_tail[0]
                        t_text = head_tail[1]
                        replace_mapping = [(h_text, "")]
                        replace_mapping.append((m_texts[0], v1))
                        for text in m_texts[1:]:
                            replace_mapping.append((text, ""))
                        replace_mapping.append((t_text, ""))

                    for i in range(s, e):
                        _k, _v = replace_mapping[i - s]
                        p.runs[i].text = p.runs[i].text.replace(_k, _v)

        # 所有变量替换完成后，统一处理资源占位符
        self._process_resource_placeholders(doc, placeholder_map)

        return doc


def test_replace_string(template_file, kv_dict: dict, file_name: str):
    # If the file is a web path, download it to a temporary file, and use that
    if not os.path.isfile(template_file) and _is_valid_url(template_file):
        r = requests.get(template_file)

        if r.status_code != 200:
            raise ValueError("Check the url of your file; returned status code %s" % r.status_code)

        temp_dir = tempfile.TemporaryDirectory()
        temp_file = Path(temp_dir.name) / unquote(urlparse(template_file).path.split("/")[-1])
        with open(temp_file, mode="wb") as f:
            f.write(r.content)

        template_file = temp_file
    elif not os.path.isfile(template_file):
        raise ValueError("File path %s is not a valid file or url" % template_file)

    template_dict = []
    for k, v in kv_dict.items():
        template_dict.append(["{{" + k + "}}", v])

    doc = DocxTemplateRender(str(template_file))
    output = doc.render(template_dict)

    temp_dir = tempfile.TemporaryDirectory()
    temp_file = Path(temp_dir.name) / file_name
    output.save(temp_file)
    MinioClient().upload_minio(file_name, temp_file)

    return file_name
