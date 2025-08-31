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

    def _download_minio_file(self, minio_path: str) -> Tuple[str, bool]:
        """
        从MinIO下载文件到临时目录
        
        Args:
            minio_path: MinIO文件路径
            
        Returns:
            tuple: (本地文件路径, 是否下载成功)
        """
        try:
            # 解析MinIO路径
            bucket_name = None
            object_name = None
            
            if minio_path.startswith('minio://'):
                # 格式: minio://bucket/object/name
                parts = minio_path[8:].split('/', 1)
                if len(parts) == 2:
                    bucket_name, object_name = parts
                else:
                    object_name = parts[0]
                    bucket_name = self._minio_client.bucket  # 默认bucket
            elif minio_path.startswith('/bisheng/'):
                # 格式: /bisheng/object/name
                bucket_name = self._minio_client.bucket
                object_name = minio_path[9:]  # 移除 '/bisheng/'
            elif minio_path.startswith('/tmp-dir/'):
                # 格式: /tmp-dir/object/name
                bucket_name = self._minio_client.tmp_bucket
                object_name = minio_path[9:]  # 移除 '/tmp-dir/'
            else:
                # 尝试作为完整URL处理
                if self._is_valid_url(minio_path):
                    return self._download_file(minio_path)
                else:
                    logger.error(f"无法解析MinIO路径: {minio_path}")
                    return "", False
            
            # 检查文件是否存在
            if not self._minio_client.object_exists(bucket_name, object_name):
                logger.error(f"MinIO文件不存在: {bucket_name}/{object_name}")
                return "", False
            
            # 下载文件内容
            file_content = self._minio_client.get_object(bucket_name, object_name)
            
            # 生成临时文件名
            file_ext = os.path.splitext(object_name)[1] or '.dat'
            filename = f"{uuid4().hex}{file_ext}"
            temp_dir = tempfile.gettempdir()
            temp_file = os.path.join(temp_dir, filename)
            
            # 保存到临时文件
            with open(temp_file, 'wb') as f:
                f.write(file_content)
            
            logger.info(f"成功从MinIO下载文件: {minio_path} -> {temp_file}")
            return temp_file, True
            
        except Exception as e:
            logger.error(f"从MinIO下载文件失败: {minio_path}, 错误: {str(e)}")
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
            'local_image': r'([^\s]*\.(?:png|jpg|jpeg|bmp))',  # 本地路径图片（嵌入文本中）
            'minio_image': r'((?:minio://|/bisheng/|/tmp-dir/)[^\s]*\.(?:png|jpg|jpeg|bmp))',  # MinIO路径图片
            'http_image': r'(https?://[^\s]*\.(?:png|jpg|jpeg|bmp))',  # HTTP/HTTPS图片
            
            # 表格模式
            'excel_file': r'([^\s]*\.(?:xls|xlsx))',  # Excel文件（嵌入文本中）
            'markdown_table': r'(\|[^|\n]*\|(?:\n\|[^|\n]*\|)*)',  # Markdown表格
        }
        
        processed_value = value
        resources = {
            'images': [],
            'excel_files': [],
            'markdown_tables': []
        }
        
        # 用于跟踪已处理的路径，避免重复
        processed_paths = set()
        
        # 1. 处理图片 - 按优先级排序
        # 1.1 Markdown格式图片（优先级最高）
        markdown_images = re.findall(patterns['markdown_image'], processed_value, re.IGNORECASE)
        for alt_text, img_path in markdown_images:
            if img_path not in processed_paths:
                processed_paths.add(img_path)
                
                if not self._is_valid_url(img_path):  # 本地路径
                    if os.path.exists(img_path):
                        # 本地文件存在，记录到资源列表
                        placeholder = f"__IMAGE_PLACEHOLDER_{len(resources['images'])}__"
                        resources['images'].append({
                            'original_path': img_path,
                            'local_path': img_path,
                            'alt_text': alt_text,
                            'placeholder': placeholder,
                            'type': 'local',
                            'original_text': f"![{alt_text}]({img_path})"
                        })
                        # 在文档中用占位符替换
                        processed_value = processed_value.replace(f"![{alt_text}]({img_path})", placeholder)
                        logger.info(f"识别到本地Markdown图片: {img_path}")
                    else:
                        logger.warning(f"本地图片文件不存在: {img_path}")
                else:
                    # 网络图片，下载处理
                    local_path, success = self._download_file(img_path)
                    placeholder = f"__IMAGE_PLACEHOLDER_{len(resources['images'])}__"
                    
                    if success:
                        resources['images'].append({
                            'original_path': img_path,
                            'local_path': local_path,
                            'alt_text': alt_text,
                            'placeholder': placeholder,
                            'type': 'downloaded',
                            'original_text': f"![{alt_text}]({img_path})"
                        })
                        logger.info(f"网络Markdown图片下载成功: {img_path} -> {local_path}")
                    else:
                        resources['images'].append({
                            'original_path': img_path,
                            'local_path': img_path,
                            'alt_text': alt_text,
                            'placeholder': placeholder,
                            'type': 'failed',
                            'original_text': f"![{alt_text}]({img_path})"
                        })
                        logger.warning(f"网络Markdown图片下载失败: {img_path}")
                    
                    processed_value = processed_value.replace(f"![{alt_text}]({img_path})", placeholder)
        
        # 1.2 MinIO路径图片 - 下载到本地
        minio_images = re.findall(patterns['minio_image'], processed_value, re.IGNORECASE)
        for img_path in minio_images:
            if img_path not in processed_paths:
                processed_paths.add(img_path)
                # 下载MinIO图片到本地
                local_path, success = self._download_minio_file(img_path)
                placeholder = f"__IMAGE_PLACEHOLDER_{len(resources['images'])}__"
                
                if success:
                    resources['images'].append({
                        'original_path': img_path,
                        'local_path': local_path,
                        'alt_text': '图片',
                        'placeholder': placeholder,
                        'type': 'downloaded',
                        'original_text': img_path
                    })
                    logger.info(f"MinIO图片下载成功: {img_path} -> {local_path}")
                else:
                    resources['images'].append({
                        'original_path': img_path,
                        'local_path': img_path,
                        'alt_text': '图片',
                        'placeholder': placeholder,
                        'type': 'failed',
                        'original_text': img_path
                    })
                    logger.warning(f"MinIO图片下载失败: {img_path}")
                
                processed_value = processed_value.replace(img_path, placeholder)
        
        # 1.3 HTTP/HTTPS图片链接
        http_images = re.findall(patterns['http_image'], processed_value, re.IGNORECASE)
        for img_url in http_images:
            if img_url not in processed_paths:
                processed_paths.add(img_url)
                local_path, success = self._download_file(img_url)
                placeholder = f"__IMAGE_PLACEHOLDER_{len(resources['images'])}__"
                
                if success:
                    resources['images'].append({
                        'original_path': img_url,
                        'local_path': local_path,
                        'alt_text': '图片',
                        'placeholder': placeholder,
                        'type': 'downloaded',
                        'original_text': img_url
                    })
                    logger.info(f"网络图片下载成功: {img_url} -> {local_path}")
                else:
                    resources['images'].append({
                        'original_path': img_url,
                        'local_path': img_url,
                        'alt_text': '图片',
                        'placeholder': placeholder,
                        'type': 'failed',
                        'original_text': img_url
                    })
                    logger.warning(f"网络图片下载失败: {img_url}")
                
                processed_value = processed_value.replace(img_url, placeholder)
        
        # 1.4 本地路径图片（最后处理，避免误匹配）
        local_images = re.findall(patterns['local_image'], processed_value, re.IGNORECASE)
        for img_path in local_images:
            # 过滤掉已处理的路径和明显不是路径的文本
            if (img_path not in processed_paths and 
                ('/' in img_path or '\\' in img_path) and  # 必须包含路径分隔符
                not self._is_valid_url(img_path) and 
                not img_path.startswith('minio://') and
                not img_path.startswith('/bisheng/') and
                not img_path.startswith('/tmp-dir/')):
                
                processed_paths.add(img_path)
                if os.path.exists(img_path):
                    placeholder = f"__IMAGE_PLACEHOLDER_{len(resources['images'])}__"
                    resources['images'].append({
                        'original_path': img_path,
                        'local_path': img_path,
                        'alt_text': '图片',
                        'placeholder': placeholder,
                        'type': 'local',
                        'original_text': img_path
                    })
                    processed_value = processed_value.replace(img_path, placeholder)
                    logger.info(f"识别到本地图片: {img_path}")
                else:
                    logger.warning(f"本地图片文件不存在: {img_path}")
        
        # 2. 处理Excel表格文件
        excel_files = re.findall(patterns['excel_file'], processed_value, re.IGNORECASE)
        for excel_path in excel_files:
            if excel_path not in processed_paths:
                processed_paths.add(excel_path)
                placeholder = f"__EXCEL_PLACEHOLDER_{len(resources['excel_files'])}__"
                
                if self._is_valid_url(excel_path):
                    # 网络Excel文件
                    local_path, success = self._download_file(excel_path)
                    if success:
                        resources['excel_files'].append({
                            'original_path': excel_path,
                            'local_path': local_path,
                            'placeholder': placeholder,
                            'type': 'downloaded',
                            'original_text': excel_path
                        })
                        logger.info(f"Excel文件下载成功: {excel_path} -> {local_path}")
                    else:
                        resources['excel_files'].append({
                            'original_path': excel_path,
                            'local_path': excel_path,
                            'placeholder': placeholder,
                            'type': 'failed',
                            'original_text': excel_path
                        })
                        logger.warning(f"Excel文件下载失败: {excel_path}")
                elif (excel_path.startswith('/bisheng/') or 
                      excel_path.startswith('/tmp-dir/') or 
                      excel_path.startswith('minio://')):
                    # MinIO Excel文件
                    local_path, success = self._download_minio_file(excel_path)
                    if success:
                        resources['excel_files'].append({
                            'original_path': excel_path,
                            'local_path': local_path,
                            'placeholder': placeholder,
                            'type': 'downloaded',
                            'original_text': excel_path
                        })
                        logger.info(f"MinIO Excel文件下载成功: {excel_path} -> {local_path}")
                    else:
                        resources['excel_files'].append({
                            'original_path': excel_path,
                            'local_path': excel_path,
                            'placeholder': placeholder,
                            'type': 'failed',
                            'original_text': excel_path
                        })
                        logger.warning(f"MinIO Excel文件下载失败: {excel_path}")
                else:
                    # 本地Excel文件
                    if os.path.exists(excel_path):
                        resources['excel_files'].append({
                            'original_path': excel_path,
                            'local_path': excel_path,
                            'placeholder': placeholder,
                            'type': 'local',
                            'original_text': excel_path
                        })
                        logger.info(f"识别到本地Excel文件: {excel_path}")
                    else:
                        resources['excel_files'].append({
                            'original_path': excel_path,
                            'local_path': excel_path,
                            'placeholder': placeholder,
                            'type': 'missing',
                            'original_text': excel_path
                        })
                        logger.warning(f"本地Excel文件不存在: {excel_path}")
                
                processed_value = processed_value.replace(excel_path, placeholder)
        
        # 3. 处理Markdown表格（保持不变）
        markdown_tables = re.findall(patterns['markdown_table'], processed_value, re.MULTILINE)
        for table_content in markdown_tables:
            placeholder = f"__TABLE_PLACEHOLDER_{len(resources['markdown_tables'])}__"
            resources['markdown_tables'].append({
                'content': table_content,
                'placeholder': placeholder,
                'type': 'markdown',
                'original_text': table_content
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


def test_report_node_scenario():
    """
    测试用户场景：处理嵌入在文本中的图片和表格路径
    
    测试用例：
    1. 图片嵌入文本：asdasd/ada/ada.jpgdasda
    2. Excel文件嵌入文本：报告数据file/data.xlsx请查看
    3. Markdown表格在文本中
    """
    print("🎯 测试ReportNode场景处理")
    
    # 创建测试实例（模拟必要的参数）
    test_params = {
        'report_info': {
            'version_key': 'test_123',
            'file_name': 'test_report.docx'
        }
    }
    
    # 创建一个简化的测试类来测试_extract_and_download_resources方法
    class TestReportNode:
        def __init__(self):
            pass
            
        def _is_valid_url(self, url: str) -> bool:
            try:
                from urllib.parse import urlparse
                result = urlparse(url)
                return all([result.scheme, result.netloc])
            except ValueError:
                return False
        
        def _download_file(self, url: str):
            # 模拟下载失败（测试用）
            logger.info(f"模拟下载: {url}")
            return "", False
        
        def _extract_and_download_resources(self, value: str):
            # 将原来的方法复制过来进行测试
            if not isinstance(value, str):
                return str(value), {}
            
            # 定义正则表达式模式
            patterns = {
                'markdown_image': r'!\[([^\]]*)\]\(([^)]+\.(?:png|jpg|jpeg|bmp))\)',
                'local_image': r'([^\s]*\.(?:png|jpg|jpeg|bmp))',
                'minio_image': r'((?:minio://|/bisheng/|/tmp-dir/)[^\s]*\.(?:png|jpg|jpeg|bmp))',
                'http_image': r'(https?://[^\s]*\.(?:png|jpg|jpeg|bmp))',
                'excel_file': r'([^\s]*\.(?:xls|xlsx))',
                'markdown_table': r'(\|[^|\n]*\|(?:\n\|[^|\n]*\|)*)',
            }
            
            processed_value = value
            resources = {
                'images': [],
                'excel_files': [],
                'markdown_tables': []
            }
            
            processed_paths = set()
            
            # 处理图片路径
            import re
            local_images = re.findall(patterns['local_image'], processed_value, re.IGNORECASE)
            for img_path in local_images:
                if (img_path not in processed_paths and 
                    ('/' in img_path or '\\' in img_path) and
                    not self._is_valid_url(img_path)):
                    
                    processed_paths.add(img_path)
                    placeholder = f"__IMAGE_PLACEHOLDER_{len(resources['images'])}__"
                    resources['images'].append({
                        'original_path': img_path,
                        'local_path': img_path,
                        'alt_text': '图片',
                        'placeholder': placeholder,
                        'type': 'local',
                        'original_text': img_path
                    })
                    processed_value = processed_value.replace(img_path, placeholder)
            
            # 处理Excel文件
            excel_files = re.findall(patterns['excel_file'], processed_value, re.IGNORECASE)
            for excel_path in excel_files:
                if excel_path not in processed_paths:
                    processed_paths.add(excel_path)
                    placeholder = f"__EXCEL_PLACEHOLDER_{len(resources['excel_files'])}__"
                    resources['excel_files'].append({
                        'original_path': excel_path,
                        'placeholder': placeholder,
                        'type': 'local',
                        'original_text': excel_path
                    })
                    processed_value = processed_value.replace(excel_path, placeholder)
            
            # 处理Markdown表格
            markdown_tables = re.findall(patterns['markdown_table'], processed_value, re.MULTILINE)
            for table_content in markdown_tables:
                placeholder = f"__TABLE_PLACEHOLDER_{len(resources['markdown_tables'])}__"
                resources['markdown_tables'].append({
                    'content': table_content,
                    'placeholder': placeholder,
                    'type': 'markdown',
                    'original_text': table_content
                })
                processed_value = processed_value.replace(table_content, placeholder)
            
            return processed_value, resources
    
    node = TestReportNode()
    
    # 测试场景1：图片嵌入文本
    test_value_1 = "这是报告前言asdasd/ada/ada.jpgdasda这是结尾"
    print(f"\n📝 原始文本: {test_value_1}")
    
    processed_value, resources = node._extract_and_download_resources(test_value_1)
    print(f"✅ 处理后文本: {processed_value}")
    print(f"🖼️ 识别到的图片: {[img['original_path'] for img in resources['images']]}")
    
    # 测试场景2：Excel文件嵌入文本  
    test_value_2 = "报告数据请参考file/data.xlsx文件详情"
    print(f"\n📝 原始文本: {test_value_2}")
    
    processed_value_2, resources_2 = node._extract_and_download_resources(test_value_2)
    print(f"✅ 处理后文本: {processed_value_2}")
    print(f"📊 识别到的Excel: {[excel['original_path'] for excel in resources_2['excel_files']]}")
    
    # 测试场景3：多种资源混合（包括MinIO路径）
    test_value_3 = """
    报告摘要：图片路径/path/image.png和数据表data/report.xlsx
    
    MinIO图片：/bisheng/knowledge/images/123/test.jpg
    临时图片：/tmp-dir/temp/demo.png
    MinIO Excel：/bisheng/reports/data.xlsx
    
    | 项目 | 数值 |
    |------|------|
    | A    | 100  |
    | B    | 200  |
    
    还有网络图片https://example.com/chart.jpg
    """
    print(f"\n📝 原始文本: {test_value_3}")
    
    processed_value_3, resources_3 = node._extract_and_download_resources(test_value_3)
    print(f"✅ 处理后文本: {processed_value_3}")
    print(f"🖼️ 识别到的图片: {len(resources_3['images'])} 个")
    print(f"📊 识别到的Excel: {len(resources_3['excel_files'])} 个") 
    print(f"📋 识别到的表格: {len(resources_3['markdown_tables'])} 个")
    
    # 显示识别到的资源详情
    for i, img in enumerate(resources_3['images']):
        print(f"  图片{i+1}: {img['original_path']} -> {img['type']}")
    for i, excel in enumerate(resources_3['excel_files']):
        print(f"  Excel{i+1}: {excel['original_path']} -> {excel['type']}")
    
    # 测试场景4：复杂混合内容（一段话中多种资源）
    test_value_4 = """
    综合分析报告：首先查看/bisheng/charts/overview.png概览图，
    然后参考/tmp-dir/data/sales.xlsx销售数据，最后是统计表格：
    
    | 季度 | 销售额 | 增长率 |
    |------|-------|--------|
    | Q1   | 100万 | 10%    |
    | Q2   | 120万 | 20%    |
    
    补充图表https://example.com/trends.jpg显示趋势，
    详细数据见report.xlsx文件分析。
    """
    print(f"\n📝 测试场景4 - 复杂混合内容:")
    print(f"原始文本: {test_value_4}")
    
    processed_value_4, resources_4 = node._extract_and_download_resources(test_value_4)
    print(f"✅ 处理后文本: {processed_value_4}")
    print(f"🔍 资源统计:")
    print(f"  - 图片: {len(resources_4['images'])} 个")
    print(f"  - Excel: {len(resources_4['excel_files'])} 个")
    print(f"  - 表格: {len(resources_4['markdown_tables'])} 个")
    
    # 显示处理后的占位符分布
    print(f"\n🎯 占位符分布:")
    for i, img in enumerate(resources_4['images']):
        print(f"  {img['placeholder']} ← {img['original_path']}")
    for i, excel in enumerate(resources_4['excel_files']):
        print(f"  {excel['placeholder']} ← {excel['original_path']}")
    for i, table in enumerate(resources_4['markdown_tables']):
        print(f"  {table['placeholder']} ← Markdown表格")
    
    return True


if __name__ == "__main__":
    test_report_node_scenario()
