import logging
import os
import uuid
from typing import Any, Sequence

from langchain_core.documents import BaseDocumentTransformer, Document

from bisheng.core.storage.minio.minio_manager import get_minio_storage_sync
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from bisheng.knowledge.rag.pipeline.loader.base import BaseBishengLoader

logger = logging.getLogger(__name__)


class ThumbnailTransformer(BaseDocumentTransformer):
    """
    Generate and upload a thumbnail for specific file types to MinIO.
    Excludes word, excel, ppt variants.
    """

    def __init__(self, loader: BaseBishengLoader, knowledge_file: KnowledgeFile) -> None:
        self.loader = loader
        self.knowledge_file = knowledge_file

    def transform_documents(
            self, documents: Sequence[Document], **kwargs: Any
    ) -> Sequence[Document]:
        if not self.knowledge_file or not self.loader.file_path:
            return documents

        file_ext = self.loader.file_extension

        # Exclude specified types
        excluded_exts = ["doc", "docx", "xls", "xlsx", "csv", "ppt", "pptx"]
        if file_ext in excluded_exts:
            return documents

        thumbnail_path = os.path.join(self.loader.tmp_dir, "thumbnail.jpg")
        generated = False

        try:
            if file_ext == "pdf":
                import fitz
                doc = fitz.open(self.loader.file_path)
                if len(doc) > 0:
                    page = doc.load_page(0)
                    pix = page.get_pixmap(matrix=fitz.Matrix(0.5, 0.5))
                    pix.save(thumbnail_path)
                    generated = True
                    doc.close()

            elif file_ext in ["png", "jpg", "jpeg", "bmp"]:
                from PIL import Image
                img = Image.open(self.loader.file_path)
                img.thumbnail((400, 400))
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                img.save(thumbnail_path, "JPEG")
                generated = True

            elif file_ext in ["txt", "md"]:
                from PIL import Image, ImageDraw, ImageFont
                with open(self.loader.file_path, "r", encoding="utf-8", errors="ignore") as f:
                    lines = [f.readline() for _ in range(20)]
                text = "".join(lines)

                img = Image.new('RGB', (800, 800), color=(255, 255, 255))
                d = ImageDraw.Draw(img)
                try:
                    # Attempt to use a common fallback font
                    font = ImageFont.load_default()
                except Exception:
                    font = None

                # Draw text with basic wrapping handling or just let it clip
                d.text((20, 20), text, fill=(0, 0, 0), font=font)

                img.thumbnail((400, 400))
                img.save(thumbnail_path, "JPEG")
                generated = True

            elif file_ext in ["html", "htm"]:
                from playwright.sync_api import sync_playwright
                with sync_playwright() as p:
                    # Launch chromium. This requires that browsers are installed in the environment.
                    browser = p.chromium.launch(headless=True)
                    page = browser.new_page()
                    # playwright can read local files via file:// url
                    local_url = f"file://{os.path.abspath(self.loader.file_path)}"
                    page.goto(local_url, wait_until="networkidle")
                    page.screenshot(path=thumbnail_path, type="jpeg", quality=80)
                    browser.close()
                generated = True

        except Exception as e:
            logger.error(f"Failed to generate thumbnail for {self.knowledge_file.file_name}: {e}")
            generated = False

        if generated and os.path.exists(thumbnail_path):
            try:
                minio_client = get_minio_storage_sync()
                object_name = f"thumbnails/{uuid.uuid4().hex}.jpg"

                # Upload to public bucket
                minio_client.put_object_sync(
                    bucket_name=minio_client.bucket,
                    object_name=object_name,
                    file=thumbnail_path,
                    content_type="image/jpeg"
                )

                # Set thumbnails field on the database model
                self.knowledge_file.thumbnails = object_name
            except Exception as e:
                logger.error(f"Failed to upload thumbnail to minio: {e}")

        return documents
