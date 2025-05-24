import os
import requests
import re
from uuid import uuid4
import json
from bisheng.api.services.md_from_docx import handler as docx_handler
from bisheng.api.services.md_from_pptx import handler as pptx_handler
from bisheng.api.services.md_from_excel import handler as excel_handler
from bisheng.api.services.md_from_html import handler as html_handler
from bisheng_langchain.rag.extract_info import extract_title
from bisheng.utils.minio_client import bucket as BUCKET_NAME
from bisheng.cache.utils import CACHE_DIR

def convert_doc_to_docx(file_name):
    """
        convert doc to docx and upload to minio server.
    """
    pass

def convert_pptx_to_pdf(file_name):
    """
        convet pptx and ppt to pdf and upload to minio.
    """
    pass

def extract_images_from_md_converted_by_etl4lm(documents: str):
    """
        1. extract image links from md file which converted by etl4lm.
        2. put all images into minio
        3. reset image links
        4. return new documents
    """
    regex = r"!\[[^\]]*?\]\((.+?)(?:\s+(?:\"[^\"]*\"|'[^\']*'))?\)"
    urls =  re.findall(regex, documents)
    if len(urls) == 0:
        return

    from bisheng.worker.knowledge.file_worker import put_doc_images_to_minio
    uuid = str(uuid4())
    temp_folder = f"{CACHE_DIR}/{uuid}"
    os.makedirs(temp_folder, exist_ok=True)
    # image urls downloaded successfully.
    downloaded_urls = []
    origin_url_prefix = None
    idx = 0
    for url in urls:
        try:
            response = requests.get(url)
            if response.status_code == 200:
                image_path = os.path.join(temp_folder, os.path.basename(url))
                with open(image_path, 'wb') as f:
                    f.write(response.content)
                downloaded_urls.append(url)
                # get origin image url prefix.
                if idx == 0:
                    origin_url_prefix = url.split(".")[-1]
                idx += 1
        except Exception as e:
            print(f"Failed to download image from {url}: {str(e)}")

    if len(downloaded_urls) == 0:
        return

    put_doc_images_to_minio(temp_folder, uuid)
    curr_url_prefix = f"{BUCKET_NAME}/{uuid}"
    result = documents.replace(origin_url_prefix, curr_url_prefix)
    return result


def handle_xls_multiple_md_files(llm, md_file_directories,file_name): 
   files = [f for f in os.listdir(md_file_directories)]
   raw_texts = []
   metadata_list = []
   title = ""
   index = 0
   for file_name in files:
      full_file_name = f"{md_file_directories}/{file_name}"
      with open(full_file_name, "r", encoding="utf-8") as f:
         content = f.read()
         if index == 0:
            title = extract_title(llm=llm, text=content)
            title = re.sub("<think>.*</think>", "", title)
         raw_texts.append(content)
         metedata = {
                "bbox": json.dumps({"chunk_bboxes": ""}),
                "page": 0,
                "source": file_name,
                "title": title,
                "chunk_index": index,
                "extra": "",
            }
         metadata_list.append(metedata)
         index += 1
   return raw_texts, metadata_list, 'local', []


def convert_file_to_md(file_name, input_file_name, header_rows=[0, 1], data_rows=10, append_header=True):
    """
    处理文件转换的主函数。
    """
    md_file_name = None
    local_image_dir = None
    doc_id = None
    if file_name.endswith(".docx") or file_name.endswith(".doc"):
        md_file_name, local_image_dir, doc_id = docx_handler(CACHE_DIR, input_file_name)
    elif file_name.endswith(".pptx") or file_name.endswith(".ppt"):
        md_file_name, local_image_dir, doc_id = pptx_handler(CACHE_DIR, input_file_name)
    elif (
        file_name.endswith(".xlsx")
        or file_name.endswith(".xls")
        or file_name.endswith(".csv")
    ):
        md_file_name, local_image_dir, doc_id = excel_handler(
            CACHE_DIR, input_file_name, header_rows, data_rows, append_header
        )
        local_image_dir = None
    elif (
        file_name.endswith(".html")
        or file_name.endswith(".htm")
        or file_name.endswith(".mhtml")
    ):
        (
            md_file_name,
            local_image_dir,
            doc_id,
        ) = html_handler(CACHE_DIR, input_file_name)
        if not file_name.endswith("mhtml"):
            local_image_dir = None
    return replace_image_url(md_file_name, local_image_dir, doc_id)


def replace_image_url(md_file_name, local_image_dir, doc_id):
    """
        user the same bucket as origin file located.
    """
    minio_image_path = f"/{BUCKET_NAME}/{doc_id}"
    if md_file_name and local_image_dir and doc_id:
        with open(md_file_name, "r", encoding="utf-8") as f:
            content = f.read()
        content = content.replace(local_image_dir, minio_image_path)
        with open(md_file_name, "w", encoding="utf-8") as f:
            f.write(content)
    return md_file_name, local_image_dir, doc_id