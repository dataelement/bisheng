from bisheng.api.services.md_from_docx import handler as docx_handler
from bisheng.api.services.md_from_pptx import handler as pptx_handler
from bisheng.api.services.md_from_excel  import handler as excel_handler
from bisheng.api.services.md_from_html   import handler as html_handler
from appdirs import user_cache_dir
from bisheng.settings import settings

CACHE_DIR = user_cache_dir('bisheng', 'bisheng')
MINIO_IMAGE_BUCKET_NAME = "images"

def handler(file_name, input_file_name):

    """
    处理文件转换的主函数。
    """
    md_file_name = None
    local_image_dir = None
    doc_id = None
    if file_name.endswith(".docx") or file_name.endswith(".doc"):
       md_file_name, local_image_dir, doc_id = docx_handler(CACHE_DIR, input_file_name)
       local_image_dir = f"{local_image_dir}/media"
    elif file_name.endswith(".pptx") or file_name.endswith(".ppt"):
       md_file_name, local_image_dir, doc_id = pptx_handler(CACHE_DIR, input_file_name)
    elif file_name.endswith(".xlsx") or file_name.endswith(".xls") or file_name.endswith(".csv"):
      md_file_name, local_image_dir, doc_id = excel_handler(CACHE_DIR, input_file_name)
    elif file_name.endswith(".html") or file_name.endswith(".htm") or file_name.endswith(".mhtml"):
      md_file_name, local_image_dir, doc_id, = html_handler(CACHE_DIR, input_file_name)
    return replace_image_url(md_file_name, local_image_dir, doc_id)

def replace_image_url(md_file_name, local_image_dir, doc_id):
   minio_endpoint = settings.object_storage.minio.endpoint
   minio_path  = f"http://{minio_endpoint}/{MINIO_IMAGE_BUCKET_NAME}/{doc_id}"
   if md_file_name and local_image_dir and doc_id:
      with open(md_file_name, 'r', encoding='utf-8') as f:
         content = f.read()
      content = content.replace(local_image_dir, minio_path)
      with open(md_file_name, 'w', encoding='utf-8') as f:
         f.write(content)
   return md_file_name, local_image_dir, doc_id