"""Actual embedding availability; callers release business SQL locks before IO."""

from math import isfinite
from numbers import Real

from bisheng.common.errcode.knowledge import KnowledgeEmbeddingUnavailableError, KnowledgeUnificationError
from bisheng.llm.domain import LLMService


def probe_embedding(knowledge, model_id, invoke_user_id):
    """Check the actual endpoint before any destructive index operation."""
    try:
        embedding = LLMService.get_bisheng_knowledge_embedding_sync(model_id=model_id, invoke_user_id=invoke_user_id)
        vector = embedding.embed_query("embedding availability check")
        if (
            not isinstance(vector, (list, tuple))
            or not vector
            or any(isinstance(value, bool) or not isinstance(value, Real) or not isfinite(value) for value in vector)
        ):
            raise ValueError("embedding availability probe returned an invalid vector")
        return embedding
    except KnowledgeUnificationError:
        raise
    except Exception as error:
        raise KnowledgeEmbeddingUnavailableError(
            knowledge_name=knowledge.name, reason="knowledge_embedding_unavailable"
        ) from error
