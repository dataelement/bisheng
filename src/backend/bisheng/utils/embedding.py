from langchain.embeddings.base import Embeddings


def decide_embeddings(model: str) -> Embeddings:
    """ embed method """
    from bisheng.interface.embeddings.custom import BishengEmbeddings

    return BishengEmbeddings(model_id=model)
