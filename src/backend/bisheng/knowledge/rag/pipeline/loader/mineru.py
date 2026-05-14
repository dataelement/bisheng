import base64
import json
import os
import re
from html.parser import HTMLParser
from typing import List, Dict, Any, Tuple
from uuid import uuid4

import requests
from langchain_community.docstore.document import Document
from loguru import logger

from bisheng.common.errcode.knowledge import KnowledgeFileEmptyError
from bisheng.knowledge.rag.pipeline.loader.base import BaseBishengLoader
from bisheng.knowledge.rag.pipeline.types import TextBbox


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.grid = {}
        self.current_r = 0
        self.current_c = 0
        self.in_cell = False
        self.cell_content = []
        self.rowspan = 1
        self.colspan = 1

    def handle_starttag(self, tag, attrs):
        if tag == 'tr':
            self.current_c = 0
            while self.grid.get(self.current_r, {}).get(self.current_c) is not None:
                self.current_c += 1
        elif tag in ('td', 'th'):
            self.in_cell = True
            self.cell_content = []
            attr_dict = dict(attrs)
            try:
                self.rowspan = int(attr_dict.get('rowspan', 1))
            except ValueError:
                self.rowspan = 1
            try:
                self.colspan = int(attr_dict.get('colspan', 1))
            except ValueError:
                self.colspan = 1

            while self.grid.get(self.current_r, {}).get(self.current_c) is not None:
                self.current_c += 1

    def handle_endtag(self, tag):
        if tag in ('td', 'th'):
            self.in_cell = False
            text = "".join(self.cell_content).strip().replace('\n', ' ')

            for r in range(self.current_r, self.current_r + self.rowspan):
                if r not in self.grid:
                    self.grid[r] = {}
                for c in range(self.current_c, self.current_c + self.colspan):
                    self.grid[r][c] = text

            self.current_c += self.colspan

        elif tag == 'tr':
            self.current_r += 1

    def handle_data(self, data):
        data = data.replace('\n', ' ')
        if self.in_cell:
            self.cell_content.append(data)


def html_table_to_md(html_str):
    if not html_str or not isinstance(html_str, str):
        return ""
    if "<tr>" not in html_str.lower():
        return html_str

    parser = TableParser()
    parser.feed(html_str)

    if not parser.grid:
        return html_str

    max_r = max(parser.grid.keys()) if parser.grid else -1
    max_c = max(max(cols.keys()) for cols in parser.grid.values() if cols) if parser.grid else -1
    if max_r < 0 or max_c < 0:
        return html_str

    md_lines = []
    for r in range(max_r + 1):
        row = parser.grid.get(r, {})
        line = "|"
        for c in range(max_c + 1):
            cell_text = row.get(c, "")
            line += f" {cell_text} |"
        md_lines.append(line)

        if r == 0:
            sep = "|"
            for c in range(max_c + 1):
                sep += " --- |"
            md_lines.append(sep)

    return "\n".join(md_lines)


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
                "return_middle_json": True,
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
        middle_json = first_result.get("middle_json", "")
        images_data = first_result.get("images", {})
        pdf_info = None
        if not conten_list and not pdf_info:
            raise KnowledgeFileEmptyError()
        if conten_list:
            conten_list = json.loads(conten_list) if isinstance(conten_list, str) else conten_list
        if middle_json:
            middle_json = json.loads(middle_json) if isinstance(middle_json, str) else middle_json
            pdf_info = middle_json.get("pdf_info")
        logger.info(
            f"Successfully extracted from MinerU: has_pdf_info={bool(pdf_info)}, md_content length={len(conten_list) if conten_list else 0}, images count={len(images_data)}")

        # 生成文档 ID
        doc_id = str(uuid4())

        # 存储图片到 MinIO 并获取路径映射
        image_path_mapping = self._store_images_to_local(images_data, doc_id)

        if pdf_info:
            content, metadata = self.merge_pdf_info(pdf_info)
        else:
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
                if "<tr>" in table_content.lower():
                    table_content = html_table_to_md(table_content)
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

    def merge_pdf_info(self, pdf_info) -> Tuple[str, Dict]:
        self.bbox_list = []
        content = ""

        bboxes = []
        indexes = []
        pages = []
        types = []

        start_index = 0

        for page_num, page in enumerate(pdf_info):
            page_idx = page.get("page_idx", page_num)
            for block in page.get("preproc_blocks", []):
                text_type = block.get("type", "text")
                bbox = block.get("bbox", [])

                text = ""
                if text_type in ("text", "title"):
                    for line in block.get("lines", []):
                        for span in line.get("spans", []):
                            content_str = span.get("content", "")
                            if span.get("type") == "inline_equation":
                                content_str = f"${content_str}$"
                            text += content_str
                        text += "\n"
                elif text_type == "image":
                    img_path = block.get("image_path") or block.get("img_path")
                    if not img_path:
                        for line in block.get("lines", []):
                            for span in line.get("spans", []):
                                if "image_path" in span:
                                    img_path = span["image_path"]
                                    break
                    if img_path:
                        text = f"![image]({img_path})\n"
                elif text_type == "table":
                    html_str = ""
                    for line in block.get("lines", []):
                        for span in line.get("spans", []):
                            if span.get("type") == "table" and span.get("html"):
                                html_str = span.get("html")
                                break
                        if html_str: break
                    if not html_str:
                        for sub_block in block.get("blocks", []):
                            for line in sub_block.get("lines", []):
                                for span in line.get("spans", []):
                                    if span.get("type") == "table" and span.get("html"):
                                        html_str = span.get("html")
                                        break
                                if html_str: break
                            if html_str: break

                    if html_str:
                        md_table = html_table_to_md(html_str)
                        text = f"\n\n{md_table}\n\n"

                if not text:
                    continue

                content += text

                self.bbox_list.append(TextBbox(
                    text=text,
                    type=text_type,
                    page=page_idx,
                    part_id=str(len(self.bbox_list)),
                    bbox=bbox,
                ))
                pages.append(page_idx)
                bboxes.append(bbox)
                indexes.append([start_index, start_index + len(text)])
                types.append(text_type)
                start_index += len(text)

        return content, {
            "bboxes": bboxes,
            "pages": pages,
            "indexes": indexes,
            "types": types,
        }
