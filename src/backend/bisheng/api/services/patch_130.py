import os

from langchain_core.documents import Document

from bisheng.api.services.md_from_docx import handler as docx_handler
from bisheng.api.services.md_from_excel import handler as excel_handler
from bisheng.api.services.md_from_html import handler as html_handler
from bisheng.api.services.md_from_pptx import handler as pptx_handler
from bisheng.cache.utils import CACHE_DIR
from bisheng.utils.minio_client import minio_client


def combine_multiple_md_files_to_raw_texts(path) -> (list[Document], list[Document]):
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
    document = Document(page_content="", metadata={})
    for file_name in files:
        full_file_name = f"{path}/{file_name}"
        with open(full_file_name, "r", encoding="utf-8") as f:
            content = f.read()
            document.page_content += content + "\n"
            raw_texts.append(Document(page_content=content, metadata={}))
    return raw_texts, [document]


def convert_file_to_md(
    file_name,
    input_file_name,
    header_rows=[0, 1],
    data_rows=10,
    append_header=True,
    knowledge_id: int = None,
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
        # if not file_name.endswith("mhtml"):
        # local_image_dir = None
    return replace_image_url(
        md_file_name, local_image_dir, doc_id, knowledge_id=knowledge_id
    )


def replace_image_url(md_file_name, local_image_dir, doc_id, knowledge_id: int = None):
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

    if md_file_name and local_image_dir and doc_id:
        with open(md_file_name, "r", encoding="utf-8") as f:
            content = f.read()
        content = content.replace(local_image_dir, minio_image_path)
        with open(md_file_name, "w", encoding="utf-8") as f:
            f.write(content)
    return md_file_name, local_image_dir, doc_id
