from langchain.embeddings.base import Embeddings


def decide_embeddings(model: str) -> Embeddings:
    """ embed method """
    from bisheng.llm.domain.services import LLMService

    return LLMService.get_bisheng_embedding_sync(model_id=model)
