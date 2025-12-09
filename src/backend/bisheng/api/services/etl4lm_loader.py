# flake8: noqa
"""Loads PDF with semantic splilter."""
import base64
import logging
import os
from typing import List
from uuid import uuid4

import aiofiles
import cv2
import fitz
import requests
from PIL import Image
from aiohttp import ClientTimeout
from langchain_community.docstore.document import Document
from langchain_community.document_loaders.pdf import BasePDFLoader

from bisheng.core.external.http_client.http_client_manager import get_http_client
from bisheng.core.storage.minio.minio_manager import get_minio_storage_sync

logger = logging.getLogger(__name__)


def get_image_tag(results, part):
    element_id = part.get("element_id", None)
    url = results.get(element_id)
    return f"![]({url})"


def get_image_parts(partitions):
    page_dict = {}
    for part in partitions:
        label = part["type"]
        if label == "Image":
            bboxes = part.get("metadata", {}).get("extra_data", {}).get("bboxes", [])
            page = part.get("metadata", {}).get("extra_data", {}).get("pages", -1)
            element_id = part.get("element_id", None)
            if len(bboxes) == 0 or page == -1 or not element_id:
                continue
            item = {}
            item["bboxes"] = bboxes[0]
            item["element_id"] = element_id
            page_id = page[0]
            if page_id not in page_dict:
                page_dict[page_id] = []
            page_dict[page_id].append(item)
    return page_dict


def crop_image(image_file, item, cropped_imag_base_dir):
    element_id = item.get("element_id")
    bbox = item.get("bboxes")
    img = cv2.imread(image_file)
    x1, y1, x2, y2 = bbox
    cropped_img = img[y1:y2, x1:x2]
    file_name = f"{element_id}.png"
    cv2.imwrite(os.path.join(cropped_imag_base_dir, file_name), cropped_img)
    return file_name


def extract_pdf_images(file_name, page_dict, doc_id, knowledge_id):
    from bisheng.api.services.knowledge_imp import put_images_to_minio
    from bisheng.api.services.knowledge_imp import KnowledgeUtils
    from bisheng.core.cache.utils import CACHE_DIR

    result = {}
    base_dir = f"{CACHE_DIR}/{doc_id}"
    cropped_image_base_dir = f"{base_dir}/images"
    pdf_page_base_dir = f"{base_dir}/images"

    if not os.path.exists(pdf_page_base_dir):
        os.makedirs(pdf_page_base_dir)
    if not os.path.exists(cropped_image_base_dir):
        os.makedirs(cropped_image_base_dir)

    pdf_document = fitz.open(file_name)

    minio_client = get_minio_storage_sync()

    for page_number, items in page_dict.items():
        page = pdf_document[page_number]
        pix = page.get_pixmap()
        image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        pdf_image_file_name = f"{pdf_page_base_dir}/{page_number}.png"
        image.save(pdf_image_file_name)
        for item in items:
            cropped_image_file = crop_image(
                pdf_image_file_name, item, cropped_image_base_dir
            )
            result[item["element_id"]] = (
                f"/{minio_client.bucket}/{KnowledgeUtils.get_knowledge_file_image_dir(doc_id, knowledge_id)}/{cropped_image_file}"
            )
    put_images_to_minio(cropped_image_base_dir, knowledge_id, doc_id)
    return result


def pre_handle(partitions, file_name, knowledge_id):
    doc_id = str(uuid4())
    image_parts = get_image_parts(partitions=partitions)
    if len(image_parts) == 0:
        return []
    return extract_pdf_images(file_name, image_parts, doc_id, knowledge_id)


def merge_partitions(file_name, partitions, knowledge_id=None):
    # 预处理pdf，提取图片
    pre_handle_results = pre_handle(
        partitions=partitions, file_name=file_name, knowledge_id=knowledge_id
    )
    text_elem_sep = "\n"
    doc_content = []
    is_first_elem = True
    last_label = ""
    prev_length = 0
    metadata = dict(bboxes=[], pages=[], indexes=[], types=[])

    for part in partitions:
        label, text = part["type"], part["text"]
        extra_data = part["metadata"]["extra_data"]
        if label == "Image":
            part["text"] = get_image_tag(pre_handle_results, part)
            text = part["text"]

        if is_first_elem:
            f_text = text + "\n" if label == "Title" else text
            doc_content.append(f_text)
            is_first_elem = False
        else:
            if last_label == "Title" and label == "Title":
                doc_content.append("\n" + text)
            elif label == "Title":
                doc_content.append("\n\n" + text)
            elif label == "Table":
                doc_content.append("\n\n" + text)
            else:
                if last_label == "Table":
                    doc_content.append(text_elem_sep * 2 + text)
                else:
                    doc_content.append(text_elem_sep + text)

        last_label = label
        metadata["bboxes"].extend(
            list(map(lambda x: list(map(int, x)), extra_data["bboxes"]))
        )
        metadata["pages"].extend(extra_data["pages"])
        metadata["types"].extend(extra_data["types"])

        indexes = extra_data["indexes"]
        up_indexes = [[s + prev_length, e + prev_length] for (s, e) in indexes]
        metadata["indexes"].extend(up_indexes)
        prev_length += len(doc_content[-1])

    content = "".join(doc_content)
    return content, metadata


class Etl4lmLoader(BasePDFLoader):
    """Loads a PDF with pypdf and chunks at character level. dummy version

    Loader also stores page numbers in metadata.
    """

    def __init__(
            self,
            file_name: str,
            file_path: str,
            unstructured_api_key: str = None,
            unstructured_api_url: str = None,
            force_ocr: bool = False,
            enable_formular: bool = True,
            filter_page_header_footer: bool = False,
            ocr_sdk_url: str = None,
            timeout: int = 60,
            knowledge_id: int = None,
            start: int = 0,
            n: int = None,
            verbose: bool = False,
            kwargs: dict = {},
    ) -> None:
        """Initialize with a file path."""
        self.unstructured_api_url = unstructured_api_url
        self.unstructured_api_key = unstructured_api_key
        self.force_ocr = force_ocr
        self.enable_formular = enable_formular
        self.filter_page_header_footer = filter_page_header_footer
        self.ocr_sdk_url = ocr_sdk_url
        self.headers = {"Content-Type": "application/json"}
        self.file_name = file_name
        self.timemout = timeout
        self.start = start
        self.n = n
        self.extra_kwargs = kwargs
        self.partitions = None
        self.knowledge_id = knowledge_id
        super().__init__(file_path)

    def load(self) -> List[Document]:
        """Load given path as pages."""
        b64_data = base64.b64encode(open(self.file_path, "rb").read()).decode()
        parameters = {"start": self.start, "n": self.n}
        parameters.update(self.extra_kwargs)
        # TODO: add filter_page_header_footer into payload when elt4llm is ready.
        payload = dict(
            filename=os.path.basename(self.file_name),
            b64_data=[b64_data],
            mode="partition",
            force_ocr=self.force_ocr,
            enable_formula=self.enable_formular,
            ocr_sdk_url=self.ocr_sdk_url,
            parameters=parameters,
        )
        try:
            resp = requests.post(
                self.unstructured_api_url, headers=self.headers, json=payload, timeout=self.timemout
            )
        except requests.Timeout as e:
            logger.error(f"Request to etl4lm API timed out: {e}")
            raise Exception("etl4lm server timeout")
        except Exception as e:
            if str(e).find("Timeout") != -1:
                logger.error(f"Request to etl4lm API timed out: {e}")
                raise Exception("etl4lm server timeout")
            raise e
        if resp.status_code != 200:
            raise Exception(
                f"file partition {os.path.basename(self.file_name)} failed resp={resp.text}"
            )

        resp = resp.json()
        if 200 != resp.get("status_code"):
            logger.info(
                f"file partition {os.path.basename(self.file_name)} error resp={resp}"
            )
            raise Exception(
                f"file partition error {os.path.basename(self.file_name)} error resp={resp}"
            )
        partitions = resp["partitions"]
        if partitions:
            logger.info(f"content_from_partitions")
            self.partitions = partitions
            content, metadata = merge_partitions(
                self.file_path, partitions, self.knowledge_id
            )
        elif resp.get("text"):
            logger.info(f"content_from_text")
            content = resp["text"]
            metadata = {
                "bboxes": [],
                "pages": [],
                "indexes": [],
                "types": [],
            }
        else:
            logger.warning(f"content_is_empty resp={resp}")
            content = ""
            metadata = {}

        logger.info(f'unstruct_return code={resp.get("status_code")}')

        if resp.get("b64_pdf"):
            with open(self.file_path, "wb") as f:
                f.write(base64.b64decode(resp["b64_pdf"]))

        metadata["source"] = self.file_name
        doc = Document(page_content=content, metadata=metadata)
        return [doc]

    async def aload(self) -> List[Document]:
        """Asynchronously load given path as pages."""
        async with aiofiles.open(self.file_path, "rb") as f:
            file_data = await f.read()
        b64_data = base64.b64encode(file_data).decode()
        parameters = {"start": self.start, "n": self.n}
        parameters.update(self.extra_kwargs)
        # TODO: add filter_page_header_footer into payload when elt4llm is ready.
        payload = dict(
            filename=os.path.basename(self.file_name),
            b64_data=[b64_data],
            mode="partition",
            force_ocr=self.force_ocr,
            enable_formula=self.enable_formular,
            ocr_sdk_url=self.ocr_sdk_url,
            parameters=parameters,
        )
        try:

            http_client = await get_http_client()

            resp = await http_client.post(
                url=self.unstructured_api_url, headers=self.headers, body=payload,
                timeout=ClientTimeout(total=self.timemout)
            )
        except Exception as e:
            if str(e).find("Timeout") != -1:
                logger.error(f"Request to etl4lm API timed out: {e}")
                raise Exception("etl4lm server timeout")
            raise e
        if (resp.status_code != 200) or (resp.body and resp.body.get("status_code") != 200):
            logger.info(
                f"file partition {os.path.basename(self.file_name)} error resp={resp}"
            )
            raise Exception(
                f"file partition error {os.path.basename(self.file_name)} error resp={resp}"
            )

        partitions = resp.body.get("partitions")
        if partitions:
            logger.info(f"content_from_partitions")
            self.partitions = partitions
            content, metadata = merge_partitions(
                self.file_path, partitions, self.knowledge_id
            )
        elif resp.body.get("text"):
            logger.info(f"content_from_text")
            content = resp.body["text"]
            metadata = {
                "bboxes": [],
                "pages": [],
                "indexes": [],
                "types": [],
            }
        else:
            logger.warning(f"content_is_empty resp={resp.body}")
            content = ""
            metadata = {}

        logger.info(f'unstruct_return code={resp.body.get("status_code")}')

        if resp.body.get("b64_pdf"):
            with open(self.file_path, "wb") as f:
                f.write(base64.b64decode(resp.body["b64_pdf"]))

        metadata["source"] = self.file_name
        doc = Document(page_content=content, metadata=metadata)
        return [doc]
