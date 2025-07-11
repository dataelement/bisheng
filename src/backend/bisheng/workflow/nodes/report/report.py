import io
import re
import os
import tempfile
import requests
from urllib.parse import urlparse, unquote
from pathlib import Path
from uuid import uuid4
from loguru import logger
from typing import Dict, List, Tuple, Any

from bisheng.utils.minio_client import MinioClient
from bisheng.utils.docx_temp import DocxTemplateRender
from bisheng.workflow.callback.event import OutputMsgData
from bisheng.workflow.nodes.base import BaseNode


class ReportNode(BaseNode):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._report_info = self.node_params['report_info']
        self._version_key = self._report_info['version_key'].split('_')[0]
        self._object_name = f"workflow/report/{self._version_key}.docx"
        self._file_name = self._report_info['file_name'] if self._report_info['file_name'] else 'tmp_report.docx'
        if not self._file_name.endswith('.docx'):
            self._file_name += '.docx'
        self._minio_client = MinioClient()
        # 存储下载的文件信息，用于后续插入文档
        self._downloaded_files: Dict[str, str] = {}

    def _is_valid_url(self, url: str) -> bool:
        """检查是否为有效的URL"""
        try:
            result = urlparse(url)
            return all([result.scheme, result.netloc])
        except ValueError:
            return False

    def _download_file(self, url: str) -> Tuple[str, bool]:
        """
        下载文件到临时目录
        
        Args:
            url: 文件URL
            
        Returns:
            tuple: (本地文件路径, 是否下载成功)
        """
        try:
            # 设置请求头，模拟浏览器访问
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            
            response = requests.get(url, headers=headers, timeout=30, verify=False)
            response.raise_for_status()
            
            # 获取文件名
            content_disposition = response.headers.get('Content-Disposition', '')
            filename = ''
            if content_disposition:
                filename = unquote(content_disposition).split('filename=')[-1].strip("\"'")
            if not filename:
                filename = unquote(urlparse(url).path.split('/')[-1])
            if not filename:
                # 根据Content-Type推断扩展名
                content_type = response.headers.get('Content-Type', '').lower()
                if 'image/png' in content_type:
                    filename = f"{uuid4().hex}.png"
                elif 'image/jpeg' in content_type or 'image/jpg' in content_type:
                    filename = f"{uuid4().hex}.jpg"
                elif 'image/bmp' in content_type:
                    filename = f"{uuid4().hex}.bmp"
                elif 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' in content_type:
                    filename = f"{uuid4().hex}.xlsx"
                elif 'application/vnd.ms-excel' in content_type:
                    filename = f"{uuid4().hex}.xls"
                else:
                    filename = f"{uuid4().hex}.dat"
            
            # 创建临时文件
            temp_dir = tempfile.gettempdir()
            temp_file = os.path.join(temp_dir, filename)
            
            with open(temp_file, 'wb') as f:
                f.write(response.content)
            
            logger.info(f"成功下载文件: {url} -> {temp_file}")
            return temp_file, True
            
        except Exception as e:
            logger.error(f"下载文件失败: {url}, 错误: {str(e)}")
            return "", False

    def _extract_and_download_resources(self, value: str) -> Tuple[str, Dict[str, Any]]:
        """
        从变量值中提取并下载资源文件
        
        Args:
            value: 原始变量值
            
        Returns:
            tuple: (处理后的变量值, 资源信息字典)
        """
        if not isinstance(value, str):
            return str(value), {}
        
        # 定义正则表达式模式
        patterns = {
            # 图片模式 - 按优先级排序
            'markdown_image': r'!\[([^\]]*)\]\(([^)]+\.(?:png|jpg|jpeg|bmp))\)',  # Markdown格式图片
            'local_image': r'(?:^|[\s\n])([^\s\n]*\.(?:png|jpg|jpeg|bmp))(?=[\s\n]|$)',  # 本地路径图片
            'minio_image': r'(?:^|[\s\n])(minio://[^\s\n]*\.(?:png|jpg|jpeg|bmp))(?=[\s\n]|$)',  # MinIO路径图片
            'http_image': r'(?:^|[\s\n])(https?://[^\s\n]*\.(?:png|jpg|jpeg|bmp))(?=[\s\n]|$)',  # HTTP/HTTPS图片
            
            # 表格模式
            'excel_file': r'(?:^|[\s\n])([^\s\n]*\.(?:xls|xlsx))(?=[\s\n]|$)',  # Excel文件
            'markdown_table': r'(\|[^|\n]*\|(?:\n\|[^|\n]*\|)*)',  # Markdown表格
        }
        
        processed_value = value
        resources = {
            'images': [],
            'excel_files': [],
            'markdown_tables': []
        }
        
        # 1. 处理图片 - 本地路径优先
        # 1.1 Markdown格式图片（本地）
        markdown_images = re.findall(patterns['markdown_image'], processed_value, re.IGNORECASE)
        for alt_text, img_path in markdown_images:
            if not self._is_valid_url(img_path):  # 本地路径
                if os.path.exists(img_path):
                    # 本地文件存在，记录到资源列表
                    placeholder = f"__IMAGE_PLACEHOLDER_{len(resources['images'])}__"
                    resources['images'].append({
                        'original_path': img_path,
                        'local_path': img_path,
                        'alt_text': alt_text,
                        'placeholder': placeholder,
                        'type': 'local'
                    })
                    # 在文档中用占位符替换
                    processed_value = processed_value.replace(f"![{alt_text}]({img_path})", placeholder)
                    logger.info(f"识别到本地图片: {img_path}")
                else:
                    logger.warning(f"本地图片文件不存在: {img_path}")
        
        # 1.2 本地路径图片（非Markdown格式）
        local_images = re.findall(patterns['local_image'], processed_value, re.IGNORECASE)
        for img_path in local_images:
            if not self._is_valid_url(img_path) and not img_path.startswith('minio://'):
                # 避免重复处理已经在Markdown中的图片
                if not any(img['original_path'] == img_path for img in resources['images']):
                    if os.path.exists(img_path):
                        placeholder = f"__IMAGE_PLACEHOLDER_{len(resources['images'])}__"
                        resources['images'].append({
                            'original_path': img_path,
                            'local_path': img_path,
                            'alt_text': '图片',
                            'placeholder': placeholder,
                            'type': 'local'
                        })
                        processed_value = processed_value.replace(img_path, placeholder)
                        logger.info(f"识别到本地图片: {img_path}")
                    else:
                        logger.warning(f"本地图片文件不存在: {img_path}")
        
        # 1.3 MinIO路径图片
        minio_images = re.findall(patterns['minio_image'], processed_value, re.IGNORECASE)
        for img_path in minio_images:
            placeholder = f"__IMAGE_PLACEHOLDER_{len(resources['images'])}__"
            resources['images'].append({
                'original_path': img_path,
                'local_path': img_path,  # MinIO路径保持原样，由后续处理决定是否下载
                'alt_text': '图片',
                'placeholder': placeholder,
                'type': 'minio'
            })
            processed_value = processed_value.replace(img_path, placeholder)
            logger.info(f"识别到MinIO图片: {img_path}")
        
        # 2. 处理网络路径图片
        # 2.1 Markdown格式的网络图片
        markdown_net_images = re.findall(patterns['markdown_image'], processed_value, re.IGNORECASE)
        for alt_text, img_url in markdown_net_images:
            if self._is_valid_url(img_url):
                local_path, success = self._download_file(img_url)
                placeholder = f"__IMAGE_PLACEHOLDER_{len(resources['images'])}__"
                
                if success:
                    resources['images'].append({
                        'original_path': img_url,
                        'local_path': local_path,
                        'alt_text': alt_text,
                        'placeholder': placeholder,
                        'type': 'downloaded'
                    })
                    logger.info(f"网络图片下载成功: {img_url} -> {local_path}")
                else:
                    # 下载失败，但仍记录原URL，后续可能仍需处理
                    resources['images'].append({
                        'original_path': img_url,
                        'local_path': img_url,
                        'alt_text': alt_text,
                        'placeholder': placeholder,
                        'type': 'failed'
                    })
                    logger.warning(f"网络图片下载失败: {img_url}")
                
                processed_value = processed_value.replace(f"![{alt_text}]({img_url})", placeholder)
        
        # 2.2 直接的HTTP/HTTPS图片链接
        http_images = re.findall(patterns['http_image'], processed_value, re.IGNORECASE)
        for img_url in http_images:
            # 检查是否已经在Markdown格式中处理过
            if not any(img['original_path'] == img_url for img in resources['images']):
                local_path, success = self._download_file(img_url)
                placeholder = f"__IMAGE_PLACEHOLDER_{len(resources['images'])}__"
                
                if success:
                    resources['images'].append({
                        'original_path': img_url,
                        'local_path': local_path,
                        'alt_text': '图片',
                        'placeholder': placeholder,
                        'type': 'downloaded'
                    })
                    logger.info(f"网络图片下载成功: {img_url} -> {local_path}")
                else:
                    resources['images'].append({
                        'original_path': img_url,
                        'local_path': img_url,
                        'alt_text': '图片',
                        'placeholder': placeholder,
                        'type': 'failed'
                    })
                    logger.warning(f"网络图片下载失败: {img_url}")
                
                processed_value = processed_value.replace(img_url, placeholder)
        
        # 3. 处理Excel表格文件
        excel_files = re.findall(patterns['excel_file'], processed_value, re.IGNORECASE)
        for excel_path in excel_files:
            placeholder = f"__EXCEL_PLACEHOLDER_{len(resources['excel_files'])}__"
            
            if self._is_valid_url(excel_path):
                # 网络Excel文件
                local_path, success = self._download_file(excel_path)
                if success:
                    resources['excel_files'].append({
                        'original_path': excel_path,
                        'local_path': local_path,
                        'placeholder': placeholder,
                        'type': 'downloaded'
                    })
                    logger.info(f"Excel文件下载成功: {excel_path} -> {local_path}")
                else:
                    resources['excel_files'].append({
                        'original_path': excel_path,
                        'local_path': excel_path,
                        'placeholder': placeholder,
                        'type': 'failed'
                    })
                    logger.warning(f"Excel文件下载失败: {excel_path}")
            else:
                # 本地Excel文件
                if os.path.exists(excel_path):
                    resources['excel_files'].append({
                        'original_path': excel_path,
                        'local_path': excel_path,
                        'placeholder': placeholder,
                        'type': 'local'
                    })
                    logger.info(f"识别到本地Excel文件: {excel_path}")
                else:
                    resources['excel_files'].append({
                        'original_path': excel_path,
                        'local_path': excel_path,
                        'placeholder': placeholder,
                        'type': 'missing'
                    })
                    logger.warning(f"本地Excel文件不存在: {excel_path}")
            
            processed_value = processed_value.replace(excel_path, placeholder)
        
        # 4. 处理Markdown表格
        markdown_tables = re.findall(patterns['markdown_table'], processed_value, re.MULTILINE)
        for table_content in markdown_tables:
            placeholder = f"__TABLE_PLACEHOLDER_{len(resources['markdown_tables'])}__"
            resources['markdown_tables'].append({
                'content': table_content,
                'placeholder': placeholder,
                'type': 'markdown'
            })
            processed_value = processed_value.replace(table_content, placeholder)
            logger.info(f"识别到Markdown表格，行数: {table_content.count('|')}")
        
        return processed_value, resources

    def _run(self, unique_id: str):
        # 下载报告模板文件
        if not self._minio_client.object_exists(self._minio_client.bucket, self._object_name):
            raise Exception(f"{self.name}节点模板文件不存在，请先编辑对应的报告模板")
        file_content = self._minio_client.get_object(self._minio_client.bucket, self._object_name)
        doc_parse = DocxTemplateRender(file_content=io.BytesIO(file_content))
        
        # 获取所有的节点变量
        all_variables = self.graph_state.get_all_variables()
        template_def = []
        all_resources = {
            'images': [],
            'excel_files': [],
            'markdown_tables': []
        }
        
        # 处理每个变量值
        for key, value in all_variables.items():
            # 提取并下载资源文件
            processed_value, resources = self._extract_and_download_resources(str(value))
            
            # 合并资源信息
            all_resources['images'].extend(resources.get('images', []))
            all_resources['excel_files'].extend(resources.get('excel_files', []))
            all_resources['markdown_tables'].extend(resources.get('markdown_tables', []))
            
            template_def.append(["{{" + key + "}}", processed_value])

        # 将变量和资源信息一起渲染到docx模板文件
        output_doc = doc_parse.render(template_def, all_resources)
        output_content = io.BytesIO()
        output_doc.save(output_content)
        output_content.seek(0)

        # minio的临时目录
        tmp_object_name = f"workflow/report/{uuid4().hex}/{self._file_name}"
        # upload file to minio
        self._minio_client.upload_tmp(tmp_object_name, output_content.read())
        # get share link
        file_share_url = self._minio_client.get_share_link(tmp_object_name, self._minio_client.tmp_bucket)

        self.callback_manager.on_output_msg(OutputMsgData(**{
            'unique_id': unique_id,
            'node_id': self.id,
            'msg': "",
            'files': [{'path': file_share_url, 'name': self._file_name}],
            'output_key': '',
        }))
