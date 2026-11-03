"""Checkpointed dual-index writes for DocFlow, without a second embedding path."""

import hashlib
import json
import math

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from bisheng.knowledge.docflow.client import DocFlowError


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def elasticsearch_index(store):
    # langchain-elasticsearch 1.0 stores its index on the underlying EVectorStore.
    # Resolve before any cleanup so a missing target cannot delete vector data.
    index = getattr(getattr(store, "_store", None), "index", None)
    if not isinstance(index, str) or not index.strip():
        index = getattr(store, "index_name", None)
    if not isinstance(index, str) or not index.strip():
        raise DocFlowError("DocFlow ingestion: Elasticsearch target index is missing")
    return index


def embedding_profile(delegate):
    snapshots = []
    for name in ("model_info", "server_info"):
        value = getattr(delegate, name, None)
        if callable(getattr(type(value), "model_dump", None)):
            snapshots.append(value.model_dump())
    # Only a one-way digest is persisted; provider credentials can occur in the
    # server snapshot. Configuration changes under the same model ID invalidate
    # both ingestion completion and vector-cache entries.
    return fingerprint(snapshots)


def chunk_identity(document):
    metadata = document.metadata
    text = document.page_content
    abstract = metadata.get("abstract")
    if abstract and text.startswith("{<file_title>"):
        # The summary transformer is best-effort and may regenerate a different
        # summary on retry. Resume the confirmed chunk snapshot instead of
        # reembedding the same source body solely for a new generated abstract.
        text = text.replace(f"<file_abstract>{abstract}</file_abstract>\n", "", 1)
    return text, {key: value for key, value in metadata.items() if key not in ("update_time", "abstract")}


class CachedDocFlowEmbeddings(Embeddings):
    """Cache document vectors in tenant-scoped temporary object storage.

    A process crash between the model response and artifact save can still
    repeat an external model call. No exactly-once model guarantee is claimed.
    """

    def __init__(self, delegate, state, namespace):
        self.delegate, self.state, self.namespace = delegate, state, namespace

    def embed_documents(self, texts):
        keys = [fingerprint([self.state.tenant_id, self.namespace, text]) for text in texts]
        values = [self.state.load_artifact(f"docflow/{self.state.tenant_id}/{key}.json") for key in keys]
        missing = {}
        for index, value in enumerate(values):
            if value is None:
                missing.setdefault(keys[index], texts[index])
        if missing:
            vectors = self.delegate.embed_documents(list(missing.values()))
            if len(vectors) != len(missing):
                raise DocFlowError("Embedding returned an inconsistent vector count")
            vectors = [[float(number) for number in vector] for vector in vectors]
            if any(not vector or not all(math.isfinite(number) for number in vector) for vector in vectors):
                raise DocFlowError("Embedding returned an empty or non-finite vector")
            for key, vector in zip(missing, vectors, strict=True):
                self.state.save_artifact(key, vector)
            vector_map = dict(zip(missing, vectors, strict=True))
            values = [value if value is not None else vector_map[key] for key, value in zip(keys, values, strict=True)]
        return values

    def embed_query(self, text):
        return self.delegate.embed_query(text)


class DocFlowIngest:
    def __init__(self, state, cache_revision="1"):
        self.state, self.cache_revision = state, cache_revision

    def run(self, documents, stores):
        if not documents or not any(document.page_content.strip() for document in documents):
            raise DocFlowError("DocFlow ingestion: no text chunks")
        if not stores:
            return
        if len(stores) != 2:
            raise DocFlowError("DocFlow ingestion requires the existing Milvus + BM25 stores")
        vector, es = stores
        file_ids = {int(document.metadata["document_id"]) for document in documents}
        if len(file_ids) != 1:
            raise DocFlowError("DocFlow ingestion requires one knowledge file per transaction")
        file_id = file_ids.pop()
        identity = getattr(vector, "_docflow_identity", None)
        if not identity:
            raise DocFlowError("DocFlow ingestion target identity is missing")
        identity = {**identity, "runtime_model": embedding_profile(vector.embedding_func)}
        index_name = elasticsearch_index(es)
        # One checkpoint per file+physical target. A model/configuration change
        # changes the signature and cleans that target instead of reviving an
        # obsolete "done" checkpoint after a switch back.
        target = [getattr(vector, "collection_name", None), index_name]
        key = fingerprint(["ingest", self.state.tenant_id, file_id, target])
        signature = fingerprint(
            [
                identity,
                self.cache_revision,
                [chunk_identity(document) for document in documents],
            ]
        )
        with self.state.lease(key) as owned:
            checkpoint = self.state.read(key)
            if checkpoint.get("signature") == signature and checkpoint.get("phase") == "done":
                return
            resume_vector = checkpoint.get("signature") == signature and checkpoint.get("phase") in (
                "vector_done",
                "writing_es",
            )
            saved_documents = None
            if resume_vector and checkpoint.get("documents"):
                saved_documents = self.state.load_artifact(checkpoint["documents"])
                if saved_documents is None:
                    resume_vector = False
                else:
                    documents = [Document(**document) for document in saved_documents]
            artifact_key = fingerprint(["chunks", key, signature])
            artifact = self.state.save_artifact(
                artifact_key,
                [{"page_content": document.page_content, "metadata": document.metadata} for document in documents],
            )
            checkpoint = {"signature": signature, "phase": "deleting", "documents": artifact}
            if resume_vector:
                checkpoint["phase"] = "vector_done"
            self.state.write(key, checkpoint, "ingest")
            owned()
            if not resume_vector:
                if vector.col is not None:
                    vector.col.delete(expr=f"document_id in [{file_id}]", timeout=30)
            if es.client.indices.exists(index=index_name):
                deletion = es.client.delete_by_query(
                    index=index_name, query={"term": {"metadata.document_id": file_id}}, refresh=True
                )
                body = deletion if isinstance(deletion, dict) else deletion.body
                if body.get("failures") or body.get("timed_out"):
                    raise DocFlowError("DocFlow ingestion: Elasticsearch cleanup incomplete")
            if not resume_vector:
                checkpoint["phase"] = "writing_vector"
                self.state.write(key, checkpoint, "ingest")
                delegate = vector.embedding_func
                vector.embedding_func = CachedDocFlowEmbeddings(delegate, self.state, [identity, self.cache_revision])
                try:
                    written = vector.add_documents(documents)
                    if len(written) != len(documents):
                        raise DocFlowError("DocFlow ingestion: incomplete Milvus write")
                finally:
                    vector.embedding_func = delegate
                owned()
                checkpoint["phase"] = "vector_done"
                self.state.write(key, checkpoint, "ingest")
            owned()
            checkpoint["phase"] = "writing_es"
            self.state.write(key, checkpoint, "ingest")
            ids = [fingerprint([key, signature, index]) for index in range(len(documents))]
            written = es.add_documents(documents, ids=ids)
            if len(written) != len(documents):
                raise DocFlowError("DocFlow ingestion: incomplete Elasticsearch write")
            owned()
            checkpoint["phase"] = "done"
            self.state.write(key, checkpoint, "ingest")
