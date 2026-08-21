from langchain_core.documents import Document

from bisheng.knowledge.rag.pipeline.transformer.direct_chunk import DirectChunkTransformer


def test_direct_chunks_are_split_to_the_configured_character_limit():
    transformer = DirectChunkTransformer(max_chunk_limit=5)

    documents = transformer.transform_documents([
        Document(page_content="abcdefghijkl", metadata={"page": 7}),
    ])

    assert [document.page_content for document in documents] == ["abcde", "fghij", "kl"]
    assert [document.metadata["chunk_index"] for document in documents] == [0, 1, 2]
    assert all(document.metadata["page"] == 7 for document in documents)
