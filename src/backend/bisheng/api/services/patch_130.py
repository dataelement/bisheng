import os

from langchain_core.documents import Document

from bisheng.api.services.md_from_docx import handler as docx_handler
from bisheng.api.services.md_from_excel import handler as excel_handler
from bisheng.api.services.md_from_html import handler as html_handler
from bisheng.api.services.md_from_pdf import handler as pdf_handler
from bisheng.api.services.md_from_pptx import handler as pptx_handler
from bisheng.api.services.md_post_processing import post_processing
from bisheng.cache.utils import CACHE_DIR
from bisheng.utils.minio_client import minio_client


def combine_multiple_md_files_to_raw_texts(
        path,
) -> tuple[list[Document], list[Document]]:
    """
    combine multiple md file to raw texts including meta-data list.
    Args:
        path: the directory containing the md files.
    Returns:
        0: split raw texts, each text is a Document object.
        1: a single Document object containing all the texts combined.
    """

    files = sorted([f for f in os.listdir(path)])
    raw_texts = []

    # 一个文件只对应一个完整的 Document 对象, texts 才是切分后的chunk内容
    documents = [Document(page_content="", metadata={})]

    for file_name in files:
        full_file_name = f"{path}/{file_name}"
        with open(full_file_name, "r", encoding="utf-8") as f:
            content = f.read()
            raw_texts.append(Document(page_content=content, metadata={}))
            documents[0].page_content += content
    return raw_texts, documents


def convert_file_to_md(
        file_name,
        input_file_name,
        header_rows=[0, 1],
        data_rows=10,
        append_header=True,
        knowledge_id=None,
        retain_images=True,
):
    """
    处理文件转换的主函数。
    Args:
        file_name:
        input_file_name:
        header_rows:
        data_rows:
        append_header:
        knowledge_id:
    """
    md_file_name = None
    local_image_dir = None
    include_cache_dir = True
    doc_id = None
    if file_name.endswith(".docx") or file_name.endswith(".doc"):
        md_file_name, local_image_dir, doc_id = docx_handler(CACHE_DIR, input_file_name)
    elif file_name.endswith(".pptx") or file_name.endswith(".ppt"):
        md_file_name, local_image_dir, doc_id = pptx_handler(CACHE_DIR, input_file_name)
        include_cache_dir = False
    elif (
            file_name.endswith(".xlsx")
            or file_name.endswith(".xls")
            or file_name.endswith(".csv")
    ):
        md_file_name, local_image_dir, doc_id = excel_handler(
            CACHE_DIR, input_file_name, header_rows, data_rows, append_header
        )
        local_image_dir = None
        return md_file_name, local_image_dir, doc_id
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
        include_cache_dir = False
    elif file_name.endswith("pdf"):
        md_file_name, local_image_dir, doc_id = pdf_handler(CACHE_DIR, input_file_name)
        include_cache_dir = True

    return replace_image_url(
        md_file_name,
        local_image_dir,
        doc_id,
        include_cache_dir,
        knowledge_id=knowledge_id,
        retain_images=retain_images,
    )


def replace_image_url(
        md_file_name,
        local_image_dir,
        doc_id,
        include_cache_dir,
        knowledge_id=None,
        retain_images=True,
):
    """
    Usage:
        user the same bucket as origin file located.
    Args:
        md_file_name:
        local_image_dir:
        doc_id:
        knowledge_id:
            if the knowledge_id is None, this process will be interrupted,
            because the image files wouldn't be put into minio
    """
    from bisheng.api.services.knowledge_imp import KnowledgeUtils

    minio_image_path = f"/{minio_client.bucket}/{KnowledgeUtils.get_knowledge_file_image_dir(doc_id, knowledge_id)}"
    url_for_replacement = local_image_dir
    if not include_cache_dir:
        url_for_replacement = doc_id

    if md_file_name and local_image_dir and doc_id:
        with open(md_file_name, "r", encoding="utf-8") as f:
            content = f.read()
        content = content.replace(url_for_replacement, minio_image_path)

        with open(md_file_name, "w", encoding="utf-8") as f:
            f.write(content)
    post_processing(md_file_name, retain_images)
    return md_file_name, local_image_dir, doc_id
