import io
import re
import os
import tempfile
import requests
from urllib.parse import urlparse, unquote
from uuid import uuid4
import hashlib
from loguru import logger
from typing import Dict, Tuple, Any

from bisheng.utils.minio_client import MinioClient
from bisheng.utils.docx_temp import DocxTemplateRender
from bisheng.workflow.callback.event import OutputMsgData
from bisheng.workflow.nodes.base import BaseNode


class ReportNode(BaseNode):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._report_info = self.node_params["report_info"]
        self._version_key = self._report_info["version_key"].split("_")[0]
        self._object_name = f"workflow/report/{self._version_key}.docx"
        self._file_name = self._report_info["file_name"] if self._report_info["file_name"] else "tmp_report.docx"
        if not self._file_name.endswith(".docx"):
            self._file_name += ".docx"
        self._minio_client = MinioClient()
        # 存储下载的文件信息，用于后续插入文档
        self._downloaded_files: Dict[str, str] = {}
        # 全局占位符计数器，确保占位符唯一性
        self._global_placeholder_counter = 0

    def _get_unique_placeholder_id(self) -> int:
        """获取唯一的占位符ID"""
        placeholder_id = self._global_placeholder_counter
        self._global_placeholder_counter += 1
        return placeholder_id

    def _bind_markdown_with_images(self, markdown_content: str, image_files: list, resources: dict) -> str:
        """
        将markdown内容中的图片引用与实际图片文件建立绑定关系

        Args:
            markdown_content: markdown文本内容
            image_files: 相关的图片文件路径列表
            resources: 资源信息字典

        Returns:
            str: 处理后的markdown内容（图片引用已替换为占位符）
        """
        if not image_files or not isinstance(image_files, list):
            return markdown_content

        processed_content = markdown_content

        # 提取markdown中的所有图片引用
        markdown_image_pattern = r"!\[([^\]]*)\]\(([^)]+)\)"
        image_matches = re.findall(markdown_image_pattern, processed_content, re.IGNORECASE)

        logger.info(f"在markdown内容中找到 {len(image_matches)} 个图片引用")

        # 为每个图片引用匹配对应的实际图片文件
        for alt_text, img_path in image_matches:
            # 尝试匹配实际的图片文件
            matched_file = self._match_image_file(img_path, image_files)

            if matched_file:
                # 创建占位符
                placeholder = f"__IMAGE_PLACEHOLDER_{self._get_unique_placeholder_id()}__"

                # 添加到资源列表
                resources["images"].append(
                    {
                        "original_path": img_path,
                        "local_path": matched_file,
                        "alt_text": alt_text or "图片",
                        "placeholder": placeholder,
                        "type": "bound",
                        "original_text": f"![{alt_text}]({img_path})",
                    }
                )

                # 替换markdown中的图片引用为占位符
                original_ref = f"![{alt_text}]({img_path})"
                processed_content = processed_content.replace(original_ref, placeholder)

                logger.info(f"绑定成功: markdown引用 '{img_path}' -> 实际文件 '{matched_file}'")
            else:
                logger.warning(f"无法为markdown图片引用 '{img_path}' 找到匹配的实际文件")

        return processed_content

    def _match_image_file(self, markdown_ref: str, image_files: list) -> str:
        """
        为markdown中的图片引用匹配实际的图片文件

        Args:
            markdown_ref: markdown中的图片引用路径
            image_files: 可用的图片文件路径列表

        Returns:
            str: 匹配的图片文件路径，如果没有匹配返回None
        """
        if not markdown_ref or not image_files:
            return None

        # 提取文件名（不含路径）
        ref_filename = os.path.basename(markdown_ref)

        # 策略1: 完全匹配文件名
        for img_file in image_files:
            if os.path.basename(img_file) == ref_filename:
                if os.path.exists(img_file):
                    logger.info(f"完全匹配: {ref_filename} -> {img_file}")
                    return img_file

        # 策略2: 匹配不含扩展名的文件名
        ref_name_without_ext = os.path.splitext(ref_filename)[0]
        for img_file in image_files:
            img_name_without_ext = os.path.splitext(os.path.basename(img_file))[0]
            if img_name_without_ext == ref_name_without_ext:
                if os.path.exists(img_file):
                    logger.info(f"名称匹配: {ref_name_without_ext} -> {img_file}")
                    return img_file

        # 策略3: 检查markdown引用是否本身就是完整路径
        if os.path.exists(markdown_ref) and markdown_ref in image_files:
            logger.info(f"路径匹配: {markdown_ref}")
            return markdown_ref

        # 策略4: 模糊匹配 - 如果只有一个图片文件，假设它们匹配
        available_files = [f for f in image_files if os.path.exists(f)]
        if len(available_files) == 1:
            logger.info(f"单文件匹配: {markdown_ref} -> {available_files[0]} (只有一个可用图片)")
            return available_files[0]

        return None

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
                elif "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" in content_type:
                    filename = f"{uuid4().hex}.xlsx"
                elif "application/vnd.ms-excel" in content_type:
                    filename = f"{uuid4().hex}.xls"
                else:
                    filename = f"{uuid4().hex}.dat"

            # 创建临时文件
            temp_dir = tempfile.gettempdir()
            temp_file = os.path.join(temp_dir, filename)

            with open(temp_file, "wb") as f:
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

            if minio_path.startswith("minio://"):
                # 格式: minio://bucket/object/name
                parts = minio_path[8:].split("/", 1)
                if len(parts) == 2:
                    bucket_name, object_name = parts
                else:
                    object_name = parts[0]
                    bucket_name = self._minio_client.bucket  # 默认bucket
            elif minio_path.startswith("/bisheng/"):
                # 格式: /bisheng/object/name
                bucket_name = self._minio_client.bucket
                object_name = minio_path[9:]  # 移除 '/bisheng/'
            elif minio_path.startswith("/tmp-dir/"):
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
            file_ext = os.path.splitext(object_name)[1] or ".dat"
            filename = f"{uuid4().hex}{file_ext}"
            temp_dir = tempfile.gettempdir()
            temp_file = os.path.join(temp_dir, filename)

            # 保存到临时文件
            with open(temp_file, "wb") as f:
                f.write(file_content)

            logger.info(f"成功从MinIO下载文件: {minio_path} -> {temp_file}")
            return temp_file, True

        except Exception as e:
            logger.error(f"从MinIO下载文件失败: {minio_path}, 错误: {str(e)}")
            return "", False

    def _extract_and_download_resources(
        self, value: str, related_image_files: list = None
    ) -> Tuple[str, Dict[str, Any]]:
        """
        从变量值中提取并下载资源文件

        Args:
            value: 原始变量值（字符串或数组）
            related_image_files: 相关的图片文件路径列表，用于建立绑定关系

        Returns:
            tuple: (处理后的变量值, 资源信息字典)
        """
        # 优先处理数组格式（最高优先级）
        if isinstance(value, list):
            processed_items = []
            resources = {"images": [], "excel_files": [], "csv_files": [], "markdown_tables": []}

            for item in value:
                if isinstance(item, str):
                    # 检查是否是Windows路径，如果是则跳过
                    if item.startswith(("C:", "D:", "E:")) or "\\" in item:
                        logger.warning(f"跳过Windows路径: {item}")
                        continue

                    # 检查是否是图片文件路径（数组中的项目通常是文件路径）
                    if any(item.lower().endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".bmp"]):
                        if os.path.exists(item):
                            placeholder = f"__IMAGE_PLACEHOLDER_{self._get_unique_placeholder_id()}__"
                            resources["images"].append(
                                {
                                    "original_path": item,
                                    "local_path": item,
                                    "alt_text": "图片",
                                    "placeholder": placeholder,
                                    "type": "local",
                                    "original_text": f"![图片]({item})",
                                }
                            )
                            processed_items.append(placeholder)
                            logger.info(f"识别到数组中的本地图片文件: {item}")
                        else:
                            logger.warning(f"数组中的图片文件不存在: {item}")
                    else:
                        # 对非图片项目进行常规资源提取
                        processed_item, item_resources = self._extract_and_download_resources(item)
                        processed_items.append(processed_item)
                        # 合并资源
                        resources["images"].extend(item_resources.get("images", []))
                        resources["excel_files"].extend(item_resources.get("excel_files", []))
                        resources["csv_files"].extend(item_resources.get("csv_files", []))
                        resources["markdown_tables"].extend(item_resources.get("markdown_tables", []))
                else:
                    processed_items.append(str(item))

            return "\n".join(processed_items), resources

        if not isinstance(value, str):
            return str(value), {}

        # 定义正则表达式模式
        patterns = {
            # 图片模式 - 按优先级排序
            "markdown_image": r"!\[([^\]]*)\]\(([^)]+\.(?:png|jpg|jpeg|bmp)(?:\?[^)]*)?)\)",  # Markdown格式图片（支持查询参数）
            "local_image": r"([^\s]*\.(?:png|jpg|jpeg|bmp))",  # 本地路径图片（嵌入文本中）
            "minio_image": r"((?:minio://|/bisheng/|/tmp-dir/)[^\s]*\.(?:png|jpg|jpeg|bmp))",  # MinIO路径图片
            "http_image": r"(https?://[^\s\u4e00-\u9fff]*\.(?:png|jpg|jpeg|bmp)(?:\?[^\s\u4e00-\u9fff]*)?)",
            # HTTP/HTTPS图片（支持查询参数，排除中文字符）
            # 表格模式
            "excel_file": r"([^\s]*\.(?:xls|xlsx)(?:\?[^\s]*)?)",  # Excel文件（嵌入文本中，支持查询参数）
            "csv_file": r"([^\s\u4e00-\u9fff]*\.csv(?:\?[^\s]*)?)",  # CSV文件（嵌入文本中，支持查询参数，排除中文字符）
            "markdown_table": r"(\|[^\r\n]*\|(?:\r?\n\|[^\r\n]*\|)+)",  # Markdown表格（修复版，正确处理表格内的|符号）
        }

        processed_value = value
        resources = {"images": [], "excel_files": [], "csv_files": [], "markdown_tables": []}

        # 用于跟踪已处理的路径，避免重复
        processed_paths = set()

        # 特殊处理：建立markdown内容和相关图片文件的绑定关系
        markdown_binding_applied = False
        if related_image_files and isinstance(related_image_files, list):
            logger.info(f"开始处理markdown内容的图片绑定，关联图片数量: {len(related_image_files)}")
            processed_value = self._bind_markdown_with_images(processed_value, related_image_files, resources)
            markdown_binding_applied = True
            logger.info("绑定处理完成，跳过后续的常规markdown图片处理")

        # 1. 处理图片 - 按优先级排序
        # 1.1 Markdown格式图片（优先级最高）- 仅在未进行绑定处理时执行
        if not markdown_binding_applied:
            markdown_images = re.findall(patterns["markdown_image"], processed_value, re.IGNORECASE)
            for alt_text, img_path in markdown_images:
                if img_path not in processed_paths:
                    processed_paths.add(img_path)

                    if not self._is_valid_url(img_path):  # 本地路径
                        if os.path.exists(img_path):
                            # 本地文件存在，记录到资源列表
                            placeholder = f"__IMAGE_PLACEHOLDER_{self._get_unique_placeholder_id()}__"
                            resources["images"].append(
                                {
                                    "original_path": img_path,
                                    "local_path": img_path,
                                    "alt_text": alt_text,
                                    "placeholder": placeholder,
                                    "type": "local",
                                    "original_text": f"![{alt_text}]({img_path})",
                                }
                            )
                            # 在文档中用占位符替换
                            processed_value = processed_value.replace(f"![{alt_text}]({img_path})", placeholder)
                            logger.info(f"识别到本地Markdown图片: {img_path}")
                        else:
                            logger.warning(f"本地图片文件不存在: {img_path}")
                    else:
                        # 网络图片，下载处理
                        local_path, success = self._download_file(img_path)
                        placeholder = f"__IMAGE_PLACEHOLDER_{self._get_unique_placeholder_id()}__"

                        if success:
                            resources["images"].append(
                                {
                                    "original_path": img_path,
                                    "local_path": local_path,
                                    "alt_text": alt_text,
                                    "placeholder": placeholder,
                                    "type": "downloaded",
                                    "original_text": f"![{alt_text}]({img_path})",
                                }
                            )
                            logger.info(f"网络Markdown图片下载成功: {img_path} -> {local_path}")
                        else:
                            resources["images"].append(
                                {
                                    "original_path": img_path,
                                    "local_path": img_path,
                                    "alt_text": alt_text,
                                    "placeholder": placeholder,
                                    "type": "failed",
                                    "original_text": f"![{alt_text}]({img_path})",
                                }
                            )
                            logger.warning(f"网络Markdown图片下载失败: {img_path}")

                        processed_value = processed_value.replace(f"![{alt_text}]({img_path})", placeholder)

        # 1.2 MinIO路径图片 - 下载到本地
        minio_images = re.findall(patterns["minio_image"], processed_value, re.IGNORECASE)
        for img_path in minio_images:
            if img_path not in processed_paths:
                processed_paths.add(img_path)
                # 下载MinIO图片到本地
                local_path, success = self._download_minio_file(img_path)
                placeholder = f"__IMAGE_PLACEHOLDER_{self._get_unique_placeholder_id()}__"

                if success:
                    resources["images"].append(
                        {
                            "original_path": img_path,
                            "local_path": local_path,
                            "alt_text": "图片",
                            "placeholder": placeholder,
                            "type": "downloaded",
                            "original_text": img_path,
                        }
                    )
                    logger.info(f"MinIO图片下载成功: {img_path} -> {local_path}")
                else:
                    resources["images"].append(
                        {
                            "original_path": img_path,
                            "local_path": img_path,
                            "alt_text": "图片",
                            "placeholder": placeholder,
                            "type": "failed",
                            "original_text": img_path,
                        }
                    )
                    logger.warning(f"MinIO图片下载失败: {img_path}")

                processed_value = processed_value.replace(img_path, placeholder)

        # 1.3 HTTP/HTTPS图片链接
        http_images = re.findall(patterns["http_image"], processed_value, re.IGNORECASE)
        for img_url in http_images:
            if img_url not in processed_paths:
                processed_paths.add(img_url)
                local_path, success = self._download_file(img_url)
                placeholder = f"__IMAGE_PLACEHOLDER_{self._get_unique_placeholder_id()}__"

                if success:
                    resources["images"].append(
                        {
                            "original_path": img_url,
                            "local_path": local_path,
                            "alt_text": "图片",
                            "placeholder": placeholder,
                            "type": "downloaded",
                            "original_text": img_url,
                        }
                    )
                    logger.info(f"网络图片下载成功: {img_url} -> {local_path}")
                else:
                    resources["images"].append(
                        {
                            "original_path": img_url,
                            "local_path": img_url,
                            "alt_text": "图片",
                            "placeholder": placeholder,
                            "type": "failed",
                            "original_text": img_url,
                        }
                    )
                    logger.warning(f"网络图片下载失败: {img_url}")

                processed_value = processed_value.replace(img_url, placeholder)

        # 1.4 本地路径图片（最后处理，避免误匹配）
        local_images = re.findall(patterns["local_image"], processed_value, re.IGNORECASE)
        for img_path in local_images:
            # 过滤掉已处理的路径和明显不是路径的文本
            if (
                img_path not in processed_paths
                and ("/" in img_path or "\\" in img_path)
                and not self._is_valid_url(img_path)  # 必须包含路径分隔符
                and not img_path.startswith("minio://")
                and not img_path.startswith("/bisheng/")
                and not img_path.startswith("/tmp-dir/")
            ):
                processed_paths.add(img_path)
                if os.path.exists(img_path):
                    placeholder = f"__IMAGE_PLACEHOLDER_{self._get_unique_placeholder_id()}__"
                    resources["images"].append(
                        {
                            "original_path": img_path,
                            "local_path": img_path,
                            "alt_text": "图片",
                            "placeholder": placeholder,
                            "type": "local",
                            "original_text": img_path,
                        }
                    )
                    processed_value = processed_value.replace(img_path, placeholder)
                    logger.info(f"识别到本地图片: {img_path}")
                else:
                    logger.warning(f"本地图片文件不存在: {img_path}")

        # 2. 处理Excel表格文件
        excel_files = re.findall(patterns["excel_file"], processed_value, re.IGNORECASE)
        for excel_path in excel_files:
            if excel_path not in processed_paths:
                processed_paths.add(excel_path)
                placeholder = f"__EXCEL_PLACEHOLDER_{self._get_unique_placeholder_id()}__"

                if self._is_valid_url(excel_path):
                    # 网络Excel文件
                    local_path, success = self._download_file(excel_path)
                    if success:
                        resources["excel_files"].append(
                            {
                                "original_path": excel_path,
                                "local_path": local_path,
                                "placeholder": placeholder,
                                "type": "downloaded",
                                "original_text": excel_path,
                            }
                        )
                        logger.info(f"Excel文件下载成功: {excel_path} -> {local_path}")
                    else:
                        resources["excel_files"].append(
                            {
                                "original_path": excel_path,
                                "local_path": excel_path,
                                "placeholder": placeholder,
                                "type": "failed",
                                "original_text": excel_path,
                            }
                        )
                        logger.warning(f"Excel文件下载失败: {excel_path}")
                elif (
                    excel_path.startswith("/bisheng/")
                    or excel_path.startswith("/tmp-dir/")
                    or excel_path.startswith("minio://")
                ):
                    # MinIO Excel文件
                    local_path, success = self._download_minio_file(excel_path)
                    if success:
                        resources["excel_files"].append(
                            {
                                "original_path": excel_path,
                                "local_path": local_path,
                                "placeholder": placeholder,
                                "type": "downloaded",
                                "original_text": excel_path,
                            }
                        )
                        logger.info(f"MinIO Excel文件下载成功: {excel_path} -> {local_path}")
                    else:
                        resources["excel_files"].append(
                            {
                                "original_path": excel_path,
                                "local_path": excel_path,
                                "placeholder": placeholder,
                                "type": "failed",
                                "original_text": excel_path,
                            }
                        )
                        logger.warning(f"MinIO Excel文件下载失败: {excel_path}")
                else:
                    # 本地Excel文件
                    if os.path.exists(excel_path):
                        resources["excel_files"].append(
                            {
                                "original_path": excel_path,
                                "local_path": excel_path,
                                "placeholder": placeholder,
                                "type": "local",
                                "original_text": excel_path,
                            }
                        )
                        logger.info(f"识别到本地Excel文件: {excel_path}")
                    else:
                        resources["excel_files"].append(
                            {
                                "original_path": excel_path,
                                "local_path": excel_path,
                                "placeholder": placeholder,
                                "type": "missing",
                                "original_text": excel_path,
                            }
                        )
                        logger.warning(f"本地Excel文件不存在: {excel_path}")

                processed_value = processed_value.replace(excel_path, placeholder)

        # 3. 处理CSV表格文件
        csv_files = re.findall(patterns["csv_file"], processed_value, re.IGNORECASE)
        for csv_path in csv_files:
            if csv_path not in processed_paths:
                processed_paths.add(csv_path)
                placeholder = f"__CSV_PLACEHOLDER_{self._get_unique_placeholder_id()}__"

                if self._is_valid_url(csv_path):
                    # 网络CSV文件
                    local_path, success = self._download_file(csv_path)
                    if success:
                        resources["csv_files"].append(
                            {
                                "original_path": csv_path,
                                "local_path": local_path,
                                "placeholder": placeholder,
                                "type": "downloaded",
                                "original_text": csv_path,
                            }
                        )
                        logger.info(f"CSV文件下载成功: {csv_path} -> {local_path}")
                    else:
                        resources["csv_files"].append(
                            {
                                "original_path": csv_path,
                                "local_path": csv_path,
                                "placeholder": placeholder,
                                "type": "failed",
                                "original_text": csv_path,
                            }
                        )
                        logger.warning(f"CSV文件下载失败: {csv_path}")
                elif (
                    csv_path.startswith("/bisheng/")
                    or csv_path.startswith("/tmp-dir/")
                    or csv_path.startswith("minio://")
                ):
                    # MinIO CSV文件
                    local_path, success = self._download_minio_file(csv_path)
                    if success:
                        resources["csv_files"].append(
                            {
                                "original_path": csv_path,
                                "local_path": local_path,
                                "placeholder": placeholder,
                                "type": "downloaded",
                                "original_text": csv_path,
                            }
                        )
                        logger.info(f"MinIO CSV文件下载成功: {csv_path} -> {local_path}")
                    else:
                        resources["csv_files"].append(
                            {
                                "original_path": csv_path,
                                "local_path": csv_path,
                                "placeholder": placeholder,
                                "type": "failed",
                                "original_text": csv_path,
                            }
                        )
                        logger.warning(f"MinIO CSV文件下载失败: {csv_path}")
                else:
                    # 本地CSV文件
                    if os.path.exists(csv_path):
                        resources["csv_files"].append(
                            {
                                "original_path": csv_path,
                                "local_path": csv_path,
                                "placeholder": placeholder,
                                "type": "local",
                                "original_text": csv_path,
                            }
                        )
                        logger.info(f"识别到本地CSV文件: {csv_path}")
                    else:
                        resources["csv_files"].append(
                            {
                                "original_path": csv_path,
                                "local_path": csv_path,
                                "placeholder": placeholder,
                                "type": "missing",
                                "original_text": csv_path,
                            }
                        )
                        logger.warning(f"本地CSV文件不存在: {csv_path}")

                processed_value = processed_value.replace(csv_path, placeholder)

        # 4. 处理Markdown表格（保持不变）
        markdown_tables = re.findall(patterns["markdown_table"], processed_value, re.MULTILINE)
        for table_content in markdown_tables:
            placeholder = f"__TABLE_PLACEHOLDER_{self._get_unique_placeholder_id()}__"
            resources["markdown_tables"].append(
                {
                    "content": table_content,
                    "placeholder": placeholder,
                    "type": "markdown",
                    "original_text": table_content,
                }
            )
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
        all_resources = {"images": [], "excel_files": [], "csv_files": [], "markdown_tables": []}

        # 特殊处理：建立markdown内容和图片文件的绑定关系
        dialog_files_content = all_variables.get("dialog_files_content")
        dialog_image_files = all_variables.get("dialog_image_files")

        # 处理每个变量值
        for key, value in all_variables.items():
            # 记录数组变量类型用于调试
            if isinstance(value, list):
                logger.info(f"处理数组变量: {key}, 包含 {len(value)} 个项目")

            # 对于包含markdown内容的变量，传入关联的图片文件信息
            if key == "dialog_files_content" and dialog_image_files:
                logger.info(f"处理markdown内容变量，关联图片文件: {len(dialog_image_files)} 个")
                processed_value, resources = self._extract_and_download_resources(
                    value, related_image_files=dialog_image_files
                )
            else:
                # 统一使用 _extract_and_download_resources 处理其他变量
                processed_value, resources = self._extract_and_download_resources(value)

            # 合并资源信息
            all_resources["images"].extend(resources.get("images", []))
            all_resources["excel_files"].extend(resources.get("excel_files", []))
            all_resources["csv_files"].extend(resources.get("csv_files", []))
            all_resources["markdown_tables"].extend(resources.get("markdown_tables", []))

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

        self.callback_manager.on_output_msg(
            OutputMsgData(
                **{
                    "unique_id": unique_id,
                    "node_id": self.id,
                    "name": self.name,
                    "msg": "",
                    "files": [{"path": file_share_url, "name": self._file_name}],
                    "output_key": "",
                }
            )
        )


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
                "markdown_image": r"!\[([^\]]*)\]\(([^)]+\.(?:png|jpg|jpeg|bmp)(?:\?[^)]*)?)\)",
                "local_image": r"([^\s]*\.(?:png|jpg|jpeg|bmp))",
                "minio_image": r"((?:minio://|/bisheng/|/tmp-dir/)[^\s]*\.(?:png|jpg|jpeg|bmp))",
                "http_image": r"(https?://[^\s\u4e00-\u9fff]*\.(?:png|jpg|jpeg|bmp)(?:\?[^\s\u4e00-\u9fff]*)?)",
                "excel_file": r"([^\s]*\.(?:xls|xlsx)(?:\?[^\s]*)?)",
                "markdown_table": r"(\|[^|\n]*\|(?:\n\|[^|\n]*\|)*)",
            }

            processed_value = value
            resources = {"images": [], "excel_files": [], "markdown_tables": []}

            processed_paths = set()

            # 处理图片路径
            import re

            local_images = re.findall(patterns["local_image"], processed_value, re.IGNORECASE)
            for img_path in local_images:
                if (
                    img_path not in processed_paths
                    and ("/" in img_path or "\\" in img_path)
                    and not self._is_valid_url(img_path)
                ):
                    processed_paths.add(img_path)
                    placeholder = f"__IMAGE_PLACEHOLDER_{self._get_unique_placeholder_id()}__"
                    resources["images"].append(
                        {
                            "original_path": img_path,
                            "local_path": img_path,
                            "alt_text": "图片",
                            "placeholder": placeholder,
                            "type": "local",
                            "original_text": img_path,
                        }
                    )
                    processed_value = processed_value.replace(img_path, placeholder)

            # 处理Excel文件
            excel_files = re.findall(patterns["excel_file"], processed_value, re.IGNORECASE)
            for excel_path in excel_files:
                if excel_path not in processed_paths:
                    processed_paths.add(excel_path)
                    placeholder = f"__EXCEL_PLACEHOLDER_{self._get_unique_placeholder_id()}__"
                    resources["excel_files"].append(
                        {
                            "original_path": excel_path,
                            "placeholder": placeholder,
                            "type": "local",
                            "original_text": excel_path,
                        }
                    )
                    processed_value = processed_value.replace(excel_path, placeholder)

            # 处理Markdown表格
            markdown_tables = re.findall(patterns["markdown_table"], processed_value, re.MULTILINE)
            for table_content in markdown_tables:
                placeholder = f"__TABLE_PLACEHOLDER_{self._get_unique_placeholder_id()}__"
                resources["markdown_tables"].append(
                    {
                        "content": table_content,
                        "placeholder": placeholder,
                        "type": "markdown",
                        "original_text": table_content,
                    }
                )
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
    for i, img in enumerate(resources_3["images"]):
        print(f"  图片{i+1}: {img['original_path']} -> {img['type']}")
    for i, excel in enumerate(resources_3["excel_files"]):
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
    print("\n📝 测试场景4 - 复杂混合内容:")
    print(f"原始文本: {test_value_4}")

    processed_value_4, resources_4 = node._extract_and_download_resources(test_value_4)
    print(f"✅ 处理后文本: {processed_value_4}")
    print("🔍 资源统计:")
    print(f"  - 图片: {len(resources_4['images'])} 个")
    print(f"  - Excel: {len(resources_4['excel_files'])} 个")
    print(f"  - 表格: {len(resources_4['markdown_tables'])} 个")

    # 显示处理后的占位符分布
    print("\n🎯 占位符分布:")
    for i, img in enumerate(resources_4["images"]):
        print(f"  {img['placeholder']} ← {img['original_path']}")
    for i, excel in enumerate(resources_4["excel_files"]):
        print(f"  {excel['placeholder']} ← {excel['original_path']}")
    for i, table in enumerate(resources_4["markdown_tables"]):
        print(f"  {table['placeholder']} ← Markdown表格")

    return True


if __name__ == "__main__":
    test_report_node_scenario()
