from langchain.embeddings.base import Embeddings


def decide_embeddings(model: str) -> Embeddings:
    """ embed method """
    from bisheng.api.services.llm import LLMService

    return LLMService.get_bisheng_embedding(model_id=model)
