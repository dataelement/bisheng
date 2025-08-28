# bisheng/api/services/mineru_loader.py
from typing import List, Optional, Dict, Any
from langchain_community.document_loaders.pdf import BasePDFLoader
from langchain_community.docstore.document import Document
import requests
import os
from uuid import uuid4
import base64
import re
from pathlib import Path

from bisheng.api.services.etl4lm_loader import merge_partitions
from bisheng.utils.minio_client import MinioClient
from bisheng.utils.logger import logger

class MineruLoader(BasePDFLoader):
    def __init__(
        self,
        file_name: str,
        file_path: str,
        base_url: str,
        timeout: int = 600,
        backend: str = "pipeline",
        knowledge_id: int | None = None,
        **kwargs: Any
    ) -> None:
        self.file_name = file_name
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.backend = backend
        self.knowledge_id = knowledge_id
        self.extra = kwargs
        self.partitions = []
        super().__init__(file_path)

    def _store_images_to_minio(self, images_data: Dict[str, Any], doc_id: str) -> Dict[str, str]:
        """将 MinerU 返回的 base64 图片存储到 MinIO，返回图片路径映射"""
        if not images_data:
            return {}
        
        # 调试日志：确认 knowledge_id 的值
        logger.info(f"Storing images to MinIO: knowledge_id={self.knowledge_id}, doc_id={doc_id}, images count={len(images_data)}")
        
        minio_client = MinioClient()
        image_path_mapping = {}
        
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
                    
                    if self.knowledge_id:
                        # 正式模式：存储到知识库目录，包含文档 ID
                        minio_path = f"knowledge/images/{self.knowledge_id}/{doc_id}/{image_name}"
                        bucket_name = minio_client.bucket
                    else:
                        # 预览模式：存储到主桶的临时目录，避免临时桶访问权限问题
                        minio_path = f"tmp/preview_images/{doc_id}/{image_name}"
                        bucket_name = minio_client.bucket  # 使用主桶而不是临时桶
                    
                    # 上传到 MinIO
                    minio_client.upload_minio_data(
                        object_name=minio_path,
                        data=image_bytes,
                        length=len(image_bytes),
                        content_type=f"image/{image_format}"
                    )
                    
                    # 测试 MinIO 访问策略是否生效
                    try:
                        # 尝试直接访问刚上传的图片
                        test_url = f"http://minio:9000/{bucket_name}/{minio_path}"
                        logger.info(f"Testing MinIO access: {test_url}")
                        
                        # 检查文件是否存在
                        if minio_client.object_exists(bucket_name, minio_path):
                            logger.info(f"Image {image_name} successfully uploaded and accessible")
                        else:
                            logger.warning(f"Image {image_name} uploaded but not accessible")
                    except Exception as e:
                        logger.error(f"Failed to test MinIO access for {image_name}: {str(e)}")
                    
                    # 生成可访问的 URL
                    if self.knowledge_id:
                        # 正式模式：使用知识库路径，包含文档 ID
                        image_url = f"/bucket/bisheng/knowledge/images/{self.knowledge_id}/{doc_id}/{image_name}"
                    else:
                        # 预览模式：使用 MinIO 路径，避免文本块过长
                        # 这样既能显示图片，又不会影响后续的 Embedding 处理
                        image_url = f"/bucket/bisheng/tmp/preview_images/{doc_id}/{image_name}"
                        logger.info(f"Using MinIO path for {image_name} in preview mode: {image_url}")
                    
                    image_path_mapping[image_name] = image_url
                    
                    logger.info(f"Successfully stored image {image_name} to MinIO: {minio_path} (bucket: {bucket_name})")
                    
            except Exception as e:
                logger.error(f"Failed to store image {image_name} to MinIO: {str(e)}")
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
                "backend": self.backend,
                "return_md": True,
                "return_content_list": True,
                "return_info": True,
                "return_layout": False,
                "return_images": True,
                "is_json_md_dump": False,
                "output_dir": "output",
                **self.extra,
            }
            resp = requests.post(
                f"{self.base_url}/file_parse", files=files, data=data, timeout=self.timeout
            )
        resp.raise_for_status()
        result = resp.json()
        
        # 从 MinerU API 响应中正确提取数据
        # MinerU 返回的数据结构：{"results": {"file_hash": {...}}}
        results = result.get("results", {})
        if not results:
            logger.warning("MinerU API returned empty results")
            return [Document(page_content="", metadata={"source": self.file_name})]
        
        # 获取第一个结果（通常只有一个文件）
        first_result = next(iter(results.values()))
        md_content = first_result.get("md_content", "")
        middle_json = first_result.get("middle_json", {})
        images_data = first_result.get("images", {})
        
        logger.info(f"Successfully extracted from MinerU: md_content length={len(md_content)}, images count={len(images_data)}")
        
        # 生成文档 ID
        doc_id = str(uuid4())
        
        # 存储图片到 MinIO 并获取路径映射
        image_path_mapping = self._store_images_to_minio(images_data, doc_id)
        
        # 替换 Markdown 中的图片链接
        if image_path_mapping:
            md_content = self._replace_image_links_in_markdown(md_content, image_path_mapping)
        
        # 构建 partitions 结构（用于原文定位）
        if middle_json and "pdf_info" in middle_json:
            pdf_info = middle_json["pdf_info"]
            partitions = []
            
            for page_num, page_data in enumerate(pdf_info.get("pages", [])):
                page_partitions = []
                
                # 处理预处理块
                for block in page_data.get("preproc_blocks", []):
                    if "lines" in block:
                        text_parts = []
                        bboxes = []
                        indexes = []
                        
                        for line in block["lines"]:
                            for span in line.get("spans", []):
                                if "text" in span:
                                    text_parts.append(span["text"])
                                    if "bbox" in span:
                                        bboxes.append(span["bbox"])
                                    indexes.append(len("".join(text_parts)) - len(span["text"]))
                        
                        if text_parts:
                            text = "".join(text_parts)
                            partition = {
                                "text": text,
                                "metadata": {
                                    "extra_data": {
                                        "bboxes": bboxes,
                                        "indexes": indexes,
                                        "pages": [page_num + 1],
                                        "types": [block.get("type", "Paragraph")]
                                    }
                                }
                            }
                            page_partitions.append(partition)
                
                # 处理丢弃块
                for block in page_data.get("discarded_blocks", []):
                    if "lines" in block:
                        text_parts = []
                        bboxes = []
                        indexes = []
                        
                        for line in block["lines"]:
                            for span in line.get("spans", []):
                                if "text" in span:
                                    text_parts.append(span["text"])
                                    if "bbox" in span:
                                        bboxes.append(span["bbox"])
                                    indexes.append(len("".join(text_parts)) - len(span["text"]))
                        
                        if text_parts:
                            text = "".join(text_parts)
                            partition = {
                                "text": text,
                                "metadata": {
                                    "extra_data": {
                                        "bboxes": bboxes,
                                        "indexes": indexes,
                                        "pages": [page_num + 1],
                                        "types": [block.get("type", "Paragraph")]
                                    }
                                }
                            }
                            page_partitions.append(partition)
                
                partitions.extend(page_partitions)
            
            self.partitions = partitions
            logger.info(f"Built {len(partitions)} partitions from middle_json")
        
        # 确保 md_content 不为空
        if not md_content or not md_content.strip():
            logger.error("MinerU returned empty md_content")
            return [Document(page_content="", metadata={"source": self.file_name})]
        
        # 尝试使用 merge_partitions 处理图片和生成最终内容
        try:
            if self.partitions and self.knowledge_id:
                content, metadata = merge_partitions(self.file_path, self.partitions, self.knowledge_id)
                # 若合成内容为空，则使用处理后的 md_content
                if not content or not str(content).strip():
                    logger.info("merge_partitions returned empty content, using md_content")
                    final_doc = Document(page_content=md_content, metadata={"source": self.file_name})
                else:
                    logger.info("Successfully merged partitions")
                    final_doc = Document(page_content=content, metadata=metadata)
            else:
                # 没有 partitions 或 knowledge_id，直接使用处理后的 md_content
                logger.info(f"No partitions or knowledge_id, using md_content directly. partitions: {len(self.partitions)}, knowledge_id: {self.knowledge_id}")
                final_doc = Document(page_content=md_content, metadata={"source": self.file_name})
        except Exception as e:
            logger.warning(f"Failed to merge partitions, falling back to md_content: {str(e)}")
            # 回退到处理后的 md_content
            final_doc = Document(page_content=md_content, metadata={"source": self.file_name})
        
        logger.info(f"Final document content length: {len(final_doc.page_content)}")
        return [final_doc]
