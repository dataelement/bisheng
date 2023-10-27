"""Wrapper around Elasticsearch vector database."""
from __future__ import annotations

import uuid
from abc import ABC
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Optional, Tuple

import jieba.analyse
from langchain.docstore.document import Document
from langchain.embeddings.base import Embeddings
from langchain.utils import get_from_dict_or_env
from langchain.vectorstores.base import VectorStore
from langchain.chains.llm import LLMChain
from langchain.llms.base import BaseLLM
from langchain.prompts.prompt import PromptTemplate

if TYPE_CHECKING:
    from elasticsearch import Elasticsearch  # noqa: F401


def _default_text_mapping() -> Dict:
    return {'properties': {'text': {'type': 'text'}}}


DEFAULT_PROMPT = PromptTemplate(
    input_variables=["question"],
    template="""分析给定Question，提取Question中包含的KeyWords，输出列表形式

Examples:
Question: 达梦公司在过去三年中的流动比率如下：2021年：3.74倍；2020年：2.82倍；2019年：2.05倍。
KeyWords: ['过去三年', '流动比率', '2021', '3.74', '2020', '2.82', '2019', '2.05']

----------------
Question: {question}
KeyWords: """,
)


# ElasticKeywordsSearch is a concrete implementation of the abstract base class
# VectorStore, which defines a common interface for all vector database
# implementations. By inheriting from the ABC class, ElasticKeywordsSearch can be
# defined as an abstract base class itself, allowing the creation of subclasses with
# their own specific implementations. If you plan to subclass ElasticKeywordsSearch,
# you can inherit from it and define your own implementation of the necessary methods
# and attributes.
class ElasticKeywordsSearch(VectorStore, ABC):
    """Wrapper around Elasticsearch as a vector database.

    To connect to an Elasticsearch instance that does not require
    login credentials, pass the Elasticsearch URL and index name along with the

    Example:
        .. code-block:: python

            from langchain import ElasticKeywordsSearch

            elastic_vector_search = ElasticKeywordsSearch(
                elasticsearch_url="http://localhost:9200",
                index_name="test_index",
            )


    To connect to an Elasticsearch instance that requires login credentials,
    including Elastic Cloud, use the Elasticsearch URL format
    https://username:password@es_host:9243. For example, to connect to Elastic
    Cloud, create the Elasticsearch URL with the required authentication details and
    pass it to the ElasticKeywordsSearch constructor as the named parameter
    elasticsearch_url.

    You can obtain your Elastic Cloud URL and login credentials by logging in to the
    Elastic Cloud console at https://cloud.elastic.co, selecting your deployment, and
    navigating to the "Deployments" page.

    To obtain your Elastic Cloud password for the default "elastic" user:

    1. Log in to the Elastic Cloud console at https://cloud.elastic.co
    2. Go to "Security" > "Users"
    3. Locate the "elastic" user and click "Edit"
    4. Click "Reset password"
    5. Follow the prompts to reset the password

    The format for Elastic Cloud URLs is
    https://username:password@cluster_id.region_id.gcp.cloud.es.io:9243.

    Example:
        .. code-block:: python

            from langchain import ElasticKeywordsSearch
            elastic_host = "cluster_id.region_id.gcp.cloud.es.io"
            elasticsearch_url = f"https://username:password@{elastic_host}:9243"
            elastic_keywords_search = ElasticKeywordsSearch(
                elasticsearch_url=elasticsearch_url,
                index_name="test_index"
            )

    Args:
        elasticsearch_url (str): The URL for the Elasticsearch instance.
        index_name (str): The name of the Elasticsearch index for the keywords.

    Raises:
        ValueError: If the elasticsearch python package is not installed.
    """

    def __init__(
        self,
        elasticsearch_url: str,
        index_name: str,
        *,
        ssl_verify: Optional[Dict[str, Any]] = None,
        llm_chain: Optional[LLMChain] = None,
    ):
        """Initialize with necessary components."""
        try:
            import elasticsearch
        except ImportError:
            raise ImportError('Could not import elasticsearch python package. '
                              'Please install it with `pip install elasticsearch`.')
        self.index_name = index_name
        self.llm_chain = llm_chain
        _ssl_verify = ssl_verify or {}
        try:
            self.client = elasticsearch.Elasticsearch(elasticsearch_url, **_ssl_verify)
        except ValueError as e:
            raise ValueError(f'Your elasticsearch client string is mis-formatted. Got error: {e} ')

    def add_texts(
        self,
        texts: Iterable[str],
        metadatas: Optional[List[dict]] = None,
        ids: Optional[List[str]] = None,
        refresh_indices: bool = True,
        **kwargs: Any,
    ) -> List[str]:
        """Run more texts through the keywords and add to the vectorstore.

        Args:
            texts: Iterable of strings to add to the vectorstore.
            metadatas: Optional list of metadatas associated with the texts.
            ids: Optional list of unique IDs.
            refresh_indices: bool to refresh ElasticSearch indices

        Returns:
            List of ids from adding the texts into the vectorstore.
        """
        try:
            from elasticsearch.exceptions import NotFoundError
            from elasticsearch.helpers import bulk
        except ImportError:
            raise ImportError('Could not import elasticsearch python package. '
                              'Please install it with `pip install elasticsearch`.')
        requests = []
        ids = ids or [str(uuid.uuid4()) for _ in texts]
        mapping = _default_text_mapping()

        # check to see if the index already exists
        try:
            self.client.indices.get(index=self.index_name)
        except NotFoundError:
            # TODO would be nice to create index before embedding,
            # just to save expensive steps for last
            self.create_index(self.client, self.index_name, mapping)

        for i, text in enumerate(texts):
            metadata = metadatas[i] if metadatas else {}
            request = {
                '_op_type': 'index',
                '_index': self.index_name,
                'text': text,
                'metadata': metadata,
                '_id': ids[i],
            }
            requests.append(request)
        bulk(self.client, requests)

        if refresh_indices:
            self.client.indices.refresh(index=self.index_name)
        return ids

    def similarity_search(self,
                          query: str,
                          k: int = 4,
                          query_strategy: str = 'match_phrase',
                          must_or_should: str = 'should',
                          **kwargs: Any) -> List[Document]:
        assert must_or_should in ['must', 'should'], 'only support must and should.'
        # llm or jiaba extract keywords
        if self.llm_chain:
            keywords_str = self.llm_chain.run(query)
            print('keywords_str:', keywords_str)
            try:
                keywords = eval(keywords_str)
                if not isinstance(keywords, list):
                    raise ValueError('Keywords extracted by llm is not list.')
            except Exception as e:
                print(str(e))
                keywords = jieba.analyse.extract_tags(query, topK=10, withWeight=False)
        else:
            keywords = jieba.analyse.extract_tags(query, topK=10, withWeight=False)
        match_query = {'bool': {must_or_should: []}}
        for key in keywords:
            match_query['bool'][must_or_should].append({query_strategy: {'text': key}})
        docs_and_scores = self.similarity_search_with_score(match_query, k)
        documents = [d[0] for d in docs_and_scores]
        return documents

    def similarity_search_with_score(self, query: str, k: int = 4, **kwargs: Any) -> List[Tuple[Document, float]]:
        response = self.client_search(self.client, self.index_name, query, size=k)
        hits = [hit for hit in response['hits']['hits']]
        docs_and_scores = [(
            Document(
                page_content=hit['_source']['text'],
                metadata=hit['_source']['metadata'],
            ),
            hit['_score'],
        ) for hit in hits]
        return docs_and_scores

    @classmethod
    def from_texts(
        cls,
        texts: List[str],
        embedding: Embeddings,
        metadatas: Optional[List[dict]] = None,
        ids: Optional[List[str]] = None,
        index_name: Optional[str] = None,
        refresh_indices: bool = True,
        llm: Optional[BaseLLM] = None,
        prompt: Optional[PromptTemplate] = DEFAULT_PROMPT,
        **kwargs: Any,
    ) -> ElasticKeywordsSearch:
        """Construct ElasticKeywordsSearch wrapper from raw documents.

        This is a user-friendly interface that:
            1. Embeds documents.
            2. Creates a new index for the embeddings in the Elasticsearch instance.
            3. Adds the documents to the newly created Elasticsearch index.

        This is intended to be a quick way to get started.

        Example:
            .. code-block:: python

                from langchain import ElasticKeywordsSearch
                from langchain.embeddings import OpenAIEmbeddings
                embeddings = OpenAIEmbeddings()
                elastic_vector_search = ElasticKeywordsSearch.from_texts(
                    texts,
                    embeddings,
                    elasticsearch_url="http://localhost:9200"
                )
        """
        elasticsearch_url = get_from_dict_or_env(kwargs, 'elasticsearch_url', 'ELASTICSEARCH_URL')
        if 'elasticsearch_url' in kwargs:
            del kwargs['elasticsearch_url']
        index_name = index_name or uuid.uuid4().hex
        if llm:
            llm_chain = LLMChain(llm=llm, prompt=prompt)
            vectorsearch = cls(elasticsearch_url, index_name, llm_chain=llm_chain, **kwargs)
        else:
            vectorsearch = cls(elasticsearch_url, index_name, **kwargs)
        vectorsearch.add_texts(texts, metadatas=metadatas, ids=ids, refresh_indices=refresh_indices)
        return vectorsearch

    def create_index(self, client: Any, index_name: str, mapping: Dict) -> None:
        version_num = client.info()['version']['number'][0]
        version_num = int(version_num)
        if version_num >= 8:
            client.indices.create(index=index_name, mappings=mapping)
        else:
            client.indices.create(index=index_name, body={'mappings': mapping})

    def client_search(self, client: Any, index_name: str, script_query: Dict, size: int) -> Any:
        version_num = client.info()['version']['number'][0]
        version_num = int(version_num)
        if version_num >= 8:
            response = client.search(index=index_name, query=script_query, size=size)
        else:
            response = client.search(index=index_name, body={'query': script_query, 'size': size})
        return response

    def delete(self, ids: Optional[List[str]] = None, **kwargs: Any) -> None:
        """Delete by vector IDs.

        Args:
            ids: List of ids to delete.
        """

        if ids is None:
            raise ValueError('No ids provided to delete.')

        # TODO: Check if this can be done in bulk
        for id in ids:
            self.client.delete(index=self.index_name, id=id)
