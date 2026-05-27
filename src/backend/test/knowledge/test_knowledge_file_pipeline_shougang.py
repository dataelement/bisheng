from types import SimpleNamespace

from bisheng.knowledge.rag.knowledge_file_pipeline import KnowledgeFilePipeline
from bisheng.knowledge.rag.pipeline.transformer.file_encoding import FileEncodingTransformer
from bisheng.knowledge.rag.pipeline.transformer.simhash import SimHashTransformer


def test_excel_pipeline_generates_file_encoding_before_simhash(monkeypatch):
    pipeline = KnowledgeFilePipeline.__new__(KnowledgeFilePipeline)
    pipeline.invoke_user_id = 1
    pipeline.db_file = SimpleNamespace(id=1, knowledge_id=10, tenant_id=1, file_encoding=None)
    pipeline.preview_cache_key = "preview"
    pipeline.loader = SimpleNamespace()
    pipeline.file_split_rule = SimpleNamespace(retain_images=0)
    pipeline.__dict__["file_metadata"] = {}
    monkeypatch.setattr(pipeline, "_init_content_safety_transformers", lambda: [])
    monkeypatch.setattr(pipeline, "_init_abstract_transformers", lambda: [])

    transformers = pipeline._init_excel_transformers()

    file_encoding_index = next(
        index for index, transformer in enumerate(transformers)
        if isinstance(transformer, FileEncodingTransformer)
    )
    simhash_index = next(
        index for index, transformer in enumerate(transformers)
        if isinstance(transformer, SimHashTransformer)
    )
    assert file_encoding_index < simhash_index
