import base64
import json
import os
import re
from typing import List, Dict, Any, Tuple
from uuid import uuid4

import requests
from langchain_community.docstore.document import Document
from loguru import logger

from bisheng.common.errcode.knowledge import KnowledgeFileEmptyError
from bisheng.knowledge.rag.pipeline.loader.base import BaseBishengLoader
from bisheng.knowledge.rag.pipeline.types import TextBbox


class MineruLoader(BaseBishengLoader):
    def __init__(self, url: str, timeout: int = 600, headers: Dict = None, request_kwargs: Dict = None,
                 *args, **kwargs: Any) -> None:
        super(MineruLoader, self).__init__(*args, **kwargs)

        self.url = url
        self.timeout = timeout
        self.headers = headers if headers is not None else {}
        self.request_kwargs = request_kwargs if request_kwargs is not None else {}

        self.extra = kwargs
        self.partitions = []

    def _store_images_to_local(self, images_data: Dict[str, Any], doc_id: str) -> Dict[str, str]:
        """将 MinerU 返回的 base64 图片存储到 MinIO，返回图片路径映射"""
        if not images_data:
            return {}

        image_path_mapping = {}
        self.local_image_dir = os.path.join(self.tmp_dir, doc_id)
        os.makedirs(os.path.dirname(self.local_image_dir), exist_ok=True)

        for image_name, image_info in images_data.items():
            try:
                # 检查是否是 base64 图片数据
                if isinstance(image_info, str) and image_info.startswith('data:image/'):
                    # 提取 base64 数据
                    header, base64_data = image_info.split(',', 1)
                    # 获取图片格式
                    format_match = re.search(r'data:image/(\w+)', header)
                    image_format = format_match.group(1) if format_match else 'jpg'

                    # 解码 base64 数据
                    image_bytes = base64.b64decode(base64_data)
                    image_url = os.path.join(self.local_image_dir, f"{image_name}.{image_format}")
                    with open(image_url, "wb") as f:
                        f.write(image_bytes)

                    image_path_mapping[image_name] = image_url

                    logger.info(
                        f"Successfully stored image {image_name} to local {image_url}")

            except Exception as e:
                logger.error(f"Failed to store image {image_name} to local: {str(e)}")
                continue

        return image_path_mapping

    def _replace_image_links_in_markdown(self, markdown_content: str, image_path_mapping: Dict[str, str]) -> str:
        """替换 Markdown 中的相对图片路径为可访问的 URL"""
        if not image_path_mapping:
            # 如果没有图片映射（预览模式），保持原始链接
            logger.info("No image mapping available, keeping original image links in markdown")
            return markdown_content

        # 有图片映射时，替换为可访问的 URL
        logger.info(f"Replacing {len(image_path_mapping)} image links with accessible URLs")
        for image_name, image_url in image_path_mapping.items():
            # 匹配相对路径格式
            relative_pattern = f"images/{image_name}"

            # 替换为对应的 URL
            markdown_content = markdown_content.replace(relative_pattern, image_url)
            logger.debug(f"Replaced {relative_pattern} with: {image_url}")

        return markdown_content

    def load(self) -> List[Document]:
        with open(self.file_path, "rb") as f:
            files = [("files", f)]
            data: Dict[str, Any] = {
                "return_md": False,
                "return_content_list": True,
                "formula_enable": True,
                "table_enable": True,
                "return_images": True,
                **self.request_kwargs
            }
            resp = requests.post(self.url, files=files, data=data, timeout=self.timeout, headers=self.headers)
        resp.raise_for_status()
        result = resp.json()

        # 从 MinerU API 响应中正确提取数据
        # MinerU 返回的数据结构：{"results": {"file_name": {...}}}
        results = result.get("results", {})
        if not results:
            raise KnowledgeFileEmptyError()

        # 获取第一个结果（通常只有一个文件）
        first_result = next(iter(results.values()))
        conten_list = first_result.get("content_list", "")
        images_data = first_result.get("images", {})
        if not conten_list:
            raise KnowledgeFileEmptyError()
        conten_list = json.loads(conten_list)

        logger.info(
            f"Successfully extracted from MinerU: md_content length={len(conten_list)}, images count={len(images_data)}")

        # 生成文档 ID
        doc_id = str(uuid4())

        # 存储图片到 MinIO 并获取路径映射
        image_path_mapping = self._store_images_to_local(images_data, doc_id)

        content, metadata = self.merge_conten_list(conten_list)

        # 替换 Markdown 中的图片链接
        if image_path_mapping:
            content = self._replace_image_links_in_markdown(content, image_path_mapping)

        return [Document(page_content=content, metadata=metadata)]

    def merge_conten_list(self, content_list) -> Tuple[str, Dict]:
        self.bbox_list = []
        content = ""

        bboxes = []
        indexes = []
        pages = []
        types = []

        start_index = 0
        for index, one in enumerate(content_list):
            text_type = one.get("type")
            if text_type == "image":
                text = f"![image]({one.get('img_path')})\n"
            elif text_type == "table":
                table_content = one.get("table_content")
                if not table_content:
                    continue
                table_footnote = "\n".join(one.get("table_footnote", []))
                text = f"\n\n{table_content}\n{table_footnote}\n\n"
            else:
                text = one.get("text") + "\n"

            content += text

            self.bbox_list.append(TextBbox(
                text=text,
                type=text_type,
                page=one.get("page_idx", 0),
                part_id=str(index),
                bbox=one.get("bbox"),
            ))
            pages.append(one.get("page_idx", 0))
            bboxes.append(one.get("bbox"))
            indexes.append([start_index, start_index + len(text)])
            types.append(text_type)
            start_index += len(text)
        return content, {
            "bboxes": bboxes,
            "pages": pages,
            "indexes": indexes,
            "types": types,
        }
