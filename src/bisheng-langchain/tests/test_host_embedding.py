import os

from bisheng_langchain.embeddings import CustomHostEmbedding, HostEmbeddings

RT_EP = os.environ.get('RT_EP')


def test_host_embedding():
    model = 'multilingual-e5-large'
    url = f'http://{RT_EP}/v2.1/models'
    emb = HostEmbeddings(
      model=model,
      host_base_url=url)

    resp = emb.embed_query('你能做什么')
    print(resp)


def test_custom_host_embedding():
    model = 'multilingual-e5-large'
    url = f'http://{RT_EP}/v2.1/models/{model}/infer'
    emb = CustomHostEmbedding(
      model=model,
      host_base_url=url)
    resp = emb.embed_query('你能做什么')
    print(resp)


def test_custom_host_embedding_timeout():
    try:
        model = 'multilingual-e5-large'
        url = f'http://{RT_EP}/v2.1/models/{model}/infer'
        emb = CustomHostEmbedding(
          model=model,
          host_base_url=url,
          timeout=1)
        resp = emb.embed_query('你能做什么')
        print(resp)
    except Exception as e:
        assert 'timeout' in str(e)


# test_host_embedding()
# test_custom_host_embedding()
test_custom_host_embedding_timeout()
