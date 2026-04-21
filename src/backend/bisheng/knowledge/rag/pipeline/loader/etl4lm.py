import base64
import os
from typing import List, Dict, Tuple

import cv2
import fitz
import requests
from PIL import Image
from langchain_core.documents import Document
from loguru import logger

from bisheng.knowledge.rag.pipeline.loader.base import BaseBishengLoader
from bisheng.knowledge.rag.pipeline.types import TextBbox
from bisheng.utils.exceptions import EtlException


class Etl4lmLoader(BaseBishengLoader):
    def __init__(self, url: str, ocr_sdk_url: str, enable_formular: bool = True, force_ocr: bool = True,
                 filter_page_header_footer: bool = False, start: int = 0, n: int = None, timeout: int = 60,
                 retain_images: bool = True, *args, **kwargs):
        super(Etl4lmLoader, self).__init__(*args, **kwargs)
        self.url = url
        self.ocr_sdk_url = ocr_sdk_url
        self.enable_formular = enable_formular
        self.force_ocr = force_ocr
        self.filter_page_header_footer = filter_page_header_footer
        self.start = start
        self.n = n
        self.timeout = timeout
        self.retain_images = retain_images

    def parse_bbox_list(self, partitions: List[Dict]):
        """Resolve BuildbboxCorrespondence with text"""
        if not partitions:
            return None
        self.bbox_list = []
        for part_index, part in enumerate(partitions):
            bboxes = part["metadata"]["extra_data"]["bboxes"]
            indexes = part["metadata"]["extra_data"]["indexes"]
            pages = part["metadata"]["extra_data"]["pages"]
            text = part["text"]
            for index, bbox in enumerate(bboxes):
                if index == len(bboxes) - 1:
                    val = text[indexes[index][0]:]
                else:
                    val = text[indexes[index][0]:indexes[index][1]]
                self.bbox_list.append(TextBbox(
                    text=val,
                    type=part["type"],
                    part_id=str(part_index),
                    bbox=bbox,
                    page=pages[index],
                ))

    def load(self) -> List[Document]:
        b64_data = base64.b64encode(open(self.file_path, "rb").read()).decode()
        parameters = {
            "start": self.start,
            "n": self.n,
            "filter_page_header_footer": self.filter_page_header_footer,
        }
        payload = dict(
            filename=self.file_name,
            b64_data=[b64_data],
            mode="partition",
            force_ocr=self.force_ocr,
            enable_formula=self.enable_formular,
            filter_page_header_footer=self.filter_page_header_footer,
            ocr_sdk_url=self.ocr_sdk_url,
            parameters=parameters,
        )
        try:
            resp = requests.post(
                self.url, json=payload, timeout=self.timeout
            )
        except requests.Timeout as e:
            logger.error(f"Request to etl4lm API timed out: {e}")
            raise EtlException("etl4lm server timeout")
        except Exception as e:
            if str(e).find("Timeout") != -1:
                logger.error(f"Request to etl4lm API timed out: {e}")
                raise EtlException("etl4lm server timeout")
            raise e
        if resp.status_code != 200:
            raise EtlException(
                f"file partition {self.file_name} failed resp={resp.text}"
            )

        resp = resp.json()
        if 200 != resp.get("status_code"):
            logger.info(
                f"file partition {self.file_name} error resp={resp}"
            )
            raise EtlException(
                f"file partition error {self.file_name} error resp={resp}"
            )
        partitions = resp["partitions"]
        if partitions:
            logger.info(f"content_from_partitions")
            content, metadata = self.merge_partitions(partitions)
            self.parse_bbox_list(partitions)
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

        metadata.update(self.file_metadata)
        return [Document(page_content=content, metadata=metadata)]

    @staticmethod
    def get_image_tag(results: Dict, part: Dict) -> str:
        element_id = part.get("element_id", None)
        url = results.get(element_id, element_id)
        return f"![]({url})"

    @staticmethod
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

    def crop_image(self, image_file: str, item: Dict):
        element_id = item.get("element_id")
        bbox = item.get("bboxes")
        img = cv2.imread(image_file)
        x1, y1, x2, y2 = bbox
        cropped_img = img[y1:y2, x1:x2]
        file_name = f"{self.local_image_dir}{os.sep}{element_id}.png"
        cv2.imwrite(file_name, cropped_img)
        return file_name

    def extract_images(self, partitions: List[Dict]) -> Dict:
        if not self.retain_images:
            return {}
        image_parts = self.get_image_parts(partitions=partitions)
        if len(image_parts) == 0:
            return {}

        pdf_page_dir = os.path.join(self.tmp_dir, "pdf_page")
        self.local_image_dir = os.path.join(self.tmp_dir, "images")
        os.makedirs(pdf_page_dir, exist_ok=True)
        os.makedirs(self.local_image_dir, exist_ok=True)

        result = {}
        pdf_document = fitz.open(self.file_path)
        for page_number, items in image_parts.items():
            pdf_page_image_path = f"{pdf_page_dir}/{page_number}.png"
            if not os.path.exists(pdf_page_image_path):
                page = pdf_document[page_number]
                pix = page.get_pixmap()
                image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                image.save(pdf_page_image_path)
            for item in items:
                result[item["element_id"]] = self.crop_image(pdf_page_image_path, item)
        return result

    def merge_partitions(self, partitions: List[Dict]) -> Tuple[str, Dict]:
        # Pre-proces sing pdf, Extracting Images
        local_image_result = self.extract_images(partitions=partitions)
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
                part["text"] = self.get_image_tag(local_image_result, part)
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
