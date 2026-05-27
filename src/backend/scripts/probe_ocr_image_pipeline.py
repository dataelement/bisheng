"""Probe paddle_ocr / mineru / etl4lm loaders against /tmp/tenglong.pdf.

Exercises the post-refactor pipeline:
  1. Loader stages bytes under local_image_dir and embeds final MinIO URLs
     in page_content / metadata.indexes (no MinIO call during load()).
  2. ImageUploadTransformer uploads everything under local_image_dir to
     image_object_dir on MinIO.
  3. Verifies:
       - filename(local) == filename(MinIO object) == filename(in URL)
       - metadata.indexes[s:e] map to valid positions in final content
       - every URL embedded in content resolves to a real MinIO object
"""

import asyncio
import json
import os
import sys
import tempfile
import traceback
from typing import Dict, List

FILE_PATH = "/tmp/tenglong.pdf"
FILE_NAME = "tenglong.pdf"
PROBE_OBJECT_DIR = "probe_ocr_images"


def _summarize_image_dict(images: Dict, n: int = 3):
    print(f"  images count: {len(images)}")
    for i, (k, v) in enumerate(images.items()):
        if i >= n:
            break
        vtype = type(v).__name__
        sample = v if not isinstance(v, str) else (v[:80] + (" ..." if len(v) > 80 else ""))
        print(f"    [{i}] key={k!r}  value_type={vtype}  value_sample={sample!r}")


def _verify_indexes(content: str, metadata: Dict, label: str, n: int = 5):
    indexes = metadata.get("indexes", [])
    pages = metadata.get("pages", [])
    types = metadata.get("types", [])
    print(f"  indexes count: {len(indexes)}  content len: {len(content)}")
    if not indexes:
        return
    sample_ids = list(range(min(n, len(indexes))))
    if len(indexes) > n:
        sample_ids += list(range(len(indexes) - 2, len(indexes)))
    bad = 0
    for i, (s, e) in enumerate(indexes):
        if not (0 <= s <= e <= len(content)):
            bad += 1
    for i in sample_ids:
        s, e = indexes[i]
        snippet = content[s:e]
        ok = 0 <= s <= e <= len(content)
        print(f"    [{i}] type={types[i] if i < len(types) else '?'} page={pages[i] if i < len(pages) else '?'} [{s}:{e}] ok={ok}  text={snippet[:80]!r}")
    if bad:
        print(f"  [FAIL] {bad} indexes entries are out of bounds")


def _check_minio_object(object_key: str) -> bool:
    try:
        from bisheng.core.storage.minio.minio_manager import get_minio_storage_sync
        client = get_minio_storage_sync()
        path = object_key.lstrip("/")
        if path.startswith(client.bucket + "/"):
            path = path[len(client.bucket) + 1:]
        return client.object_exists_sync(object_name=path)
    except Exception as e:
        print(f"    [minio-stat-fail] {object_key} -> {e}")
        return False


def _run_image_upload_transformer(loader, documents, document_id="probe-doc", knowledge_id=999999):
    from bisheng.knowledge.rag.pipeline.transformer.image_upload import ImageUploadTransformer
    t = ImageUploadTransformer(
        loader=loader, document_id=document_id, knowledge_id=knowledge_id, retain_images=True,
    )
    return t.transform_documents(documents)


def _assert_filename_consistency(loader, documents, label: str):
    """All three corner files agree:
      - local fs filename under loader.local_image_dir
      - MinIO object suffix under image_object_dir
      - URL fragment embedded in page_content
    """
    if not loader.local_image_dir or not os.path.exists(loader.local_image_dir):
        print(f"  [filename-check] {label}: no local_image_dir, skipped")
        return
    local_files = sorted([
        f for f in os.listdir(loader.local_image_dir)
        if os.path.isfile(os.path.join(loader.local_image_dir, f))
    ])
    print(f"  local_image_dir files: {len(local_files)}")
    # Check MinIO + URL presence per filename
    in_minio = 0
    in_content = 0
    for fname in local_files:
        url = f"/{loader._minio_bucket}/{loader.image_object_dir}/{fname}"
        if _check_minio_object(url):
            in_minio += 1
        if any(url in doc.page_content for doc in documents):
            in_content += 1
    print(f"  MinIO uploaded: {in_minio}/{len(local_files)}")
    print(f"  URL referenced in content: {in_content}/{len(local_files)}")
    orphan = len(local_files) - in_content
    if orphan:
        print(f"  [INFO] {orphan} orphan(s) uploaded but not referenced (paddle header_image is expected)")


def probe_paddleocr(tmp_dir: str):
    from bisheng.knowledge.rag.pipeline.loader.paddle_ocr import PaddleOcrLoader
    from bisheng.common.services.config_service import settings as bs_settings

    conf = bs_settings.get_knowledge().paddle_ocr
    print("=" * 80)
    print("[PaddleOCR] url:", conf.url)
    loader = PaddleOcrLoader(
        file_path=FILE_PATH, file_metadata={}, file_extension="pdf",
        tmp_dir=tmp_dir, image_object_dir=PROBE_OBJECT_DIR + "/paddle",
        url=conf.url, auth_token=conf.auth_token, timeout=conf.timeout,
        headers=dict(conf.headers), request_kwargs=dict(conf.request_kwargs),
        retain_images=True,
    )

    # 1) Raw API call: capture markdown.images shape
    import base64
    with open(FILE_PATH, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    raw = loader._call_api_sync(b64)
    lps = raw.get("layoutParsingResults", [])
    print(f"  pages: {len(lps)}")
    total_img = 0
    for pi, page in enumerate(lps):
        md = page.get("markdown", {}) or {}
        imgs = md.get("images", {}) or {}
        if pi == 0:
            print(f"  page0 markdown keys: {list(md.keys())}")
        if imgs:
            total_img += len(imgs)
            if pi < 2:
                print(f"  --- page{pi} markdown.images ---")
                _summarize_image_dict(imgs)
    print(f"  total images across pages: {total_img}")

    # 2) Loader builds documents (no MinIO yet, just local staging + URL embed)
    docs = loader._build_documents(lps)
    doc = docs[0]
    content = doc.page_content
    print(f"  document.page_content length: {len(content)}")
    _verify_indexes(content, doc.metadata, "paddleocr")

    # 3) Run ImageUploadTransformer to push to MinIO
    docs = _run_image_upload_transformer(loader, docs)
    _assert_filename_consistency(loader, docs, "paddleocr")


def probe_mineru(tmp_dir: str):
    from bisheng.knowledge.rag.pipeline.loader.mineru import MineruLoader
    from bisheng.common.services.config_service import settings as bs_settings

    conf = bs_settings.get_knowledge().mineru
    print("=" * 80)
    print("[MinerU] url:", conf.url)
    loader = MineruLoader(
        file_path=FILE_PATH, file_metadata={}, file_extension="pdf",
        tmp_dir=tmp_dir, image_object_dir=PROBE_OBJECT_DIR + "/mineru",
        url=conf.url, timeout=conf.timeout,
        headers=dict(conf.headers), request_kwargs=dict(conf.request_kwargs),
    )

    docs = loader.load()
    doc = docs[0]
    content = doc.page_content
    meta = doc.metadata
    print(f"  document.page_content length: {len(content)}")
    _verify_indexes(content, meta, "mineru")

    # Count image-block indexes
    marker_count = 0
    for i, idx in enumerate(meta.get("indexes", [])):
        s, e = idx
        snippet = content[s:e]
        if snippet.lstrip().startswith("![image]("):
            marker_count += 1
            if marker_count <= 3:
                print(f"  [img-block idx={i} {s}:{e}] {snippet[:120]!r}")
    print(f"  image-block indexes total: {marker_count}")

    docs = _run_image_upload_transformer(loader, docs)
    _assert_filename_consistency(loader, docs, "mineru")


def probe_etl4lm(tmp_dir: str):
    from bisheng.knowledge.rag.pipeline.loader.etl4lm import Etl4lmLoader
    from bisheng.common.services.config_service import settings as bs_settings

    conf = bs_settings.get_knowledge().etl4lm
    print("=" * 80)
    print("[ETL4LM] url:", conf.url)
    if not conf.url:
        print("  [SKIP] etl4lm url not configured")
        return
    loader = Etl4lmLoader(
        file_path=FILE_PATH, file_metadata={}, file_extension="pdf",
        tmp_dir=tmp_dir, image_object_dir=PROBE_OBJECT_DIR + "/etl4lm",
        url=conf.url, ocr_sdk_url=conf.ocr_sdk_url, timeout=conf.timeout,
    )

    docs = loader.load()
    doc = docs[0]
    content = doc.page_content
    meta = doc.metadata
    print(f"  document.page_content length: {len(content)}")
    _verify_indexes(content, meta, "etl4lm")

    # Dump Image-type entries: indexes should now span the inserted ![](url) tag
    for i, t in enumerate(meta.get("types", [])):
        if t == "image":
            s, e = meta["indexes"][i]
            print(f"  [Image idx {i}] indexes=[{s}:{e}] content[{s}:{e}]={content[s:e]!r}")

    docs = _run_image_upload_transformer(loader, docs)
    _assert_filename_consistency(loader, docs, "etl4lm")


async def main():
    if not os.path.exists(FILE_PATH):
        print(f"FILE NOT FOUND: {FILE_PATH}")
        sys.exit(1)

    from bisheng.core.context import initialize_app_context
    from bisheng.common.services.config_service import settings as bs_settings
    await initialize_app_context(config=bs_settings)

    with tempfile.TemporaryDirectory() as tmp_dir:
        target = (sys.argv[1] if len(sys.argv) > 1 else "all").lower()
        if target in ("paddle", "all"):
            try:
                probe_paddleocr(tmp_dir)
            except Exception as e:
                print(f"[paddle] outer error: {e}")
                traceback.print_exc()
        if target in ("mineru", "all"):
            try:
                probe_mineru(tmp_dir)
            except Exception as e:
                print(f"[mineru] outer error: {e}")
                traceback.print_exc()
        if target in ("etl4lm", "all"):
            try:
                probe_etl4lm(tmp_dir)
            except Exception as e:
                print(f"[etl4lm] outer error: {e}")
                traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
