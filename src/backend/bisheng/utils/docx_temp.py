import os
import tempfile
from pathlib import Path
from typing import IO, Dict, List, Any, Tuple
from urllib.parse import unquote, urlparse

import pandas as pd
import requests
from docx import Document
from docx.shared import Inches
from loguru import logger

from bisheng.utils.minio_client import MinioClient
from bisheng.utils.util import _is_valid_url


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

    return str1[p - maxNum: p], maxNum


class DocxTemplateRender(object):
    def __init__(self, filepath: str = None, file_content: IO[bytes] = None):
        self.filepath = filepath
        self.file_content = file_content
        if self.filepath:
            self.doc = Document(self.filepath)
        else:
            self.doc = Document(self.file_content)

        # 添加调试：检查模板文档初始内容
        logger.info("[模板调试] Word模板文档初始化完成")
        self._log_template_initial_content()

    def _log_template_initial_content(self):
        """记录模板的初始内容，用于调试"""
        try:
            logger.info(f"[模板调试] 模板总段落数: {len(self.doc.paragraphs)}")

            # 查找包含特定标签的段落
            for i, paragraph in enumerate(self.doc.paragraphs):
                paragraph_text = paragraph.text.strip()
                if paragraph_text:
                    # 检查是否包含file content标签
                    if 'file content' in paragraph_text.lower():
                        logger.info(f"[模板调试] 段落{i}: {paragraph_text[:200]}...")
                    # 检查是否包含变量占位符
                    elif '{{' in paragraph_text and '}}' in paragraph_text:
                        logger.info(f"[模板调试] 变量段落{i}: {paragraph_text[:200]}...")
                    # 只记录前5个非空段落的简要内容
                    elif i < 5:
                        logger.info(f"[模板调试] 段落{i}: {paragraph_text[:100]}...")
        except Exception as e:
            logger.error(f"[模板调试] 记录模板内容失败: {str(e)}")

    def _insert_image(self, paragraph, image_path: str, alt_text: str = "图片"):
        """
        在段落中插入图片

        Args:
            paragraph: Word段落对象
            image_path: 图片文件路径
            alt_text: 图片替代文本
        """
        logger.debug(f"[简单插图] 开始插入图片: {image_path}")
        try:
            if os.path.exists(image_path):
                # 检查文件大小
                file_size = os.path.getsize(image_path)
                logger.debug(f"[简单插图] 图片文件存在: {image_path}, 大小: {file_size}字节")

                # 插入图片，设置最大宽度为6英寸
                run = paragraph.runs[0] if paragraph.runs else paragraph.add_run()
                logger.debug(f"[简单插图] 准备在run中插入图片，run数量: {len(paragraph.runs)}")

                run.add_picture(image_path, width=Inches(6))
                logger.info(f"[简单插图] ✅ 成功插入图片: {image_path}, 大小: {file_size}字节")
            else:
                # 图片文件不存在，使用原路径
                logger.error(f"[简单插图] ❌ 图片文件不存在: {image_path}")
                if paragraph.runs:
                    paragraph.runs[0].text = image_path
                else:
                    paragraph.add_run(image_path)
        except Exception as e:
            # 插入图片失败，显示原URL
            logger.error(f"[简单插图] ❌ 插入图片失败: {image_path}, 错误类型: {type(e).__name__}, 错误: {str(e)}")
            if paragraph.runs:
                paragraph.runs[0].text = image_path
            else:
                paragraph.add_run(image_path)

    def _replace_placeholder_with_image(self, paragraph, placeholder, image_path, alt_text):
        """
        精确替换段落中的占位符为图片，正确处理跨run的占位符

        Args:
            paragraph: Word段落对象
            placeholder: 要替换的占位符
            image_path: 图片文件路径
            alt_text: 图片替代文字
        """
        logger.debug(f"[图片替换] 开始替换占位符: {placeholder} -> {image_path}")

        # 获取段落的完整文本
        paragraph_text = paragraph.text

        # 查找占位符的位置
        placeholder_start = paragraph_text.find(placeholder)
        if placeholder_start == -1:
            logger.warning(f"[图片替换] 占位符未找到: {placeholder}")
            return  # 占位符不存在

        placeholder_end = placeholder_start + len(placeholder)

        # 定位占位符在runs中的位置
        current_pos = 0
        start_run_index = -1
        start_run_pos = 0
        end_run_index = -1
        end_run_pos = 0

        for i, run in enumerate(paragraph.runs):
            run_len = len(run.text)

            # 找到占位符开始位置
            if start_run_index == -1 and current_pos + run_len > placeholder_start:
                start_run_index = i
                start_run_pos = placeholder_start - current_pos

            # 找到占位符结束位置
            if current_pos + run_len >= placeholder_end:
                end_run_index = i
                end_run_pos = placeholder_end - current_pos
                break

            current_pos += run_len

        # 清除占位符文本
        if start_run_index == end_run_index:
            # 占位符在同一个run内
            run = paragraph.runs[start_run_index]
            run.text = run.text[:start_run_pos] + run.text[end_run_pos:]
        else:
            # 占位符跨越多个runs
            # 清除开始run中的部分
            start_run = paragraph.runs[start_run_index]
            start_run.text = start_run.text[:start_run_pos]

            # 清除结束run中的部分
            end_run = paragraph.runs[end_run_index]
            end_run.text = end_run.text[end_run_pos:]

            # 清除中间的runs
            for i in range(end_run_index - 1, start_run_index, -1):
                paragraph.runs[i].text = ""

        # 在占位符位置插入图片
        # 找到合适的插入位置（在清理后的第一个非空run之后）
        insert_run = None
        for i in range(start_run_index, len(paragraph.runs)):
            if paragraph.runs[i].text or i == start_run_index:
                insert_run = paragraph.runs[i]
                break

        if insert_run is not None:
            # 在该run之后插入图片
            logger.debug(f"[图片替换] 在run位置插入图片: {image_path}")
            self._insert_image_at_run(insert_run, image_path, alt_text)
            logger.info(f"[图片替换] 占位符替换完成: {placeholder} -> {image_path}")
        else:
            # 如果没有找到合适位置，使用原有方法
            logger.warning(f"[图片替换] 未找到合适run位置，使用备用方法: {image_path}")
            self._insert_image(paragraph, image_path, alt_text)

    def _insert_image_at_run(self, run, image_path, alt_text):
        """
        在指定run位置插入图片

        Args:
            run: Word run对象
            image_path: 图片路径
            alt_text: 图片替代文字
        """
        try:
            from docx.shared import Inches

            # 检查文件是否存在
            if not os.path.exists(image_path):
                logger.warning(f"[图片渲染] 图片文件不存在，使用原路径: {image_path}")
                run.text = image_path
                return

            # 检查文件大小和格式
            file_size = os.path.getsize(image_path)
            file_ext = os.path.splitext(image_path)[1].lower()
            logger.debug(f"[图片渲染] 准备插入图片: path={image_path}, size={file_size}字节, ext={file_ext}")

            # 直接在当前run中插入图片
            run.add_picture(image_path, width=Inches(4))  # 默认宽度4英寸
            # 清空run中的文本，避免显示多余的文本
            run.text = ""
            logger.info(f"[图片渲染] 在run位置插入图片成功: {image_path}, size={file_size}字节")
        except Exception as e:
            logger.error(f"[图片渲染] run位置插入图片失败: {image_path}, 错误: {e}")
            logger.debug(f"[图片渲染] 详细错误信息: {type(e).__name__}: {str(e)}")
            try:
                # 使用原有的插入方法作为备用
                logger.info(f"[图片渲染] 尝试备用插入方法: {image_path}")
                # 获取run的父段落对象
                paragraph = run._element.getparent()
                # 转换为python-docx段落对象
                from docx.text.paragraph import Paragraph

                para_obj = Paragraph(paragraph, run.part)
                self._insert_image(para_obj, image_path, alt_text)
                logger.info(f"[图片渲染] 备用方法插入成功: {image_path}")
            except Exception as backup_e:
                logger.error(f"[图片渲染] 备用插入方法也失败: {image_path}, 错误: {backup_e}")
                logger.error(f"[图片渲染] 备用方法详细错误: {type(backup_e).__name__}: {str(backup_e)}")
                # 如果所有方法都失败，就使用原路径
                run.text = image_path
                logger.warning(f"[图片渲染] 所有插入方法失败，使用原路径文本: {image_path}")

    def _replace_placeholder_in_structured_paragraph(self, paragraph, placeholder: str, table_data: List[List[str]]):
        """
        简化的表格替换：直接在占位符位置插入表格，不添加任何结构标记
        """
        # 清除占位符文本
        self._clear_placeholder_from_paragraph(paragraph, placeholder)

        # 直接在段落位置插入表格
        self._insert_table(paragraph, table_data)

        logger.info(f"表格替换完成，共 {len(table_data)} 行数据")

    def _clear_placeholder_from_paragraph(self, paragraph, placeholder):
        """
        从段落中精确清除占位符，处理跨run的情况

        Args:
            paragraph: Word段落对象
            placeholder: 要清除的占位符
        """
        # 获取段落的完整文本
        paragraph_text = paragraph.text

        # 查找占位符的位置
        placeholder_start = paragraph_text.find(placeholder)
        if placeholder_start == -1:
            return  # 占位符不存在

        placeholder_end = placeholder_start + len(placeholder)

        # 定位占位符在runs中的位置
        current_pos = 0
        start_run_index = -1
        start_run_pos = 0
        end_run_index = -1
        end_run_pos = 0

        for i, run in enumerate(paragraph.runs):
            run_len = len(run.text)

            # 找到占位符开始位置
            if start_run_index == -1 and current_pos + run_len > placeholder_start:
                start_run_index = i
                start_run_pos = placeholder_start - current_pos

            # 找到占位符结束位置
            if current_pos + run_len >= placeholder_end:
                end_run_index = i
                end_run_pos = placeholder_end - current_pos
                break

            current_pos += run_len

        # 清除占位符文本
        if start_run_index == end_run_index:
            # 占位符在同一个run内
            run = paragraph.runs[start_run_index]
            run.text = run.text[:start_run_pos] + run.text[end_run_pos:]
        else:
            # 占位符跨越多个runs
            # 清除开始run中的部分
            start_run = paragraph.runs[start_run_index]
            start_run.text = start_run.text[:start_run_pos]

            # 清除结束run中的部分
            end_run = paragraph.runs[end_run_index]
            end_run.text = end_run.text[end_run_pos:]

            # 清除中间的runs
            for i in range(end_run_index - 1, start_run_index, -1):
                paragraph.runs[i].text = ""

    def _process_resource_placeholders(self, doc, placeholder_map):
        """
        按位置顺序处理段落中混合的占位符

        Args:
            doc: Word文档对象  
            placeholder_map: 占位符映射字典
        """
        # 处理所有段落中的占位符
        paragraphs_to_process = list(doc.paragraphs)  # 创建副本，因为我们可能会修改段落结构

        for i, p in enumerate(paragraphs_to_process):
            paragraph_text = p.text
            if not paragraph_text:
                continue

            # 找到该段落中的所有占位符及其位置
            placeholders_with_positions = []
            for placeholder, resource_info in placeholder_map.items():
                pos = paragraph_text.find(placeholder)
                if pos != -1:
                    placeholders_with_positions.append({
                        'placeholder': placeholder,
                        'resource_info': resource_info,
                        'position': pos,
                        'end_position': pos + len(placeholder)
                    })

            if not placeholders_with_positions:
                continue

            # 按位置排序，从前往后处理
            placeholders_with_positions.sort(key=lambda x: x['position'])

            # 分割段落为文本段和占位符段
            self._process_mixed_content_paragraph(doc, p, placeholders_with_positions, paragraph_text)

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
                                    # 在表格单元格中插入实际图片
                                    image_path = resource_info.get("local_path") or resource_info.get("path", "")
                                    if image_path and os.path.exists(image_path):
                                        try:
                                            # 在单元格中插入图片（这会清空单元格并插入图片）
                                            self._insert_image_in_table_cell(cell, image_path)
                                            logger.info(f"✅ 表格单元格中成功插入图片: {image_path}")
                                            # 标记占位符已处理，不需要更新文本
                                            cell_text = ""
                                        except Exception as e:
                                            logger.error(f"❌ 表格单元格插入图片失败: {str(e)}")
                                            # 失败时显示文件名
                                            cell_text = cell_text.replace(placeholder, os.path.basename(image_path))
                                    else:
                                        # 图片文件不存在，显示路径
                                        cell_text = cell_text.replace(placeholder,
                                                                      resource_info.get("path", placeholder))
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

    def _process_mixed_content_paragraph(self, doc, paragraph, placeholders_with_positions, original_text):
        """
        处理包含混合内容的段落 - 内联插入图片和表格
        
        Args:
            doc: Word文档对象
            paragraph: 原始段落
            placeholders_with_positions: 按位置排序的占位符信息列表
            original_text: 原始段落文本
        """
        logger.info(f"[内联混合内容] 开始处理混合内容段落: {original_text[:100]}...")

        # 提取原始段落的样式信息，用于后续段落创建
        original_style_info = self._extract_paragraph_style_info(paragraph)
        logger.debug(f"[样式保持] 提取到原始段落样式: 对齐={original_style_info['alignment']}")

        # 分割文本为片段，保持原始顺序
        segments = []
        last_end = 0

        for item in placeholders_with_positions:
            # 添加占位符前的文本
            if item['position'] > last_end:
                text_before = original_text[last_end:item['position']]
                if text_before:  # 保留所有文本，包括空白
                    segments.append({
                        'type': 'text',
                        'content': text_before
                    })

            # 添加占位符对应的资源
            segments.append({
                'type': 'resource',
                'placeholder': item['placeholder'],
                'resource_info': item['resource_info']
            })

            last_end = item['end_position']

        # 添加最后剩余的文本
        if last_end < len(original_text):
            text_after = original_text[last_end:]
            if text_after:
                segments.append({
                    'type': 'text',
                    'content': text_after
                })

        logger.info(f"[内联混合内容] 分割为 {len(segments)} 个片段")

        # 详细记录每个片段
        for i, seg in enumerate(segments):
            if seg['type'] == 'text':
                logger.info(
                    f"[分割调试] 片段{i + 1} (文本): '{seg['content'][:100]}{'...' if len(seg['content']) > 100 else ''}'")
            else:
                logger.info(f"[分割调试] 片段{i + 1} (资源): {seg['placeholder']} -> {seg['resource_info']['type']}")

        # 清空原始段落
        paragraph.clear()

        # 重新设计：分段处理，保持文档结构一致性
        current_paragraph = paragraph

        i = 0
        while i < len(segments):
            segment = segments[i]

            if segment['type'] == 'text':
                # 直接添加文本内容，不做任何清理
                current_paragraph.add_run(segment['content'])
                logger.info(
                    f"[处理调试] 片段{i + 1} (文本): 已添加到段落 '{segment['content'][:50]}{'...' if len(segment['content']) > 50 else ''}'")

            elif segment['type'] == 'resource':
                resource_info = segment['resource_info']

                if resource_info['type'] == 'image':
                    # 图片可以真正内联在段落中
                    self._insert_inline_image(current_paragraph, resource_info['path'],
                                              resource_info.get('alt_text', ''))
                    logger.info(f"[内联混合内容] 片段{i + 1}: 内联插入图片")

                elif resource_info['type'] in ['excel', 'csv', 'markdown_table']:
                    # 表格内联处理：在当前位置插入表格，然后为后续内容创建新段落
                    if resource_info['type'] == 'markdown_table':
                        table_data, alignments = self._markdown_table_to_data(resource_info["content"])
                    else:
                        table_data = resource_info.get('table_data', [["表格数据解析失败"]])
                        alignments = None

                    logger.info(f"[表格插入调试] 在片段{i + 1}位置插入表格，当前段落: {current_paragraph.text[:50]}")

                    # 在当前段落后立即插入表格
                    table_element = self._create_table_element(table_data)

                    # 获取当前段落在文档中的位置
                    paragraph_element = current_paragraph._element
                    paragraph_parent = paragraph_element.getparent()
                    paragraph_index = list(paragraph_parent).index(paragraph_element)

                    # 在当前段落后插入表格
                    paragraph_parent.insert(paragraph_index + 1, table_element)

                    logger.info(f"[表格插入调试] 表格已插入到段落后，段落索引: {paragraph_index}")

                    # 为后续文本创建新段落，并更新current_paragraph
                    if i + 1 < len(segments):
                        next_paragraph = self._create_new_paragraph_after_table(paragraph_parent, paragraph_index + 1,
                                                                                original_style_info)
                        current_paragraph = next_paragraph
                        logger.info(f"[表格插入调试] 已为后续文本创建新段落（继承样式）")

            i += 1

        logger.info(f"[内联混合内容] ✅ 内联混合内容处理完成")

    def _insert_table_inline(self, current_paragraph, table_data, segments, current_index):
        """
        内联插入表格，保持文本连续性
        
        Args:
            current_paragraph: 当前段落
            table_data: 表格数据
            segments: 所有片段
            current_index: 当前片段索引
            
        Returns:
            int: 跳过的后续文本片段数量
        """
        # 1. 在当前段落后插入表格段落
        table_paragraph = self._create_new_paragraph_after(current_paragraph)
        self._insert_table(table_paragraph, table_data)

        # 2. 检查是否有后续文本片段，如果有则创建新段落
        remaining_segments = segments[current_index + 1:]
        text_segments = [seg for seg in remaining_segments if seg['type'] == 'text']

        logger.info(f"[表格内联调试] 当前片段索引: {current_index}, 总片段数: {len(segments)}")
        logger.info(f"[表格内联调试] 剩余片段数: {len(remaining_segments)}, 其中文本片段: {len(text_segments)}")

        if text_segments:
            # 为后续文本创建新段落
            next_text_paragraph = self._create_new_paragraph_after(table_paragraph)
            logger.info(f"[表格内联调试] 为后续文本创建新段落")

            # 将所有后续文本片段添加到新段落
            for j, seg in enumerate(text_segments):
                next_text_paragraph.add_run(seg['content'])
                logger.info(
                    f"[表格内联调试] 后续文本片段{j + 1}: '{seg['content'][:100]}{'...' if len(seg['content']) > 100 else ''}'")

            # 返回跳过的文本片段数量（让主循环不再处理这些片段）
            skipped_count = len(text_segments)
            logger.info(f"[表格内联调试] 表格已插入，跳过后续{skipped_count}个文本片段")
            return skipped_count
        else:
            logger.info(f"[表格内联调试] 表格已插入，无后续文本片段")
            return 0

    def _create_new_paragraph_after(self, paragraph):
        """
        在指定段落后创建新段落
        
        Args:
            paragraph: 参考段落
            
        Returns:
            新创建的段落对象
        """
        from docx.oxml import parse_xml
        from docx.text.paragraph import Paragraph

        # 创建新的段落元素
        new_p_xml = '<w:p xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"></w:p>'
        new_p_element = parse_xml(new_p_xml)

        # 在当前段落后插入新段落
        paragraph._element.getparent().insert(
            list(paragraph._element.getparent()).index(paragraph._element) + 1,
            new_p_element
        )

        # 返回包装后的段落对象
        return Paragraph(new_p_element, paragraph._parent)

    def _insert_inline_image(self, paragraph, image_path: str, alt_text: str = ""):
        """
        在段落中内联插入图片，图片会在文本流的正确位置
        """
        try:
            # 使用现有的图片插入方法，但确保是内联的
            run = paragraph.add_run()
            run.add_picture(image_path, width=Inches(4.0))
            logger.info(f"[内联图片] ✅ 成功内联插入图片: {image_path}")
        except Exception as e:
            logger.error(f"[内联图片] ❌ 插入图片失败: {str(e)}")
            # 插入原图片路径
            paragraph.add_run(image_path)

    def _insert_image_in_table_cell(self, cell, image_path: str):
        """
        在表格单元格中插入图片
        
        Args:
            cell: 表格单元格对象
            image_path: 图片文件路径
        """
        try:
            from docx.shared import Inches
            import os

            if not os.path.exists(image_path):
                logger.warning(f"[表格单元格图片] 图片文件不存在: {image_path}")
                return

            # 清空单元格内容
            for paragraph in cell.paragraphs:
                paragraph.clear()

            # 在第一个段落中插入图片
            first_paragraph = cell.paragraphs[0] if cell.paragraphs else cell.add_paragraph()
            run = first_paragraph.add_run()

            # 插入图片，设置合适的大小
            run.add_picture(image_path, width=Inches(2.0))  # 表格单元格中使用较小尺寸

            logger.info(f"[表格单元格图片] ✅ 成功插入图片: {image_path}")

        except Exception as e:
            logger.error(f"[表格单元格图片] ❌ 插入失败: {str(e)}")
            raise e

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
                paragraph.add_run("表格数据为空")
                return

            rows = len(table_data)
            cols = len(alignments)

            # 简化处理：直接在段落位置插入表格
            paragraph_element = paragraph._element
            paragraph_parent = paragraph_element.getparent()

            # 创建表格
            table = self.doc.add_table(rows=rows, cols=cols)
            table_element = table._tbl

            # 直接在段落后插入表格
            paragraph_index = list(paragraph_parent).index(paragraph_element)
            paragraph_parent.insert(paragraph_index + 1, table_element)

            # 设置Markdown表格专用样式
            try:
                table.style = "Light List - Accent 1"  # 清爽的列表样式
            except Exception:
                try:
                    table.style = "Table Grid"  # 备选样式
                except Exception:
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
                for cell in table.rows[0].cells:
                    # 表头样式
                    for paragraph in cell.paragraphs:
                        for run in paragraph.runs:
                            run.bold = True

                    # 设置表头背景色（浅灰色，更适合Markdown风格）
                    try:
                        from docx.oxml import parse_xml

                        shading_elm = parse_xml(
                            r'<w:shd {} w:fill="F2F2F2"/>'.format(
                                'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
                            )
                        )
                        cell._tc.get_or_add_tcPr().append(shading_elm)
                    except Exception:
                        pass

            # 设置表格布局
            try:
                table.autofit = True
                from docx.shared import Inches

                table.width = Inches(6.5)
            except Exception:
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
            except Exception:
                pass

            logger.info(f"成功插入Markdown表格，大小: {rows}x{cols}，对齐: {alignments}")

        except Exception as e:
            paragraph.add_run(f"表格插入失败: {str(e)}")
            logger.error(f"插入Markdown表格失败: {str(e)}")

    def _insert_table_at_position(self, paragraph, table_data: List[List[str]]):
        """
        在段落当前位置插入表格，表格会出现在段落的前面

        Args:
            paragraph: Word段落对象
            table_data: 表格数据
        """
        try:
            if not table_data:
                paragraph.add_run("[表格数据为空]")
                return

            rows = len(table_data)
            cols = max(len(row) for row in table_data) if table_data else 1

            logger.info(f"[表格插入调试] 准备插入表格，大小: {rows}行 x {cols}列")

            # 获取段落在文档中的位置
            paragraph_element = paragraph._element
            paragraph_parent = paragraph_element.getparent()
            paragraph_index = list(paragraph_parent).index(paragraph_element)

            logger.info(f"[表格插入调试] 段落在父容器中的索引: {paragraph_index}")

            # 创建表格
            table = self.doc.add_table(rows=rows, cols=cols)
            table_element = table._tbl

            # 在段落之前插入表格（这样表格就出现在当前内容位置）
            paragraph_parent.insert(paragraph_index, table_element)

            logger.info(f"[表格插入调试] 表格已插入到段落之前，索引: {paragraph_index}")

            # 填充表格数据并设置样式
            self._fill_and_style_table(table, table_data)

        except Exception as e:
            paragraph.add_run(f"[表格插入失败: {str(e)}]")
            logger.error(f"插入表格失败: {str(e)}")

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

            # 简化处理：直接在段落位置插入表格
            paragraph_element = paragraph._element
            paragraph_parent = paragraph_element.getparent()

            # 创建表格
            table = self.doc.add_table(rows=rows, cols=cols)
            table_element = table._tbl

            # 直接在段落后插入表格
            paragraph_index = list(paragraph_parent).index(paragraph_element)
            paragraph_parent.insert(paragraph_index + 1, table_element)

            # 填充表格数据并设置样式
            self._fill_and_style_table(table, table_data)

        except Exception as e:
            paragraph.add_run(f"[表格插入失败: {str(e)}]")
            logger.error(f"插入表格失败: {str(e)}")

    def _fill_and_style_table(self, table, table_data: List[List[str]]):
        """
        填充表格数据并设置样式
        
        Args:
            table: Word表格对象
            table_data: 表格数据
        """
        rows = len(table_data)
        cols = max(len(row) for row in table_data) if table_data else 1

        # 设置更专业的表格样式
        try:
            # 尝试使用更好的内置样式
            table.style = "Light Shading - Accent 1"  # 浅色阴影样式
        except Exception:
            try:
                table.style = "Table Grid"  # 备选样式
            except Exception:
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
                    from docx.oxml import parse_xml

                    shading_elm = parse_xml(
                        r'<w:shd {} w:fill="D9E2F3"/>'.format(
                            'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
                        )
                    )
                    cell._tc.get_or_add_tcPr().append(shading_elm)
                except Exception:
                    pass  # 如果设置背景色失败，继续执行

        # 自动调整列宽
        try:
            table.autofit = True
            # 设置表格宽度为页面宽度
            from docx.shared import Inches

            table.width = Inches(6.5)  # 约A4页面宽度
        except Exception:
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
        except Exception:
            pass

        logger.info(f"成功设置表格样式和数据，大小: {rows}x{cols}")

    def _create_table_element(self, table_data: List[List[str]]):
        """
        创建表格元素
        
        Args:
            table_data: 表格数据 [[row1_col1, row1_col2], [row2_col1, row2_col2]]
        
        Returns:
            表格元素
        """
        logger.info(
            f"[表格创建] 开始创建表格元素，数据大小: {len(table_data)}x{len(table_data[0]) if table_data else 0}")

        if not table_data or not table_data[0]:
            logger.warning("[表格创建] 表格数据为空")
            return None

        try:
            # 创建表格
            rows = len(table_data)
            cols = len(table_data[0])
            table = self.doc.add_table(rows=rows, cols=cols)

            # 填充表格数据并设置样式
            self._fill_and_style_table(table, table_data)

            logger.info(f"[表格创建] ✅ 表格元素创建完成")
            return table._tbl

        except Exception as e:
            logger.error(f"[表格创建] ❌ 表格元素创建失败: {str(e)}", exc_info=True)
            return None

    def _create_new_paragraph_after_table(self, parent, table_index, style_info=None):
        """
        在表格后创建新段落
        
        Args:
            parent: 父容器
            table_index: 表格在父容器中的索引
            style_info: 样式信息字典，用于应用到新段落
        
        Returns:
            新段落对象
        """
        try:
            # 创建新段落
            new_paragraph = self.doc.add_paragraph()

            # 应用样式信息
            if style_info:
                self._apply_style_info(new_paragraph, style_info)
                alignment_info = f"继承样式，对齐={style_info.get('alignment', 'None')}"
            else:
                # 兜底：设置为左对齐
                from docx.enum.text import WD_ALIGN_PARAGRAPH
                new_paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
                alignment_info = "默认左对齐"

            paragraph_element = new_paragraph._element

            # 在表格后插入新段落
            parent.insert(table_index + 1, paragraph_element)

            logger.info(f"[段落创建] ✅ 在表格后创建新段落（{alignment_info}），索引: {table_index + 1}")
            return new_paragraph

        except Exception as e:
            logger.error(f"[段落创建] ❌ 创建新段落失败: {str(e)}", exc_info=True)
            return None

    def _extract_paragraph_style_info(self, paragraph):
        """
        提取段落的完整样式信息
        
        Args:
            paragraph: 段落对象
            
        Returns:
            dict: 包含段落样式信息的字典
        """
        try:
            style_info = {
                'alignment': paragraph.alignment,
                'paragraph_format': {},
                'style_name': None
            }

            # 提取段落格式信息
            if hasattr(paragraph, 'paragraph_format'):
                pf = paragraph.paragraph_format
                style_info['paragraph_format'] = {
                    'space_before': pf.space_before,
                    'space_after': pf.space_after,
                    'line_spacing': pf.line_spacing,
                    'left_indent': pf.left_indent,
                    'right_indent': pf.right_indent,
                    'first_line_indent': pf.first_line_indent,
                }

            # 提取样式名称
            if hasattr(paragraph, 'style') and paragraph.style:
                style_info['style_name'] = paragraph.style.name

            logger.debug(f"[样式提取] 段落样式信息: 对齐={style_info['alignment']}, 样式={style_info['style_name']}")
            return style_info

        except Exception as e:
            logger.warning(f"[样式提取] 提取段落样式失败: {str(e)}")
            return {'alignment': None, 'paragraph_format': {}, 'style_name': None}

    def _apply_style_info(self, paragraph, style_info):
        """
        将样式信息应用到段落
        
        Args:
            paragraph: 目标段落对象
            style_info: 样式信息字典
        """
        try:
            # 应用对齐方式
            if style_info.get('alignment') is not None:
                paragraph.alignment = style_info['alignment']
                logger.debug(f"[样式应用] 应用对齐方式: {style_info['alignment']}")

            # 应用段落格式
            paragraph_format = style_info.get('paragraph_format', {})
            if paragraph_format:
                pf = paragraph.paragraph_format

                for attr_name, value in paragraph_format.items():
                    if value is not None and hasattr(pf, attr_name):
                        try:
                            setattr(pf, attr_name, value)
                            logger.debug(f"[样式应用] 应用段落格式 {attr_name}={value}")
                        except Exception as attr_e:
                            logger.debug(f"[样式应用] 跳过段落格式 {attr_name}: {str(attr_e)}")

            # 应用样式名称
            style_name = style_info.get('style_name')
            if style_name:
                try:
                    paragraph.style = style_name
                    logger.debug(f"[样式应用] 应用样式名称: {style_name}")
                except Exception as style_e:
                    logger.debug(f"[样式应用] 跳过样式名称应用: {str(style_e)}")

        except Exception as e:
            logger.warning(f"[样式应用] 应用样式信息失败: {str(e)}")

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
                "file_name": csv_info.get("file_name", "未知CSV文件"),
                "table_data": csv_info.get("table_data", []),
                "resource_type": csv_info.get("type", "content"),
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
                                                # 在表格单元格中插入实际图片
                                                image_path = resource_info.get("local_path") or resource_info.get(
                                                    "path", "")
                                                if image_path and os.path.exists(image_path):
                                                    try:
                                                        # 清空单元格文本
                                                        cell_text = cell_text.replace(placeholder, "")
                                                        # 在单元格中插入图片
                                                        self._insert_image_in_table_cell(cell, image_path)
                                                        logger.info(f"✅ 表格单元格中成功插入图片: {image_path}")
                                                    except Exception as e:
                                                        logger.error(f"❌ 表格单元格插入图片失败: {str(e)}")
                                                        # 失败时显示文件名
                                                        cell_text = cell_text.replace(placeholder,
                                                                                      os.path.basename(image_path))
                                                else:
                                                    # 图片文件不存在，显示路径
                                                    cell_text = cell_text.replace(placeholder, resource_info.get("path",
                                                                                                                 placeholder))
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

        # 添加最终文档内容检查
        self._log_final_document_content(doc)

        return doc

    def _log_final_document_content(self, doc):
        """记录最终文档内容，用于调试标签来源"""
        try:
            logger.info("[最终文档] 开始检查文档最终内容")
            logger.info(f"[最终文档] 总段落数: {len(doc.paragraphs)}")

            for i, paragraph in enumerate(doc.paragraphs):
                paragraph_text = paragraph.text.strip()
                if paragraph_text:
                    # 检查是否包含file content标签
                    if 'file content' in paragraph_text.lower():
                        logger.warning(f"[最终文档] ⚠️ 发现file content标签，段落{i}: {paragraph_text[:200]}...")
                    # 记录前10个段落的内容
                    elif i < 10:
                        logger.info(f"[最终文档] 段落{i}: {paragraph_text[:100]}...")

            logger.info("[最终文档] 文档内容检查完成")
        except Exception as e:
            logger.error(f"[最终文档] 检查文档内容失败: {str(e)}")


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
