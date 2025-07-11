import os
import tempfile
from pathlib import Path
from typing import IO, Dict, List, Any
from urllib.parse import unquote, urlparse
import re

import requests
from bisheng.utils.minio_client import MinioClient
from bisheng.utils.util import _is_valid_url
from docx import Document
from docx.shared import Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from loguru import logger

# 检查是否有openpyxl和pandas，用于处理Excel文件
try:
    import pandas as pd
    import openpyxl
    EXCEL_SUPPORT = True
except ImportError:
    EXCEL_SUPPORT = False
    logger.warning("未安装openpyxl或pandas，无法处理Excel文件")


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

    def _excel_to_table(self, excel_path: str) -> List[List[str]]:
        """
        将Excel文件转换为表格数据
        
        Args:
            excel_path: Excel文件路径
            
        Returns:
            List[List[str]]: 表格数据
        """
        if not EXCEL_SUPPORT:
            return [["Excel处理功能不可用", "请安装openpyxl和pandas"]]
        
        try:
            # 读取Excel文件
            df = pd.read_excel(excel_path, sheet_name=0)  # 读取第一个工作表
            
            # 转换为列表格式
            table_data = []
            # 添加表头
            headers = [str(col) for col in df.columns]
            table_data.append(headers)
            
            # 添加数据行
            for _, row in df.iterrows():
                row_data = [str(cell) if pd.notna(cell) else "" for cell in row]
                table_data.append(row_data)
            
            logger.info(f"成功解析Excel文件: {excel_path}, 行数: {len(table_data)}")
            return table_data
            
        except Exception as e:
            logger.error(f"解析Excel文件失败: {excel_path}, 错误: {str(e)}")
            return [["Excel文件解析失败", str(e)]]

    def _markdown_table_to_data(self, markdown_table: str) -> List[List[str]]:
        """
        将Markdown表格转换为表格数据
        
        Args:
            markdown_table: Markdown表格文本
            
        Returns:
            List[List[str]]: 表格数据
        """
        try:
            lines = markdown_table.strip().split('\n')
            table_data = []
            
            for i, line in enumerate(lines):
                # 跳过分隔线（包含---的行）
                if '---' in line:
                    continue
                
                # 解析表格行
                cells = [cell.strip() for cell in line.split('|')]
                # 移除首尾的空元素（由于|开头和结尾导致的）
                if cells[0] == '':
                    cells = cells[1:]
                if cells and cells[-1] == '':
                    cells = cells[:-1]
                
                if cells:  # 只添加非空行
                    table_data.append(cells)
            
            logger.info(f"成功解析Markdown表格，行数: {len(table_data)}")
            return table_data
            
        except Exception as e:
            logger.error(f"解析Markdown表格失败: {str(e)}")
            return [["Markdown表格解析失败", str(e)]]

    def _insert_table(self, paragraph, table_data: List[List[str]]):
        """
        在段落后插入表格
        
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
            table.style = 'Table Grid'  # 设置表格样式
            
            # 填充表格数据
            for i, row_data in enumerate(table_data):
                for j, cell_data in enumerate(row_data):
                    if j < cols:  # 确保不超出列数
                        table.cell(i, j).text = str(cell_data)
            
            # 设置表头样式（第一行加粗）
            if rows > 0:
                for cell in table.rows[0].cells:
                    for paragraph in cell.paragraphs:
                        for run in paragraph.runs:
                            run.bold = True
            
            logger.info(f"成功插入表格，大小: {rows}x{cols}")
            
        except Exception as e:
            paragraph.add_run(f"[表格插入失败: {str(e)}]")
            logger.error(f"插入表格失败: {str(e)}")

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
            resources = {'images': [], 'excel_files': [], 'markdown_tables': []}
        
        # 创建占位符到资源的映射
        placeholder_map = {}
        
        # 图片占位符映射
        for img_info in resources.get('images', []):
            placeholder_map[img_info['placeholder']] = {
                'type': 'image',
                'path': img_info['local_path'],
                'alt_text': img_info['alt_text'],
                'resource_type': img_info['type']
            }
        
        # Excel文件占位符映射
        for excel_info in resources.get('excel_files', []):
            placeholder_map[excel_info['placeholder']] = {
                'type': 'excel',
                'path': excel_info['local_path'],
                'resource_type': excel_info['type']
            }
        
        # Markdown表格占位符映射
        for table_info in resources.get('markdown_tables', []):
            placeholder_map[table_info['placeholder']] = {
                'type': 'markdown_table',
                'content': table_info['content']
            }
        
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
                                            if resource_info['type'] == 'image':
                                                # 在表格单元格中插入图片（简化处理）
                                                cell_text = cell_text.replace(placeholder, f"[图片: {resource_info['alt_text']}]")
                                            elif resource_info['type'] == 'excel':
                                                cell_text = cell_text.replace(placeholder, "[Excel表格]")
                                            elif resource_info['type'] == 'markdown_table':
                                                cell_text = cell_text.replace(placeholder, "[Markdown表格]")
                                    
                                    one.runs[0].text = cell_text
                                    for r_index, r in enumerate(one.runs):
                                        if r_index == 0:
                                            continue
                                        r.text = ''

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
                        part_text = ''.join([r.text for r in p.runs[i:j]])
                        if k1 in part_text:
                            # 找到最小的范围内包含k1的runs
                            tmp_i, tmp_j = i, j
                            while tmp_i <= tmp_j:
                                tmp_part_text = ''.join([r.text for r in p.runs[tmp_i:tmp_j]])
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
                        replace_mapping = [(h_text, ''), (m_text, v1), (t_text, '')]
                    else:
                        m_texts = [p.runs[i].text for i in range(s + 1, e - 1)]
                        m_text = ''.join(m_texts)
                        head_tail = k1.split(m_text, 1)
                        assert len(head_tail) == 2
                        h_text = head_tail[0]
                        t_text = head_tail[1]
                        replace_mapping = [(h_text, '')]
                        replace_mapping.append((m_texts[0], v1))
                        for text in m_texts[1:]:
                            replace_mapping.append((text, ''))
                        replace_mapping.append((t_text, ''))

                    for i in range(s, e):
                        _k, _v = replace_mapping[i - s]
                        p.runs[i].text = p.runs[i].text.replace(_k, _v)
                
                # 处理段落中的资源占位符
                paragraph_text = p.text
                for placeholder, resource_info in placeholder_map.items():
                    if placeholder in paragraph_text:
                        if resource_info['type'] == 'image':
                            # 插入图片
                            # 清空段落文本中的占位符
                            for run in p.runs:
                                if placeholder in run.text:
                                    run.text = run.text.replace(placeholder, "")
                            # 插入图片
                            self._insert_image(p, resource_info['path'], resource_info['alt_text'])
                            
                        elif resource_info['type'] == 'excel':
                            # 插入Excel表格
                            if resource_info['resource_type'] in ['downloaded', 'local']:
                                table_data = self._excel_to_table(resource_info['path'])
                            else:
                                table_data = [["Excel文件加载失败", resource_info['path']]]
                            
                            # 清空段落文本中的占位符
                            for run in p.runs:
                                if placeholder in run.text:
                                    run.text = run.text.replace(placeholder, "")
                            
                            self._insert_table(p, table_data)
                            
                        elif resource_info['type'] == 'markdown_table':
                            # 插入Markdown表格
                            table_data = self._markdown_table_to_data(resource_info['content'])
                            
                            # 清空段落文本中的占位符
                            for run in p.runs:
                                if placeholder in run.text:
                                    run.text = run.text.replace(placeholder, "")
                            
                            self._insert_table(p, table_data)

        return doc


def test_replace_string(template_file, kv_dict: dict, file_name: str):
    # If the file is a web path, download it to a temporary file, and use that
    if not os.path.isfile(template_file) and _is_valid_url(template_file):
        r = requests.get(template_file)

        if r.status_code != 200:
            raise ValueError(
                'Check the url of your file; returned status code %s'
                % r.status_code
            )

        temp_dir = tempfile.TemporaryDirectory()
        temp_file = Path(temp_dir.name) / unquote(urlparse(template_file
                                                           ).path.split('/')[-1])
        with open(temp_file, mode='wb') as f:
            f.write(r.content)

        template_file = temp_file
    elif not os.path.isfile(template_file):
        raise ValueError('File path %s is not a valid file or url' % template_file)

    template_dict = []
    for k, v in kv_dict.items():
        template_dict.append(['{{'+k+'}}', v])

    doc = DocxTemplateRender(str(template_file))
    output = doc.render(template_dict)

    temp_dir = tempfile.TemporaryDirectory()
    temp_file = Path(temp_dir.name) / file_name
    output.save(temp_file)
    MinioClient().upload_minio(file_name, temp_file)

    return file_name
