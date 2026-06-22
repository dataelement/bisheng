from langchain_core.documents import Document

from bisheng.knowledge.rag.pipeline.transformer.splitter import SplitterTransformer
from bisheng_langchain.text_splitter import ElemCharacterTextSplitter


def test_elem_character_text_splitter_adds_character_fallback_for_custom_separators():
    text = "a" * 2500
    splitter = ElemCharacterTextSplitter(
        separators=["\n"],
        separator_rule=["after"],
        chunk_size=1000,
        chunk_overlap=0,
        is_separator_regex=True,
    )

    chunks = splitter.split_text(text)

    assert "".join(chunks) == text
    assert len(chunks) == 3
    assert max(len(chunk) for chunk in chunks) <= 1000


def test_splitter_transformer_handles_long_text_without_configured_separators():
    transformer = SplitterTransformer(
        separator=["\n"],
        separator_rule=["after"],
        chunk_size=1000,
        chunk_overlap=0,
    )

    documents = transformer.transform_documents([Document(page_content="a" * 12000, metadata={})])

    assert len(documents) == 12
    assert max(len(document.page_content) for document in documents) <= 1000
