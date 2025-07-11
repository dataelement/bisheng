import io
import re
import os
import tempfile
import requests
from urllib.parse import urlparse, unquote
from pathlib import Path
from uuid import uuid4
from loguru import logger

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

    def _is_valid_url(self, url: str) -> bool:
        """检查是否为有效的URL"""
        try:
            result = urlparse(url)
            return all([result.scheme, result.netloc])
        except ValueError:
            return False

    def _download_file(self, url: str) -> tuple[str, bool]:
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

    def _process_variable_value(self, value: str) -> str:
        """
        处理变量值，按照优先级匹配和下载图片、Excel文件
        
        Args:
            value: 原始变量值
            
        Returns:
            str: 处理后的变量值
        """
        if not isinstance(value, str):
            return str(value)
        
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
        
        # 1. 处理图片 - 本地路径优先
        # 1.1 Markdown格式图片（本地）
        markdown_images = re.findall(patterns['markdown_image'], processed_value, re.IGNORECASE)
        for alt_text, img_path in markdown_images:
            if not self._is_valid_url(img_path):  # 本地路径
                if os.path.exists(img_path):
                    # 本地文件存在，保持原样
                    continue
                else:
                    # 本地文件不存在，尝试作为相对路径处理
                    logger.warning(f"本地图片文件不存在: {img_path}")
        
        # 1.2 本地路径图片
        local_images = re.findall(patterns['local_image'], processed_value, re.IGNORECASE)
        for img_path in local_images:
            if not self._is_valid_url(img_path) and not img_path.startswith('minio://'):
                if os.path.exists(img_path):
                    # 转换为Markdown格式
                    processed_value = processed_value.replace(img_path, f"![图片]({img_path})")
                else:
                    logger.warning(f"本地图片文件不存在: {img_path}")
        
        # 1.3 MinIO路径图片
        minio_images = re.findall(patterns['minio_image'], processed_value, re.IGNORECASE)
        for img_path in minio_images:
            # MinIO路径保持原样或转换为Markdown格式
            if not re.search(patterns['markdown_image'], img_path):
                processed_value = processed_value.replace(img_path, f"![图片]({img_path})")
        
        # 2. 处理网络路径图片
        # 2.1 Markdown格式的网络图片
        markdown_net_images = re.findall(patterns['markdown_image'], processed_value, re.IGNORECASE)
        for alt_text, img_url in markdown_net_images:
            if self._is_valid_url(img_url):
                local_path, success = self._download_file(img_url)
                if success:
                    # 下载成功，替换为本地路径
                    old_markdown = f"![{alt_text}]({img_url})"
                    new_markdown = f"![{alt_text}]({local_path})"
                    processed_value = processed_value.replace(old_markdown, new_markdown)
                    logger.info(f"图片下载成功，已替换: {img_url} -> {local_path}")
                else:
                    logger.warning(f"图片下载失败，保持原样: {img_url}")
        
        # 2.2 直接的HTTP/HTTPS图片链接
        http_images = re.findall(patterns['http_image'], processed_value, re.IGNORECASE)
        for img_url in http_images:
            # 检查是否已经在Markdown格式中
            if not re.search(rf'!\[[^\]]*\]\({re.escape(img_url)}\)', processed_value):
                local_path, success = self._download_file(img_url)
                if success:
                    # 下载成功，替换为Markdown格式的本地路径
                    processed_value = processed_value.replace(img_url, f"![图片]({local_path})")
                    logger.info(f"图片下载成功，已替换: {img_url} -> {local_path}")
                else:
                    # 下载失败，转换为Markdown格式但保持原URL
                    processed_value = processed_value.replace(img_url, f"![图片]({img_url})")
                    logger.warning(f"图片下载失败，保持原URL: {img_url}")
        
        # 3. 处理Excel表格文件
        excel_files = re.findall(patterns['excel_file'], processed_value, re.IGNORECASE)
        for excel_path in excel_files:
            if self._is_valid_url(excel_path):
                # 网络Excel文件
                local_path, success = self._download_file(excel_path)
                if success:
                    processed_value = processed_value.replace(excel_path, local_path)
                    logger.info(f"Excel文件下载成功，已替换: {excel_path} -> {local_path}")
                else:
                    logger.warning(f"Excel文件下载失败，保持原样: {excel_path}")
            elif not os.path.exists(excel_path):
                logger.warning(f"本地Excel文件不存在: {excel_path}")
        
        # 4. 检测Markdown表格（保持原样，不需要特殊处理）
        markdown_tables = re.findall(patterns['markdown_table'], processed_value, re.MULTILINE)
        if markdown_tables:
            logger.info(f"检测到 {len(markdown_tables)} 个Markdown表格")
        
        return processed_value

    def _run(self, unique_id: str):
        # 下载报告模板文件
        if not self._minio_client.object_exists(self._minio_client.bucket, self._object_name):
            raise Exception(f"{self.name}节点模板文件不存在，请先编辑对应的报告模板")
        file_content = self._minio_client.get_object(self._minio_client.bucket, self._object_name)
        doc_parse = DocxTemplateRender(file_content=io.BytesIO(file_content))
        
        # 获取所有的节点变量
        all_variables = self.graph_state.get_all_variables()
        template_def = []
        
        # 处理每个变量值
        for key, value in all_variables.items():
            # 处理变量值（检测并下载图片、Excel文件等）
            processed_value = self._process_variable_value(str(value))
            template_def.append(["{{" + key + "}}", processed_value])

        # 将变量渲染到docx模板文件
        output_doc = doc_parse.render(template_def)
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
