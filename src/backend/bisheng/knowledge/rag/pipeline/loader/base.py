import os

from langchain_core.document_loaders import BaseLoader

from bisheng.knowledge.rag.pipeline.types import TextBbox


class BaseBishengLoader(BaseLoader):
    """
    Base loader for Bisheng knowledge-file parsing pipelines.

    Image-handling contract (when a loader extracts images during load()):

      1. Call ``ensure_local_image_dir()`` once to set up a FLAT staging dir.
      2. For each image:
           filename = <stable, MinIO-safe, unique-within-doc>
           write bytes to f"{self.local_image_dir}/{filename}"
           embed ``self.build_image_url(filename)`` into page_content
      3. Compute ``metadata.indexes`` against page_content AFTER all
         ``build_image_url`` calls (so indexes match the final text).
      4. Do NOT call MinIO directly. ImageUploadTransformer iterates
         ``local_image_dir`` and uploads with the same filename to
         ``image_object_dir``.

    Filename invariants:
      - stable across the same load() call (same string in local fs and URL);
      - MinIO/URL safe (no '/', no whitespace, no URL-reserved chars);
      - unique within self.local_image_dir (collisions overwrite content).
    """

    def __init__(self, file_path: str, file_metadata: dict, file_extension: str, tmp_dir: str,
                 image_object_dir: str | None = None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.file_path = file_path
        self.file_name = os.path.basename(file_path)
        self.file_metadata = file_metadata or {}
        self.file_extension = file_extension

        # tmp_dir is used to store images in original file.
        # Delete the temporary directory after the pipeline finishes execution.
        self.tmp_dir = tmp_dir

        # MinIO object dir (relative to bucket) where extracted images will live.
        # When set, build_image_url() returns the final MinIO URL and the actual
        # byte upload is performed by ImageUploadTransformer. When None (transient
        # TempFilePipeline), build_image_url() falls back to the local absolute
        # path and no upload occurs.
        self.image_object_dir = image_object_dir

        # Flat directory on local disk where the loader stages image bytes.
        # ImageUploadTransformer reads from here via non-recursive os.listdir.
        self.local_image_dir: str | None = None
        # original file -> preview file path; will be uploaded to minio by
        # ExtraFileTransformer
        self.preview_file_path: str | None = None
        # bbox_list
        self.bbox_list: list[TextBbox] = []

    @property
    def _minio_bucket(self) -> str:
        """Lazily resolve the MinIO bucket name (only needed when building URLs)."""
        from bisheng.core.storage.minio.minio_manager import get_minio_storage_sync
        return get_minio_storage_sync().bucket

    def ensure_local_image_dir(self) -> str:
        """Idempotently set up the flat staging directory under tmp_dir.

        Returns the absolute path. Safe to call multiple times.
        """
        if not self.local_image_dir:
            self.local_image_dir = os.path.join(self.tmp_dir, "images")
        os.makedirs(self.local_image_dir, exist_ok=True)
        return self.local_image_dir

    def build_image_url(self, filename: str) -> str:
        """Compute the string to embed in page_content for an extracted image.

        - image_object_dir set: returns the final MinIO URL. The byte upload
          is deferred to ImageUploadTransformer; metadata.indexes computed
          against this string remain aligned through the splitter.
        - image_object_dir unset: returns the absolute local path (legacy
          fallback for transient pipelines that never persist images).
        """
        if self.image_object_dir:
            return f"/{self._minio_bucket}/{self.image_object_dir}/{filename}"
        if self.local_image_dir:
            return f"{self.local_image_dir}/{filename}"
        return filename

    def rewrite_local_image_refs(self, content: str) -> str:
        """Replace absolute-local-path image refs with final MinIO URLs.

        Used by non-OCR loaders whose markdown utility (docx_handler / pptx_handler
        / pdf_handler / ...) writes absolute local paths into the markdown. The
        rewrite is safe because non-OCR loaders do NOT populate
        ``metadata.indexes`` — there is nothing to misalign.
        """
        if not content or not self.local_image_dir or not self.image_object_dir:
            return content
        return content.replace(
            self.local_image_dir,
            f"/{self._minio_bucket}/{self.image_object_dir}",
        )

