import io
import re
import os
import tempfile
import requests
from urllib.parse import urlparse, unquote
from uuid import uuid4
from loguru import logger
from typing import Dict, Tuple, Any, List, Optional
from enum import Enum
from dataclasses import dataclass
import pandas as pd
from openpyxl import load_workbook
from charset_normalizer import detect

from bisheng.core.storage.minio.minio_manager import get_minio_storage_sync
from bisheng.utils.docx_temp import DocxTemplateRender
from bisheng.workflow.callback.event import OutputMsgData
from bisheng.workflow.nodes.base import BaseNode


class ResourceType(Enum):
    """资源类型枚举"""
    IMAGE = "image"
    TABLE = "table"
    TEXT = "text"


class ImageSource(Enum):
    """图片来源类型"""

    LOCAL_FILE = "local_file"  # 本地文件路径
    HTTP_URL = "http_url"  # HTTP/HTTPS链接
    MINIO_PATH = "minio_path"  # MinIO路径
    MARKDOWN_REF = "markdown_ref"  # Markdown引用格式


class TableSource(Enum):
    """表格来源类型"""

    MARKDOWN_TABLE = "markdown_table"  # |---|---|格式
    CSV_CONTENT = "csv_content"  # [file content begin]...[end]格式
    EXCEL_CONTENT = "excel_content"  # Excel文件内容


@dataclass
class ResourceData:
    """资源数据类"""

    resource_id: int
    resource_type: ResourceType
    placeholder: str
    position: int  # 在原文中的位置
    original_content: str  # 原始匹配内容
    pattern_name: str  # 匹配的模式名称

    # 图片特有字段
    image_source: Optional[ImageSource] = None
    original_path: Optional[str] = None
    local_path: Optional[str] = None
    alt_text: Optional[str] = None

    # 表格特有字段
    table_source: Optional[TableSource] = None
    table_data: Optional[List[List[str]]] = None
    alignments: Optional[List[str]] = None
    file_name: Optional[str] = None

    # 处理状态
    download_success: bool = False
    error_message: Optional[str] = None


class ResourcePlaceholderManager:
    """统一的资源占位符管理器"""

    def __init__(self):
        self.counter = 0
        self.resources: List[ResourceData] = []
        self.placeholder_map: Dict[str, ResourceData] = {}  # placeholder -> resource映射

    def create_placeholder(
        self, resource_type: ResourceType, position: int, original_content: str, pattern_name: str
    ) -> str:
        """创建新的占位符"""
        resource_id = self.counter
        self.counter += 1

        placeholder = f"__RESOURCE_{resource_id:04d}__"  # 使用4位数字，便于排序

        resource = ResourceData(
            resource_id=resource_id,
            resource_type=resource_type,
            placeholder=placeholder,
            position=position,
            original_content=original_content,
            pattern_name=pattern_name,
        )

        self.resources.append(resource)
        self.placeholder_map[placeholder] = resource

        return placeholder

    def get_resource_by_placeholder(self, placeholder: str) -> Optional[ResourceData]:
        """根据占位符获取资源"""
        return self.placeholder_map.get(placeholder)

    def get_resources_by_type(self, resource_type: ResourceType) -> List[ResourceData]:
        """获取指定类型的所有资源"""
        return [r for r in self.resources if r.resource_type == resource_type]

    def get_sorted_resources(self) -> List[ResourceData]:
        """按位置排序获取所有资源"""
        return sorted(self.resources, key=lambda x: x.position)


@dataclass
class MatchPattern:
    """匹配模式定义"""

    name: str
    resource_type: ResourceType
    pattern: str
    flags: int
    priority: int  # 优先级，数字越小优先级越高
    handler_method: str


class OverlapResolver:
    """重叠资源解决器"""

    @staticmethod
    def resolve_overlapping_resources(resources: List[ResourceData]) -> List[ResourceData]:
        """解决重叠资源问题"""
        if not resources:
            return []

        # 按开始位置排序
        sorted_resources = sorted(resources, key=lambda x: x.position)
        resolved_resources = []

        for current in sorted_resources:
            # 检查是否与已解决的资源重叠
            overlapping_existing = None
            for existing in resolved_resources:
                if OverlapResolver._is_overlapping(current, existing):
                    overlapping_existing = existing
                    break

            if overlapping_existing:
                # 处理重叠：优先保留更精确的匹配
                if OverlapResolver._should_replace(current, overlapping_existing):
                    resolved_resources.remove(overlapping_existing)
                    resolved_resources.append(current)
                    logger.info(f"替换重叠资源: {overlapping_existing.placeholder} -> {current.placeholder}")
                else:
                    logger.info(f"跳过重叠资源: {current.placeholder}")
            else:
                resolved_resources.append(current)

        return sorted(resolved_resources, key=lambda x: x.position)

    @staticmethod
    def _is_overlapping(res1: ResourceData, res2: ResourceData) -> bool:
        """判断两个资源是否重叠"""
        # 计算结束位置
        end1 = res1.position + len(res1.original_content)
        end2 = res2.position + len(res2.original_content)

        # 检查是否有重叠区域
        return not (end1 <= res2.position or end2 <= res1.position)

    @staticmethod
    def _should_replace(new_res: ResourceData, existing_res: ResourceData) -> bool:
        """判断是否应该用新资源替换现有资源"""
        # 优先级规则：
        # 1. 更具体的匹配优先（如 Markdown 图片 > 普通 URL）
        # 2. 匹配长度更精确的优先
        # 3. 同类型资源，先匹配的优先

        priority_map = {
            "markdown_table": 1,     # 表格优先级最高，包含其他资源
            "markdown_image": 2,     # 图片次之
            "minio_image": 3,
            "http_image": 4,
            "minio_excel_csv": 5,    # Excel/CSV文件
            "http_excel_csv": 6,
            "local_excel_csv": 7,
            "local_image": 8,
        }

        new_priority = priority_map.get(new_res.pattern_name, 999)
        existing_priority = priority_map.get(existing_res.pattern_name, 999)

        return new_priority < existing_priority


class PatternMatcher:
    """模式匹配器，负责识别内容中的各种资源"""

    def __init__(self):
        self.patterns = [
            # 优先级1: Markdown图片 (最明确的格式)
            MatchPattern(
                name="markdown_image",
                resource_type=ResourceType.IMAGE,
                pattern=r"!\[([^\]]*)\]\(([^)]+\.(?:png|jpg|jpeg|bmp|gif|webp)(?:\?[^)]*)?)\)",
                flags=re.IGNORECASE,
                priority=1,
                handler_method="_handle_markdown_image",
            ),
            # 优先级2: 独立的Markdown表格（支持行首空格缩进）
            MatchPattern(
                name="markdown_table",
                resource_type=ResourceType.TABLE,
                pattern=r"(\s*\|[^\r\n]*\|[^\r\n]*(?:\r?\n\s*\|[^\r\n]*\|[^\r\n]*)+)",
                flags=re.MULTILINE,
                priority=2,
                handler_method="_handle_markdown_table",
            ),
            # 优先级3: MinIO图片路径
            MatchPattern(
                name="minio_image",
                resource_type=ResourceType.IMAGE,
                pattern=r"((?:minio://|/bisheng/|/tmp-dir/|/tmp/)[^\s]*\.(?:png|jpg|jpeg|bmp|gif|webp))",
                flags=re.IGNORECASE,
                priority=3,
                handler_method="_handle_minio_image",
            ),
            # 优先级4: HTTP图片链接
            MatchPattern(
                name="http_image",
                resource_type=ResourceType.IMAGE,
                pattern=r"(https?://[^\s\u4e00-\u9fff]*\.(?:png|jpg|jpeg|bmp|gif|webp)(?:\?[^\s\u4e00-\u9fff]*)?)",
                flags=re.IGNORECASE,
                priority=4,
                handler_method="_handle_http_image",
            ),
            # 优先级5: Excel/CSV文件 (MinIO路径和HTTP链接)
            MatchPattern(
                name="minio_excel_csv",
                resource_type=ResourceType.TABLE,
                pattern=r"((?:minio://|/bisheng/|/tmp-dir/|/tmp/)[^\s]*\.(?:xlsx?|csv))",
                flags=re.IGNORECASE,
                priority=5,
                handler_method="_handle_minio_excel_csv",
            ),
            # 优先级6: HTTP Excel/CSV文件链接
            MatchPattern(
                name="http_excel_csv",
                resource_type=ResourceType.TABLE,
                pattern=r"(https?://[^\s\u4e00-\u9fff]*\.(?:xlsx?|csv)(?:\?[^\s\u4e00-\u9fff]*)?)",
                flags=re.IGNORECASE,
                priority=6,
                handler_method="_handle_http_excel_csv",
            ),
            # 优先级7: 本地Excel/CSV文件路径
            MatchPattern(
                name="local_excel_csv",
                resource_type=ResourceType.TABLE,
                pattern=r"([^\s]*[/\\][^\s]*\.(?:xlsx?|csv))",
                flags=re.IGNORECASE,
                priority=7,
                handler_method="_handle_local_excel_csv",
            ),
            # 优先级8: 本地图片路径 (最宽泛，最后匹配)
            MatchPattern(
                name="local_image",
                resource_type=ResourceType.IMAGE,
                pattern=r"([^\s]*[/\\][^\s]*\.(?:png|jpg|jpeg|bmp|gif|webp))",
                flags=re.IGNORECASE,
                priority=8,
                handler_method="_handle_local_image",
            ),
        ]

    def find_all_matches(self, content: str) -> List[Dict[str, Any]]:
        """找到内容中的所有匹配项"""
        all_matches = []

        for pattern in self.patterns:
            for match in re.finditer(pattern.pattern, content, pattern.flags):
                match_info = {
                    "pattern_name": pattern.name,
                    "resource_type": pattern.resource_type,
                    "start": match.start(),
                    "end": match.end(),
                    "full_match": match.group(0),
                    "groups": match.groups(),
                    "handler_method": pattern.handler_method,
                    "priority": pattern.priority,
                }
                all_matches.append(match_info)

        # 只按位置排序，不去重（重叠处理交给后续步骤）
        return sorted(all_matches, key=lambda x: x["start"])


class ContentParser:
    """内容解析器，负责解析变量内容并生成占位符"""

    def __init__(self, minio_client):
        self.placeholder_manager = ResourcePlaceholderManager()
        self.pattern_matcher = PatternMatcher()
        self.minio_client = minio_client
        self.logger = logger
        self._table_image_resources = []  # 临时存储表格内的图片资源

    def parse_variable_content(self, var_name: str, content: str) -> tuple[str, List[ResourceData]]:
        """
        解析单个变量的内容

        Args:
            var_name: 变量名
            content: 变量内容

        Returns:
            (处理后的内容, 资源列表)
        """
        if not isinstance(content, str):
            content = str(content)

        self.logger.info(f"开始解析变量 '{var_name}', 内容长度: {len(content)}")
        
        # 添加详细的内容预览日志
        if content:
            content_preview = content.replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')
            if len(content_preview) > 300:
                self.logger.info(f"变量 '{var_name}' 内容预览（前300字符）: {content_preview[:300]}...")
            else:
                self.logger.info(f"变量 '{var_name}' 完整内容: {content_preview}")
        else:
            self.logger.info(f"变量 '{var_name}' 内容为空")

        # 1. 找到所有匹配项
        matches = self.pattern_matcher.find_all_matches(content)

        self.logger.info(f"变量 '{var_name}' 中找到 {len(matches)} 个资源匹配项")
        for i, match in enumerate(matches):
            self.logger.debug(f"匹配项 {i+1}: {match['pattern_name']} at {match['start']}-{match['end']}")

        # 2. 创建资源对象
        resources = []
        for match in matches:
            try:
                # 创建占位符
                placeholder = self.placeholder_manager.create_placeholder(
                    resource_type=match["resource_type"],
                    position=match["start"],
                    original_content=match["full_match"],
                    pattern_name=match["pattern_name"],
                )

                # 获取资源对象并填充详细信息
                resource = self.placeholder_manager.get_resource_by_placeholder(placeholder)

                # 调用对应的处理方法
                handler = getattr(self, match["handler_method"])
                handler(resource, match)

                resources.append(resource)

                self.logger.info(f"成功处理资源: {match['pattern_name']} -> {placeholder}")

            except Exception as e:
                self.logger.error(f"处理资源失败: {match['pattern_name']}, 错误: {str(e)}")
                # 继续处理其他资源，不中断整个流程

        # 3. 解决重叠问题
        resolved_resources = OverlapResolver.resolve_overlapping_resources(resources)

        # 4. 收集表格内的图片资源
        table_image_resources = []
        for resource in resolved_resources:
            if resource.resource_type == ResourceType.TABLE and hasattr(self, '_table_image_resources'):
                table_image_resources.extend(self._table_image_resources)
                self._table_image_resources = []  # 清空临时列表

        # 5. 替换内容
        processed_content = self._replace_content_with_placeholders(content, resolved_resources)

        # 6. 合并所有资源（主要资源 + 表格内图片资源）
        all_resources = resolved_resources + table_image_resources

        self.logger.info(f"变量 '{var_name}' 解析完成，生成 {len(all_resources)} 个资源（主要 {len(resolved_resources)} 个，表格内图片 {len(table_image_resources)} 个）")

        return processed_content, all_resources

    def _replace_content_with_placeholders(self, content: str, resources: List[ResourceData]) -> str:
        """正确的内容替换逻辑"""
        # 按位置从后往前替换（避免位置偏移）
        sorted_resources = sorted(resources, key=lambda x: x.position, reverse=True)

        processed_content = content
        for resource in sorted_resources:
            start_pos = resource.position
            end_pos = start_pos + len(resource.original_content)

            # 验证内容匹配
            actual_content = processed_content[start_pos:end_pos]
            if actual_content != resource.original_content:
                self.logger.warning(f"内容不匹配，跳过替换: 期望 '{resource.original_content}', 实际 '{actual_content}'")
                continue

            # 执行替换
            processed_content = processed_content[:start_pos] + resource.placeholder + processed_content[end_pos:]

            self.logger.debug(f"替换成功: '{resource.original_content}' -> '{resource.placeholder}'")

        return processed_content

    # 各种资源处理方法
    def _handle_markdown_image(self, resource: ResourceData, match: Dict):
        """处理Markdown格式图片"""
        alt_text, img_path = match["groups"]

        resource.image_source = ImageSource.MARKDOWN_REF
        resource.original_path = img_path
        resource.alt_text = alt_text or "图片"

        self.logger.debug(f"Markdown图片: alt='{alt_text}', path='{img_path}'")

    def _handle_markdown_table(self, resource: ResourceData, match: Dict):
        """处理独立的Markdown表格"""
        table_content = match["full_match"]

        resource.table_source = TableSource.MARKDOWN_TABLE
        resource.file_name = "table_data.csv"  # 默认文件名

        # 解析表格数据
        resource.table_data, resource.alignments = self._parse_table_data(table_content)

        self.logger.debug(f"Markdown表格: rows={len(resource.table_data) if resource.table_data else 0}")

    def _handle_minio_image(self, resource: ResourceData, match: Dict):
        """处理MinIO图片路径"""
        img_path = match["full_match"]

        # 统一走智能本地下载pipeline：本地->MinIO->原路径
        resource.image_source = ImageSource.LOCAL_FILE
        resource.original_path = img_path
        resource.alt_text = "图片"

        self.logger.debug(f"MinIO图片: path='{img_path}'")

    def _handle_http_image(self, resource: ResourceData, match: Dict):
        """处理HTTP图片链接"""
        img_url = match["full_match"]

        resource.image_source = ImageSource.HTTP_URL
        resource.original_path = img_url
        resource.alt_text = "图片"

        self.logger.debug(f"HTTP图片: url='{img_url}'")

    def _handle_local_image(self, resource: ResourceData, match: Dict):
        """处理本地图片路径"""
        img_path = match["full_match"]

        # 清理路径中的多余字符，如 [''] 等
        img_path = img_path.strip("[]'\"")

        resource.image_source = ImageSource.LOCAL_FILE
        resource.original_path = img_path
        resource.alt_text = "图片"

        self.logger.debug(f"本地图片: path='{img_path}'")

    def _handle_minio_excel_csv(self, resource: ResourceData, match: Dict):
        """处理MinIO Excel/CSV文件"""
        file_path = match["full_match"]
        
        resource.table_source = self._determine_table_source_by_extension(file_path)
        resource.original_path = file_path
        resource.file_name = os.path.basename(file_path)
        
        self.logger.debug(f"MinIO Excel/CSV文件: path='{file_path}', type='{resource.table_source.value}'")

    def _handle_http_excel_csv(self, resource: ResourceData, match: Dict):
        """处理HTTP Excel/CSV文件"""
        file_url = match["full_match"]
        
        resource.table_source = self._determine_table_source_by_extension(file_url)
        resource.original_path = file_url
        resource.file_name = os.path.basename(urlparse(file_url).path) or "spreadsheet_file"
        
        self.logger.debug(f"HTTP Excel/CSV文件: url='{file_url}', type='{resource.table_source.value}'")

    def _handle_local_excel_csv(self, resource: ResourceData, match: Dict):
        """处理本地Excel/CSV文件"""
        file_path = match["full_match"]
        
        # 清理路径中的多余字符
        file_path = file_path.strip("[]'\"")
        
        resource.table_source = self._determine_table_source_by_extension(file_path)
        resource.original_path = file_path
        resource.file_name = os.path.basename(file_path)
        
        self.logger.debug(f"本地Excel/CSV文件: path='{file_path}', type='{resource.table_source.value}'")

    def _determine_table_source_by_extension(self, file_path: str) -> TableSource:
        """根据文件扩展名确定表格源类型"""
        file_path_lower = file_path.lower()
        
        if file_path_lower.endswith('.csv'):
            return TableSource.CSV_CONTENT
        elif file_path_lower.endswith(('.xlsx', '.xls')):
            return TableSource.EXCEL_CONTENT
        else:
            # 默认为CSV
            return TableSource.CSV_CONTENT

    def _parse_table_data(self, table_content: str) -> tuple[List[List[str]], List[str]]:
        """解析表格数据，同时处理表格内的图片"""
        try:
            # 先解析表格结构
            table_data, alignments = self._parse_markdown_table_from_content(table_content)
            
            # 处理表格内的图片链接
            self._process_images_in_table(table_data)
            
            return table_data, alignments
        except Exception as e:
            self.logger.error(f"解析表格数据失败: {str(e)}")
            return [["解析失败", str(e)]], ["left"]

    def _parse_markdown_table_from_content(self, content: str) -> Tuple[list, list]:
        """
        从文件内容中解析Markdown表格

        Args:
            content: 文件内容

        Returns:
            tuple: (表格数据, 对齐信息列表)
        """
        try:
            # 查找所有Markdown表格（支持行首缩进）
            table_pattern = r"(\s*\|[^\r\n]*\|[^\r\n]*(?:\r?\n\s*\|[^\r\n]*\|[^\r\n]*)+)"
            tables = re.findall(table_pattern, content, re.MULTILINE)

            if not tables:
                self.logger.warning("内容中没有找到Markdown表格")
                return [["内容解析失败", "未找到表格数据"]], ["left"]

            # 合并所有表格（如果有多个表格，合并为一个大表格）
            all_rows = []
            alignments = []

            for i, table_content in enumerate(tables):
                # 保留所有行，包括空行 - 完全保留原始表格结构
                lines = [line.strip() for line in table_content.strip().split("\n")]

                if len(lines) < 2:
                    continue

                table_rows = []
                table_alignments = []
                separator_found = False

                for line in lines:
                    # 跳过完全空的行，但保留只有竖线的空表格行
                    if not line:
                        continue
                        
                    # 检查是否是分隔符行
                    if self._is_separator_line(line):
                        table_alignments = self._parse_alignments(line)
                        separator_found = True
                        continue

                    # 解析数据行 - 保留所有表格行，包括空行
                    cells = self._parse_table_row(line)
                    # 移除 if cells 条件，保留空表格行
                    cleaned_cells = []
                    for cell in cells:
                        cleaned_cell = self._clean_cell_content(cell)
                        cleaned_cells.append(cleaned_cell)
                    table_rows.append(cleaned_cells)

                # 如果没有找到分隔符，使用默认对齐
                if not separator_found and table_rows:
                    table_alignments = ["left"] * len(table_rows[0])

                # 将表格添加到总列表
                if table_rows:
                    if i == 0:
                        alignments = table_alignments
                    all_rows.extend(table_rows)

            # 确保所有行的列数一致
            if all_rows:
                max_cols = max(len(row) for row in all_rows)
                for row in all_rows:
                    while len(row) < max_cols:
                        row.append("")

                # 确保对齐信息数量匹配列数
                while len(alignments) < max_cols:
                    alignments.append("left")
                alignments = alignments[:max_cols]

            self.logger.info(f"成功解析内容中的表格，大小: {len(all_rows)}行 x {len(alignments)}列")
            return all_rows, alignments

        except Exception as e:
            self.logger.error(f"解析内容中的表格失败: {str(e)}")
            return [["表格解析失败", str(e)]], ["left"]

    def _is_separator_line(self, line: str) -> bool:
        """检查是否是Markdown表格的分隔符行"""
        content = line.strip().strip("|").strip()
        if not content:
            return False

        cells = [cell.strip() for cell in content.split("|")]
        
        # 必须至少有一个单元格包含分隔符字符（-或:）
        has_separator_chars = False
        for cell in cells:
            if not cell:
                continue
            # 检查是否包含分隔符字符
            if '-' in cell or ':' in cell:
                has_separator_chars = True
            # 移除分隔符字符后检查是否还有其他内容
            clean_cell = cell.replace("-", "").replace(":", "").strip()
            if clean_cell:
                return False
        
        # 只有包含分隔符字符的行才能被认为是分隔符行
        return has_separator_chars

    def _parse_alignments(self, separator_line: str) -> list:
        """从分隔符行解析列对齐方式"""
        alignments = []
        content = separator_line.strip().strip("|").strip()
        cells = [cell.strip() for cell in content.split("|")]

        for cell in cells:
            if not cell:
                alignments.append("left")
                continue

            if cell.startswith(":") and cell.endswith(":"):
                alignments.append("center")
            elif cell.endswith(":"):
                alignments.append("right")
            else:
                alignments.append("left")

        return alignments

    def _parse_table_row(self, line: str) -> list:
        """解析表格行"""
        content = line.strip()
        if content.startswith("|"):
            content = content[1:]
        if content.endswith("|"):
            content = content[:-1]

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

        # 总是添加最后一个单元格，确保空表格行也能正确解析
        cells.append(current_cell.strip())

        return cells

    def _clean_cell_content(self, cell: str) -> str:
        """清理单元格内容"""
        if not cell:
            return ""

        cleaned = cell.strip()
        cleaned = cleaned.replace("**", "")
        cleaned = cleaned.replace("*", "")
        cleaned = cleaned.replace("`", "")

        cleaned = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", cleaned)

        if len(cleaned) > 100:
            cleaned = cleaned[:97] + "..."

        return cleaned

    def _process_images_in_table(self, table_data: List[List[str]]):
        """处理表格内的图片链接，创建图片资源"""
        if not table_data:
            return
            
        for row_idx, row in enumerate(table_data):
            for col_idx, cell in enumerate(row):
                if not cell:
                    continue
                    
                # 在单元格内容中查找并处理图片链接
                updated_cell = self._process_cell_images(cell)
                table_data[row_idx][col_idx] = updated_cell
                
    def _process_cell_images(self, cell_content: str) -> str:
        """处理单元格内的图片，使用现有的模式匹配逻辑"""
        if not cell_content:
            return cell_content
            
        # 复用现有的模式匹配逻辑查找所有图片
        matches = self.pattern_matcher.find_all_matches(cell_content)
        
        # 只处理图片类型的匹配
        image_matches = [m for m in matches if m["resource_type"] == ResourceType.IMAGE]
        
        updated_content = cell_content
        
        # 从后往前处理，避免位置偏移
        for match in reversed(image_matches):
            # 创建图片资源
            placeholder = self.placeholder_manager.create_placeholder(
                resource_type=match["resource_type"],
                position=match["start"],
                original_content=match["full_match"],
                pattern_name=match["pattern_name"],
            )
            
            # 获取资源对象并调用对应的处理方法
            resource = self.placeholder_manager.get_resource_by_placeholder(placeholder)
            handler = getattr(self, match["handler_method"])
            handler(resource, match)
            
            # 将表格内的图片资源添加到临时列表（避免被重叠解决器跳过）
            self._table_image_resources.append(resource)
            
            self.logger.info(f"表格内图片: {match['pattern_name']} {match['full_match']} -> {placeholder}")
            
            # 替换为占位符
            start_pos = match["start"]
            end_pos = match["end"]
            updated_content = updated_content[:start_pos] + placeholder + updated_content[end_pos:]
            
        return updated_content

class ResourceDownloadManager:
    """资源下载管理器"""

    def __init__(self, minio_client):
        self.minio_client = minio_client
        self.temp_files: List[str] = []  # 管理所有临时文件
        self.logger = logger

    def download_all_resources(self, resources: List[ResourceData]) -> Dict[str, Any]:
        """
        下载所有需要下载的资源

        Returns:
            下载统计信息
        """
        stats = {"total": len(resources), "images_success": 0, "images_failed": 0, "tables_processed": 0, "errors": []}

        image_resources = [r for r in resources if r.resource_type == ResourceType.IMAGE]
        table_resources = [r for r in resources if r.resource_type == ResourceType.TABLE]

        self.logger.info(f"开始下载资源: 图片 {len(image_resources)} 个, 表格 {len(table_resources)} 个")

        # 下载图片资源
        for resource in image_resources:
            try:
                self._download_image_resource(resource)
                if resource.download_success:
                    stats["images_success"] += 1
                else:
                    stats["images_failed"] += 1
            except Exception as e:
                stats["images_failed"] += 1
                stats["errors"].append(f"图片下载失败 {resource.original_path}: {str(e)}")
                self.logger.error(f"图片下载异常: {str(e)}")

        # 处理表格资源
        for resource in table_resources:
            try:
                if resource.table_source == TableSource.MARKDOWN_TABLE:
                    # Markdown表格已在解析阶段处理，只需验证
                    self._validate_table_resource(resource)
                elif resource.table_source in [TableSource.CSV_CONTENT, TableSource.EXCEL_CONTENT]:
                    # Excel/CSV文件需要下载和解析
                    self._download_and_parse_table_file(resource)
                    self._validate_table_resource(resource)
                stats["tables_processed"] += 1
            except Exception as e:
                stats["errors"].append(f"表格处理失败 {resource.file_name}: {str(e)}")
                self.logger.error(f"表格处理异常: {str(e)}")

        self.logger.info(
            f"资源下载完成: 成功 {stats['images_success']}, 失败 {stats['images_failed']}, 表格 {stats['tables_processed']}"
        )

        return stats

    def _download_image_resource(self, resource: ResourceData):
        """下载单个图片资源"""
        if resource.image_source == ImageSource.LOCAL_FILE:
            self._handle_smart_local_download(resource)
        elif resource.image_source == ImageSource.HTTP_URL:
            self._handle_http_download(resource)
        elif resource.image_source == ImageSource.MARKDOWN_REF:
            # Markdown引用需要根据路径类型进一步判断
            self._handle_markdown_reference(resource)

    def _handle_smart_local_download(self, resource: ResourceData):
        """
        智能处理本地路径文件
        1. 优先从本地下载
        2. 如果本地没有，解析第一个目录为bucket从MinIO下载
        3. 如果都没有，返回原路径
        """
        file_path = resource.original_path

        # 步靄1: 优先尝试本地文件
        if os.path.exists(file_path):
            resource.local_path = file_path
            resource.download_success = True
            self.logger.info(f"本地图片文件存在: {file_path}")
            return

        # 步靄2: 尝试从MinIO下载（解析bucket和object名）
        self.logger.info(f"本地文件不存在，尝试从MinIO下载: {file_path}")

        # 解析路径获取bucket和object_name
        bucket_name, object_name = self._parse_path_for_minio(file_path)

        if bucket_name and object_name:
            # 尝试MinIO下载
            success = self._try_minio_download(resource, bucket_name, object_name)
            if success:
                return

        # 步靄3: 都没有下载成功，返回原路径
        resource.local_path = file_path
        resource.download_success = True  # 返回原路径也算成功
        self.logger.warning(f"图片下载失败，使用原路径: {file_path}")

    def _parse_path_for_minio(self, file_path: str) -> tuple[str, str]:
        """
        解析文件路径为MinIO的bucket和object_name
        支持特殊路径的正确映射

        规则:
        - "/bisheng/xxx" -> bucket="bisheng", object_name="xxx"  
        - "/tmp-dir/xxx" -> bucket="tmp-dir", object_name="xxx"
        - "/tmp/xxx" -> 优先尝试 bucket="bisheng", object_name="tmp/xxx"，然后尝试 bucket="tmp-dir", object_name="xxx"
        - "images/photo.jpg" -> bucket="images", object_name="photo.jpg"
        """
        if not file_path:
            return None, None

        # 特殊路径处理
        if file_path.startswith("/bisheng/"):
            # /bisheng/object/name -> bucket="bisheng", object_name="object/name"
            object_name = file_path[9:]  # 移除 '/bisheng/'
            return "bisheng", object_name if object_name else None
        
        elif file_path.startswith("/tmp-dir/"):
            # /tmp-dir/object/name -> bucket="tmp-dir", object_name="object/name"  
            object_name = file_path[9:]  # 移除 '/tmp-dir/'
            return "tmp-dir", object_name if object_name else None
        
        elif file_path.startswith("/tmp/"):
            # /tmp/xxx -> 返回多个可能的bucket选项，调用方需要都尝试
            # 这里先返回主bucket映射，调用方应该实现多bucket尝试逻辑
            object_name = file_path[5:]  # 移除 '/tmp/'
            return "tmp-dir", object_name if object_name else None

        # 通用路径解析（保持原有逻辑）
        clean_path = file_path.lstrip("/")
        if not clean_path or "/" not in clean_path:
            # 如果没有目录分隔，不能解析
            return None, None

        # 分离第一个目录和剩余路径
        parts = clean_path.split("/", 1)
        if len(parts) == 2:
            bucket_name = parts[0]
            object_name = parts[1]

            # 验证bucket名是否合法（简单检查）
            if bucket_name and object_name and bucket_name.replace("_", "").replace("-", "").isalnum():
                return bucket_name, object_name

        return None, None

    def _try_minio_download(self, resource: ResourceData, bucket_name: str, object_name: str) -> bool:
        """
        尝试从MinIO下载文件

        Returns:
            bool: 是否下载成功
        """
        try:
            # 检查文件是否存在
            if not self.minio_client.object_exists_sync(bucket_name, object_name):
                self.logger.debug(f"MinIO文件不存在: {bucket_name}/{object_name}")
                return False

            # 下载文件内容
            file_content = self.minio_client.get_object_sync(bucket_name, object_name)

            # 生成临时文件名
            file_ext = os.path.splitext(object_name)[1] or ".dat"
            filename = f"{uuid4().hex}{file_ext}"
            temp_dir = tempfile.gettempdir()
            temp_file = os.path.join(temp_dir, filename)

            # 保存到临时文件
            with open(temp_file, "wb") as f:
                f.write(file_content)

            # 更新资源信息
            resource.local_path = temp_file
            resource.download_success = True
            self.temp_files.append(temp_file)

            self.logger.info(f"MinIO下载成功: {bucket_name}/{object_name} -> {temp_file}")
            return True

        except Exception as e:
            self.logger.debug(f"从MinIO下载失败 {bucket_name}/{object_name}: {str(e)}")
            return False

    def _handle_http_download(self, resource: ResourceData):
        """处理HTTP下载"""
        try:
            local_path, success = self._download_file_from_url(resource.original_path)
            resource.local_path = local_path
            resource.download_success = success

            if success:
                self.temp_files.append(local_path)
                self.logger.info(f"HTTP图片下载成功: {resource.original_path} -> {local_path}")
            else:
                self.logger.warning(f"HTTP图片下载失败，使用原路径: {resource.original_path}")

        except Exception as e:
            resource.local_path = resource.original_path
            resource.download_success = True  # 返回原路径也算成功
            self.logger.warning(f"HTTP图片下载失败，使用原路径: {resource.original_path} (错误: {str(e)})")

    def _handle_markdown_reference(self, resource: ResourceData):
        """处理Markdown引用（需要判断具体类型）"""
        img_path = resource.original_path

        if self._is_valid_url(img_path):
            resource.image_source = ImageSource.HTTP_URL
            self._handle_http_download(resource)
        else:
            # 所有非HTTP URL的路径都走智能本地下载pipeline
            resource.image_source = ImageSource.LOCAL_FILE
            self._handle_smart_local_download(resource)

    def _download_and_parse_table_file(self, resource: ResourceData):
        """下载并解析Excel/CSV文件"""
        file_path = resource.original_path
        
        # 1. 先尝试下载文件
        local_file_path = self._download_table_file(file_path)
        
        if not local_file_path:
            raise Exception(f"无法下载表格文件: {file_path}")
        
        # 2. 根据文件类型解析
        try:
            if resource.table_source == TableSource.CSV_CONTENT:
                resource.table_data, resource.alignments = self._parse_csv_file(local_file_path)
            elif resource.table_source == TableSource.EXCEL_CONTENT:
                resource.table_data, resource.alignments = self._parse_excel_file(local_file_path)
            
            # 设置下载路径
            resource.local_path = local_file_path
            resource.download_success = True
            self.logger.info(f"表格文件解析成功: {file_path} -> {len(resource.table_data)}行")
            
        except Exception as e:
            self.logger.error(f"表格文件解析失败: {file_path}, 错误: {str(e)}")
            # 创建错误表格
            resource.table_data = [["文件解析失败", str(e)]]
            resource.alignments = ["left", "left"]
            resource.local_path = local_file_path if local_file_path else file_path  # 确保有路径
            resource.download_success = False
            
    def _download_table_file(self, file_path: str) -> Optional[str]:
        """下载表格文件到本地临时文件"""
        # 1. 优先尝试本地文件
        if os.path.exists(file_path):
            self.logger.info(f"本地表格文件存在: {file_path}")
            return file_path
        
        # 2. 尝试HTTP下载
        if self._is_valid_url(file_path):
            try:
                temp_file, success = self._download_file_from_url(file_path)
                if success and temp_file:
                    self.temp_files.append(temp_file)
                    self.logger.info(f"HTTP表格文件下载成功: {file_path} -> {temp_file}")
                    return temp_file
            except Exception as e:
                self.logger.warning(f"HTTP表格文件下载失败: {file_path}, 错误: {str(e)}")
        
        # 3. 尝试从MinIO下载
        bucket_name, object_name = self._parse_path_for_minio(file_path)
        if bucket_name and object_name:
            try:
                if self.minio_client.object_exists_sync(bucket_name, object_name):
                    file_content = self.minio_client.get_object_sync(bucket_name, object_name)
                    
                    # 生成临时文件
                    file_ext = os.path.splitext(object_name)[1] or ".dat"
                    filename = f"{uuid4().hex}{file_ext}"
                    temp_dir = tempfile.gettempdir()
                    temp_file = os.path.join(temp_dir, filename)
                    
                    with open(temp_file, "wb") as f:
                        f.write(file_content)
                    
                    self.temp_files.append(temp_file)
                    self.logger.info(f"MinIO表格文件下载成功: {bucket_name}/{object_name} -> {temp_file}")
                    return temp_file
            except Exception as e:
                self.logger.warning(f"MinIO表格文件下载失败: {file_path}, 错误: {str(e)}")
        
        # 4. 都没有下载成功
        self.logger.warning(f"表格文件下载失败: {file_path}")
        return None
    
    def _parse_csv_file(self, file_path: str) -> Tuple[List[List[str]], List[str]]:
        """解析CSV文件"""
        try:
            # 自动检测编码
            with open(file_path, 'rb') as f:
                raw_data = f.read()
                encoding_info = detect(raw_data)
                encoding = encoding_info['encoding'] or 'utf-8'
            
            # 使用pandas读取CSV，更好地处理各种格式
            df = pd.read_csv(file_path, encoding=encoding)
            
            # 转换为表格数据格式
            table_data = []
            
            # 添加表头
            headers = [str(col) for col in df.columns]
            table_data.append(headers)
            
            # 添加数据行
            for _, row in df.iterrows():
                row_data = [str(cell) if pd.notna(cell) else "" for cell in row]
                table_data.append(row_data)
            
            # 生成对齐信息（默认左对齐）
            alignments = ["left"] * len(headers)
            
            self.logger.info(f"CSV文件解析成功: {len(table_data)}行 x {len(headers)}列")
            return table_data, alignments
            
        except Exception as e:
            self.logger.error(f"CSV文件解析失败: {file_path}, 错误: {str(e)}")
            raise
    
    def _parse_excel_file(self, file_path: str) -> Tuple[List[List[str]], List[str]]:
        """解析Excel文件"""
        try:
            # 使用openpyxl读取Excel文件
            workbook = load_workbook(file_path, data_only=True)  # data_only=True获取计算后的值
            
            # 使用第一个工作表
            worksheet = workbook.active
            
            table_data = []
            max_col = 0
            
            # 读取所有行
            for row in worksheet.iter_rows(values_only=True):
                # 跳过完全空白的行
                if all(cell is None or str(cell).strip() == "" for cell in row):
                    continue
                    
                row_data = [str(cell) if cell is not None else "" for cell in row]
                table_data.append(row_data)
                max_col = max(max_col, len(row_data))
            
            # 确保所有行的列数一致
            for row in table_data:
                while len(row) < max_col:
                    row.append("")
            
            # 生成对齐信息（默认左对齐）
            alignments = ["left"] * max_col
            
            self.logger.info(f"Excel文件解析成功: {len(table_data)}行 x {max_col}列")
            
            return table_data, alignments
            
        except Exception as e:
            self.logger.error(f"Excel文件解析失败: {file_path}, 错误: {str(e)}")
            raise

    def _validate_table_resource(self, resource: ResourceData):
        """验证表格资源"""
        # 允许空表格存在，不再抛出"表格数据为空"错误
        if not resource.table_data:
            resource.table_data = []  # 确保table_data是空列表而不是None

        # 验证表格数据一致性
        if len(resource.table_data) > 0:
            col_count = len(resource.table_data[0])
            for i, row in enumerate(resource.table_data):
                if len(row) != col_count:
                    self.logger.warning(f"表格第 {i+1} 行列数不一致，将补齐空值")
                    while len(row) < col_count:
                        row.append("")

        # 验证对齐信息
        if resource.alignments and resource.table_data:
            expected_cols = len(resource.table_data[0]) if resource.table_data else 0
            while len(resource.alignments) < expected_cols:
                resource.alignments.append("left")

    def _download_file_from_url(self, url: str) -> Tuple[str, bool]:
        """从 URL 下载文件"""
        try:
            # 设置请求头，模拟浏览器访问
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }

            response = requests.get(url, headers=headers, timeout=30, verify=False)
            response.raise_for_status()

            # 获取文件名
            content_disposition = response.headers.get("Content-Disposition", "")
            filename = ""
            if content_disposition:
                filename = unquote(content_disposition).split("filename=")[-1].strip("\"'")
            if not filename:
                filename = unquote(urlparse(url).path.split("/")[-1])
            if not filename:
                # 根据Content-Type推断扩展名
                content_type = response.headers.get("Content-Type", "").lower()
                if "image/png" in content_type:
                    filename = f"{uuid4().hex}.png"
                elif "image/jpeg" in content_type or "image/jpg" in content_type:
                    filename = f"{uuid4().hex}.jpg"
                elif "image/bmp" in content_type:
                    filename = f"{uuid4().hex}.bmp"
                else:
                    filename = f"{uuid4().hex}.dat"

            # 创建临时文件
            temp_dir = tempfile.gettempdir()
            temp_file = os.path.join(temp_dir, filename)

            with open(temp_file, "wb") as f:
                f.write(response.content)

            return temp_file, True

        except Exception as e:
            self.logger.error(f"下载文件失败: {url}, 错误: {str(e)}")
            return "", False

    def _download_file_from_minio(self, minio_path: str) -> Tuple[str, bool]:
        """从MinIO下载文件"""
        try:
            # 解析MinIO路径
            bucket_name = None
            object_name = None

            if minio_path.startswith("minio://"):
                # 格式: minio://bucket/object/name
                parts = minio_path[8:].split("/", 1)
                if len(parts) == 2:
                    bucket_name, object_name = parts
                else:
                    object_name = parts[0]
                    bucket_name = self.minio_client.bucket  # 默认bucket
            elif minio_path.startswith("/bisheng/"):
                # 格式: /bisheng/object/name
                bucket_name = self.minio_client.bucket
                object_name = minio_path[9:]  # 移除 '/bisheng/'
            elif minio_path.startswith("/tmp-dir/"):
                # 格式: /tmp-dir/object/name
                bucket_name = self.minio_client.tmp_bucket
                object_name = minio_path[9:]  # 移除 '/tmp-dir/'
            elif minio_path.startswith("/tmp/"):
                # 格式: /tmp/object/name -> 智能bucket选择
                object_name = minio_path[5:]  # 移除 '/tmp/'
                
                # 先尝试主bucket
                bucket_name = self.minio_client.bucket
                if self.minio_client.object_exists_sync(bucket_name, object_name):
                    self.logger.debug(f"在主bucket找到文件: {bucket_name}/{object_name}")
                else:
                    # 主bucket没有，尝试tmp_bucket
                    bucket_name = self.minio_client.tmp_bucket
                    if self.minio_client.object_exists_sync(bucket_name, object_name):
                        self.logger.debug(f"在tmp_bucket找到文件: {bucket_name}/{object_name}")
                    else:
                        self.logger.warning(f"两个bucket都没找到文件: {object_name}")
            else:
                # 尝试作为完整URL处理
                if self._is_valid_url(minio_path):
                    return self._download_file_from_url(minio_path)
                else:
                    self.logger.error(f"无法解析MinIO路径: {minio_path}")
                    return "", False

            # 检查文件是否存在
            if not self.minio_client.object_exists_sync(bucket_name, object_name):
                self.logger.error(f"MinIO文件不存在: {bucket_name}/{object_name}")
                return "", False

            # 下载文件内容
            file_content = self.minio_client.get_object_sync(bucket_name, object_name)

            # 生成临时文件名
            file_ext = os.path.splitext(object_name)[1] or ".dat"
            filename = f"{uuid4().hex}{file_ext}"
            temp_dir = tempfile.gettempdir()
            temp_file = os.path.join(temp_dir, filename)

            # 保存到临时文件
            with open(temp_file, "wb") as f:
                f.write(file_content)

            return temp_file, True

        except Exception as e:
            self.logger.error(f"从MinIO下载文件失败: {minio_path}, 错误: {str(e)}")
            return "", False

    def _is_valid_url(self, url: str) -> bool:
        """检查是否为有效的URL"""
        try:
            result = urlparse(url)
            return all([result.scheme, result.netloc])
        except ValueError:
            return False

    def _is_minio_path(self, path: str) -> bool:
        """检查是否为明确的MinIO专用路径"""
        # 只有明确的MinIO专用路径才直接走MinIO下载
        # 其他路径（包括/tmp/）都走智能本地下载pipeline
        return path.startswith(("minio://", "/bisheng/", "/tmp-dir/"))

    def cleanup(self):
        """清理临时文件"""
        for temp_file in self.temp_files:
            try:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
                    self.logger.debug(f"清理临时文件: {temp_file}")
            except Exception as e:
                self.logger.warning(f"清理临时文件失败 {temp_file}: {str(e)}")

        self.temp_files.clear()


class SmartDocumentRenderer:
    """智能文档渲染器"""

    def __init__(self, template_content: bytes):
        self.template_content = template_content
        self.logger = logger

    def render(self, variables: Dict[str, str], resources: List[ResourceData]) -> bytes:
        """
        渲染最终文档

        Args:
            variables: 处理后的变量字典（包含占位符）
            resources: 所有资源列表

        Returns:
            渲染后的文档字节流
        """
        self.logger.info(f"开始渲染文档，变量 {len(variables)} 个，资源 {len(resources)} 个")

        # 1. 初始化DocxTemplateRender
        docx_renderer = DocxTemplateRender(file_content=io.BytesIO(self.template_content))

        # 2. 第一步：变量替换（包含占位符）
        template_def = [[f"{{{{{key}}}}}", value] for key, value in variables.items()]

        # 3. 构建资源映射（按类型分组）
        resource_map = self._build_resource_map(resources)

        # 4. 调用DocxTemplateRender进行渲染
        output_doc = docx_renderer.render(template_def, resource_map)

        # 5. 转换为字节流
        output_content = io.BytesIO()
        output_doc.save(output_content)
        output_content.seek(0)

        self.logger.info("文档渲染完成")

        return output_content.read()

    def _build_resource_map(self, resources: List[ResourceData]) -> Dict[str, List[Dict]]:
        """构建资源映射，适配DocxTemplateRender的格式"""
        resource_map = {"images": [], "excel_files": [], "csv_files": [], "markdown_tables": []}

        for resource in resources:
            if resource.resource_type == ResourceType.IMAGE:
                image_info = {
                    "placeholder": resource.placeholder,
                    "local_path": resource.local_path if resource.download_success else resource.original_path,
                    "alt_text": resource.alt_text,
                    "original_path": resource.original_path,
                    "type": "downloaded" if resource.download_success else "failed",
                    "original_text": resource.original_content,
                }
                resource_map["images"].append(image_info)

            elif resource.resource_type == ResourceType.TABLE:
                if resource.table_source == TableSource.MARKDOWN_TABLE:
                    # Markdown表格放在csv_files中处理
                    table_info = {
                        "placeholder": resource.placeholder,
                        "table_data": resource.table_data,
                        "alignments": resource.alignments,
                        "file_name": resource.file_name,
                        "type": "markdown_table",  # 修复：使用正确的类型标识符
                    }
                    resource_map["csv_files"].append(table_info)
                
                elif resource.table_source == TableSource.CSV_CONTENT:
                    # CSV文件
                    table_info = {
                        "placeholder": resource.placeholder,
                        "table_data": resource.table_data,
                        "alignments": resource.alignments,
                        "file_name": resource.file_name,
                        "type": "csv",  # 修复：使用正确的类型标识符
                        # 添加兼容性字段
                        "local_path": getattr(resource, 'local_path', resource.original_path),  # 使用下载的本地路径或原始路径
                    }
                    resource_map["csv_files"].append(table_info)

                elif resource.table_source == TableSource.EXCEL_CONTENT:
                    # Excel文件
                    table_info = {
                        "placeholder": resource.placeholder,
                        "table_data": resource.table_data,
                        "alignments": resource.alignments,
                        "file_name": resource.file_name,
                        "type": "excel",  # 修复：使用正确的类型标识符
                        # 添加docx_temp.py期望的字段
                        "local_path": getattr(resource, 'local_path', resource.original_path),  # 使用下载的本地路径或原始路径
                    }
                    
                    resource_map["excel_files"].append(table_info)

        # 记录资源统计
        self.logger.info(
            f"资源映射构建完成: 图片 {len(resource_map['images'])}, "
            f"CSV {len(resource_map['csv_files'])}, Excel {len(resource_map['excel_files'])}"
        )

        return resource_map


class ReportNode(BaseNode):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._report_info = self.node_params["report_info"]
        self._version_key = self._report_info["version_key"].split("_")[0]
        self._object_name = f"workflow/report/{self._version_key}.docx"
        self._file_name = self._report_info["file_name"] if self._report_info["file_name"] else "tmp_report.docx"
        if not self._file_name.endswith(".docx"):
            self._file_name += ".docx"
        self._minio_client = get_minio_storage_sync()

    def _run(self, unique_id: str):
        """主执行流程"""
        download_manager = None

        try:
            # 1. 下载模板文件
            logger.info("=== 步遄1: 下载报告模板 ===")
            template_content = self._download_template()

            # 2. 解析模板变量
            logger.info("=== 步遄2: 解析模板变量 ===")
            template_variables = self._extract_template_variables(template_content)

            # 3. 获取工作流变量
            logger.info("=== 步遄3: 获取工作流变量 ===")
            workflow_variables = self._get_filtered_workflow_variables(template_variables)

            # 4. 解析所有变量内容
            logger.info("=== 步遄4: 解析变量内容 ===")
            content_parser = ContentParser(self._minio_client)
            processed_variables = {}
            all_resources = []

            for var_name, var_value in workflow_variables.items():
                # 添加详细的变量值日志
                logger.info(f"[变量解析] 变量名: '{var_name}'")
                logger.info(f"[变量解析] 变量类型: {type(var_value).__name__}")
                logger.info(f"[变量解析] 变量值长度: {len(str(var_value)) if var_value is not None else 0}")
                
                # 打印变量值内容（截取前500字符避免日志过长）
                if var_value is not None:
                    var_value_str = str(var_value)
                    if len(var_value_str) > 500:
                        logger.info(f"[变量解析] 变量值内容（前500字符）: {var_value_str[:500]}...")
                    else:
                        logger.info(f"[变量解析] 变量值内容: {var_value_str}")
                else:
                    logger.info(f"[变量解析] 变量值内容: None")
                
                processed_content, resources = content_parser.parse_variable_content(var_name, var_value)
                processed_variables[var_name] = processed_content
                all_resources.extend(resources)
                
                # 添加解析结果日志
                logger.info(f"[变量解析] 解析后内容长度: {len(processed_content) if processed_content else 0}")
                logger.info(f"[变量解析] 识别资源数量: {len(resources)}")
                if resources:
                    for i, resource in enumerate(resources):
                        logger.info(f"[变量解析] 资源{i+1}: {resource.resource_type.value}, 占位符: {resource.placeholder}")
                logger.info(f"[变量解析] --- 变量 '{var_name}' 解析完成 ---")

            # 5. 下载所有资源
            logger.info("=== 步遄5: 下载资源文件 ===")
            download_manager = ResourceDownloadManager(self._minio_client)
            download_stats = download_manager.download_all_resources(all_resources)

            self._log_download_stats(download_stats)

            # 6. 渲染文档
            logger.info("=== 步遄6: 渲染Word文档 ===")
            renderer = SmartDocumentRenderer(template_content)
            final_document = renderer.render(processed_variables, all_resources)

            # 7. 保存并分享
            logger.info("=== 步遄7: 保存并分享文档 ===")
            share_url = self._save_and_share_document(final_document)

            # 8. 发送输出消息
            self._send_output_message(unique_id, share_url)

            logger.info("=== 报告生成完成 ===")

        except Exception as e:
            logger.error(f"报告生成失败: {str(e)}")
            self._send_error_message(unique_id, str(e))
            raise

        finally:
            # 临时禁用清理，避免图片文件被删除影响Word文档显示
            # if download_manager:
            #     download_manager.cleanup()
            pass

    def _download_template(self) -> bytes:
        """下载模板文件"""
        if not self._minio_client.object_exists_sync(self._minio_client.bucket, self._object_name):
            raise Exception(f"模板文件不存在: {self._object_name}")

        template_content = self._minio_client.get_object_sync(self._minio_client.bucket, self._object_name)
        logger.info(f"模板下载成功，大小: {len(template_content)} 字节")

        return template_content

    def _get_filtered_workflow_variables(self, template_variables: set) -> Dict[str, Any]:
        """获取过滤后的工作流变量"""
        all_variables = self.graph_state.get_all_variables()

        # 添加详细的变量信息日志
        logger.info(f"[工作流变量] 总数: {len(all_variables)}")
        logger.info(f"[工作流变量] 所有变量名: {list(all_variables.keys())}")
        
        # 显示每个变量的基本信息
        for var_name, var_value in all_variables.items():
            var_type = type(var_value).__name__
            var_length = len(str(var_value)) if var_value is not None else 0
            logger.info(f"[工作流变量] '{var_name}': {var_type}, 长度={var_length}")

        # 只保留模板中实际使用的变量
        filtered_variables = {k: v for k, v in all_variables.items() if k in template_variables}

        logger.info(f"[工作流变量] 模板需要的变量: {list(template_variables)}")
        logger.info(f"[工作流变量] 过滤后变量数: {len(filtered_variables)}")
        logger.info(f"[工作流变量] 过滤后变量名: {list(filtered_variables.keys())}")

        # 记录被过滤掉的变量（调试用）
        excluded_vars = set(all_variables.keys()) - set(filtered_variables.keys())
        if excluded_vars:
            logger.info(f"[工作流变量] 被过滤的变量: {list(excluded_vars)}")

        return filtered_variables

    def _log_download_stats(self, stats: Dict[str, Any]):
        """记录下载统计信息"""
        logger.info("资源下载统计:")
        logger.info(f"  - 图片成功: {stats['images_success']}")
        logger.info(f"  - 图片失败: {stats['images_failed']}")
        logger.info(f"  - 表格处理: {stats['tables_processed']}")

        if stats.get("errors"):
            logger.warning("下载错误详情:")
            for error in stats["errors"]:
                logger.warning(f"  - {error}")

    def _save_and_share_document(self, document_content: bytes) -> str:
        """保存文档并获取分享链接"""
        # 生成唯一的文件路径
        tmp_object_name = f"workflow/report/{uuid4().hex}/{self._file_name}"

        # 上传到MinIO
        self._minio_client.put_object_tmp_sync(tmp_object_name, document_content)

        # 获取分享链接
        share_url = self._minio_client.get_share_link(tmp_object_name, self._minio_client.tmp_bucket)

        logger.info(f"文档保存成功: {tmp_object_name}")
        logger.info(f"分享链接: {share_url}")

        return share_url

    def _send_output_message(self, unique_id: str, share_url: str):
        """发送输出消息"""
        self.callback_manager.on_output_msg(
            OutputMsgData(
                unique_id=unique_id,
                node_id=self.id,
                name=self.name,
                msg="",
                files=[{"path": share_url, "name": self._file_name}],
                output_key="",
            )
        )

    def _send_error_message(self, unique_id: str, error_msg: str):
        """发送错误消息"""
        self.callback_manager.on_output_msg(
            OutputMsgData(
                unique_id=unique_id,
                node_id=self.id,
                name=self.name,
                msg=f"报告生成失败: {error_msg}",
                files=[],
                output_key="",
            )
        )

    # 保留必要的辅助方法
    def _get_unique_placeholder_id(self) -> int:
        """保留的旧方法，用于兼容性"""
        return 0  # 新系统中不再使用

    def _extract_template_variables(self, file_content: bytes) -> set:
        """
        从Word模板文件中提取所有的变量占位符

        Args:
            file_content: Word文件的二进制内容

        Returns:
            set: 模板中引用的变量名集合
        """
        import zipfile
        import re

        try:
            # Word文档是一个zip文件，解析其中的XML内容
            template_variables = set()

            with zipfile.ZipFile(io.BytesIO(file_content), "r") as docx_zip:
                # 解析主文档部分
                if "word/document.xml" in docx_zip.namelist():
                    doc_xml = docx_zip.read("word/document.xml").decode("utf-8")

                    # 使用正则表达式查找所有 {{变量名}} 格式的占位符
                    pattern = r"\{\{([^}]+)\}\}"
                    matches = re.findall(pattern, doc_xml)

                    # 处理Word可能将变量拆分到多个XML标签的情况
                    # 先移除所有XML标签，再进行匹配
                    clean_xml = re.sub(r"<[^>]+>", "", doc_xml)
                    clean_matches = re.findall(pattern, clean_xml)

                    # 合并两种匹配结果
                    all_matches = list(set(matches + clean_matches))

                    # 添加详细调试日志
                    logger.warning(f"原始XML匹配结果: {matches}")
                    logger.warning(f"清理XML后匹配结果: {clean_matches}")
                    logger.warning(f"合并后的匹配结果: {all_matches}")

                    for match in all_matches:
                        # 清理变量名（去除空格等）
                        var_name = match.strip()
                        if var_name:
                            template_variables.add(var_name)
                            logger.debug(f"发现模板变量: {var_name}")

                # 也检查页眉页脚等部分
                for xml_part in ["word/header1.xml", "word/footer1.xml"]:
                    if xml_part in docx_zip.namelist():
                        xml_content = docx_zip.read(xml_part).decode("utf-8")
                        matches = re.findall(r"\{\{([^}]+)\}\}", xml_content)
                        for match in matches:
                            var_name = match.strip()
                            if var_name:
                                template_variables.add(var_name)
                                logger.debug(f"发现模板变量(页眉/页脚): {var_name}")

            logger.info(f"[模板解析] 提取到 {len(template_variables)} 个变量: {list(template_variables)}")
            for i, var_name in enumerate(sorted(template_variables), 1):
                logger.info(f"[模板解析] 变量{i}: '{var_name}'")
            return template_variables

        except Exception as e:
            logger.error(f"解析模板变量失败: {e}")
            # 如果解析失败，返回空集合，这样就不会过滤任何变量
            return set()
