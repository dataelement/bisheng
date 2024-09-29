from abc import ABC
from typing import TYPE_CHECKING, Any, Callable, Dict, Iterable, List, Optional, Tuple

import jieba
from bisheng_langchain.vectorstores.elastic_keywords_search import DEFAULT_PROMPT
from bisheng_langchain.vectorstores.milvus import DEFAULT_MILVUS_CONNECTION
from langchain.chains.llm import LLMChain
from langchain.docstore.document import Document
from langchain.embeddings.base import Embeddings
from langchain.utils import get_from_dict_or_env
from langchain.vectorstores.base import VectorStore
from langchain_community.vectorstores.milvus import Milvus as MilvusLangchain
from langchain_core.language_models import BaseLLM
from langchain_core.prompts import PromptTemplate
from loguru import logger

if TYPE_CHECKING:
    from elasticsearch import Elasticsearch  # noqa: F401


class MilvusWithPermissionCheck(MilvusLangchain):
    """
    only support multi collection search, but all collection must have same fields

    not include create collection
    """

    def __init__(self,
                 embedding_function: Embeddings,
                 collection_name: list[str] = None,
                 connection_args: Optional[dict[str, Any]] = None,
                 consistency_level: str = 'Session',
                 index_params: Optional[dict] = None,
                 search_params: Optional[dict] = None,
                 drop_old: Optional[bool] = False,
                 *,
                 primary_field: str = 'pk',
                 text_field: str = 'text',
                 vector_field: str = 'vector',
                 partition_field: str = 'knowledge_id',
                 **kwargs: Any):
        """Initialize the Milvus vector store."""
        try:
            from pymilvus import Collection, utility
        except ImportError:
            raise ValueError('Could not import pymilvus python package. '
                             'Please install it with `pip install pymilvus`.')

        # Default search params when one is not provided.
        self.default_search_params = {
            'IVF_FLAT': {
                'metric_type': 'L2',
                'params': {
                    'nprobe': 10
                }
            },
            'IVF_SQ8': {
                'metric_type': 'L2',
                'params': {
                    'nprobe': 10
                }
            },
            'IVF_PQ': {
                'metric_type': 'L2',
                'params': {
                    'nprobe': 10
                }
            },
            'HNSW': {
                'metric_type': 'L2',
                'params': {
                    'ef': 100
                }
            },
            'RHNSW_FLAT': {
                'metric_type': 'L2',
                'params': {
                    'ef': 10
                }
            },
            'RHNSW_SQ': {
                'metric_type': 'L2',
                'params': {
                    'ef': 10
                }
            },
            'RHNSW_PQ': {
                'metric_type': 'L2',
                'params': {
                    'ef': 10
                }
            },
            'IVF_HNSW': {
                'metric_type': 'L2',
                'params': {
                    'nprobe': 10,
                    'ef': 10
                }
            },
            'ANNOY': {
                'metric_type': 'L2',
                'params': {
                    'search_k': 10
                }
            },
            'AUTOINDEX': {
                'metric_type': 'L2',
                'params': {}
            },
        }

        self.embedding_func = embedding_function
        self.collection_name = collection_name
        self.index_params = index_params
        self.search_params = search_params
        self.consistency_level = consistency_level
        self.connection_args = connection_args

        # In order for a collection to be compatible, pk needs to be auto'id and int
        self._primary_field = primary_field
        # In order for compatiblility, the text field will need to be called "text"
        self._text_field = text_field
        # In order for compatibility, the vector field needs to be called "vector"
        self._vector_field = vector_field
        #  partion key for multi-tenancy
        self._partition_field = partition_field

        # if collection_name is None or collection_name.__len__() == 0:
        #     raise ValueError('collection_name cannot be empty, please provide at least one collection name.')

        self.fields: list[str] = []
        # Create the connection to the server
        if connection_args is None:
            connection_args = DEFAULT_MILVUS_CONNECTION

        self.alias = self._create_connection_alias(connection_args)
        self.col: Optional[List[Collection]] = []
        self.col_partition_key: Optional[List[str]] = []
        # not used
        self.drop_old = drop_old

        # Grab the existing collection if it exists
        try:
            for index, one_collection_name in enumerate(self.collection_name):
                if utility.has_collection(one_collection_name, using=self.alias):
                    self.col.append(Collection(
                        one_collection_name,
                        using=self.alias,
                    ))
                    self.col_partition_key.append(kwargs.get('partition_keys')[index])
        except Exception as e:
            logger.error(f'milvus operating error={str(e)}')
            self.close_connection(self.alias)
            raise e

        if not self.col:
            logger.warning('No collection found, please confirm user have knowledge access')
            # raise ValueError("No collection found, please confirm collection name correctly.")
        # Initialize the vector store
        self._init()

    def close_connection(self, using):
        from pymilvus import connections
        connections.remove_connection(using)

    def _init(
        self,
        embeddings: Optional[list] = None,
        metadatas: Optional[list[dict]] = None,
        partition_names: Optional[list] = None,
        replica_number: int = 1,
        timeout: Optional[float] = None,
    ) -> None:
        self._extract_fields(col_index=0)
        self._create_search_params()
        self._load()

    def _extract_fields(self, col_index=0) -> None:
        """Grab the existing fields from the Collection"""
        from pymilvus import Collection
        if not self.col:
            return

        if isinstance(self.col[col_index], Collection):
            schema = self.col[col_index].schema
            for x in schema.fields:
                self.fields.append(x.name)
            # Since primary field is auto-id, no need to track it
            self.fields.remove(self._primary_field)

    def _create_search_params(self, col_index=0) -> None:
        """Generate search params based on the current index type"""
        from pymilvus import Collection
        if not self.col:
            return

        if isinstance(self.col[col_index], Collection) and self.search_params is None:
            index = self._get_index(col_index)
            if index is not None:
                index_type: str = index['index_param']['index_type']
                metric_type: str = index['index_param']['metric_type']
                self.search_params = self.default_search_params[index_type]
                self.search_params['metric_type'] = metric_type

    def _get_index(self, col_index=0) -> Optional[dict[str, Any]]:
        """Return the vector index information if it exists"""
        from pymilvus import Collection
        if not self.col:
            return

        if isinstance(self.col[col_index], Collection):
            for x in self.col[col_index].indexes:
                if x.field_name == self._vector_field:
                    return x.to_dict()
        return None

    def _load(self) -> None:
        """Load the collection if available."""
        from pymilvus import Collection
        # 加载所有的collection
        for i, col in enumerate(self.col):
            if isinstance(col, Collection) and self._get_index(col_index=i) is not None:
                col.load()

    @classmethod
    def from_texts(
        cls,
        texts: List[str],
        embedding: Embeddings,
        metadatas: Optional[List[dict]] = None,
        collection_name: list[str] = None,
        connection_args: dict[str, Any] = DEFAULT_MILVUS_CONNECTION,
        consistency_level: str = 'Session',
        index_params: Optional[dict] = None,
        search_params: Optional[dict] = None,
        drop_old: bool = False,
        no_embedding: bool = False,
        **kwargs: Any,
    ):
        """
        no insert data into milvus, only search from milvus
        """
        vector_db = cls(
            embedding_function=embedding,
            collection_name=collection_name,
            connection_args=connection_args,
            consistency_level=consistency_level,
            index_params=index_params,
            search_params=search_params,
            drop_old=drop_old,
            **kwargs,
        )
        return vector_db

    def similarity_search(
        self,
        query: str,
        k: int = 4,
        param: Optional[dict] = None,
        expr: Optional[str] = None,
        timeout: Optional[int] = None,
        **kwargs: Any,
    ) -> List[Document]:
        """Perform a similarity search against the query string.

        Args:
            query (str): The text to search.
            k (int, optional): How many results to return. Defaults to 4.
            param (dict, optional): The search params for the index type.
                Defaults to None.
            expr (str, optional): Filtering expression. Defaults to None.
            timeout (int, optional): How long to wait before timeout error.
                Defaults to None.
            kwargs: Collection.search() keyword arguments.

        Returns:
            List[Document]: Document results for search.
        """
        res = self.similarity_search_with_score(query=query,
                                                k=k,
                                                param=param,
                                                expr=expr,
                                                timeout=timeout,
                                                **kwargs)
        return [doc for doc, _ in res]

    def similarity_search_by_vector(
        self,
        embedding: List[float],
        k: int = 4,
        param: Optional[dict] = None,
        expr: Optional[str] = None,
        timeout: Optional[int] = None,
        **kwargs: Any,
    ) -> List[Document]:
        """Perform a similarity search against the query string.

        Args:
            embedding (List[float]): The embedding vector to search.
            k (int, optional): How many results to return. Defaults to 4.
            param (dict, optional): The search params for the index type.
                Defaults to None.
            expr (str, optional): Filtering expression. Defaults to None.
            timeout (int, optional): How long to wait before timeout error.
                Defaults to None.
            kwargs: Collection.search() keyword arguments.

        Returns:
            List[Document]: Document results for search.
        """
        res = self.similarity_search_with_score_by_vector(embedding=embedding,
                                                          k=k,
                                                          param=param,
                                                          expr=expr,
                                                          timeout=timeout,
                                                          **kwargs)
        return [doc for doc, _ in res]

    def similarity_search_with_score(
        self,
        query: str,
        k: int = 4,
        param: Optional[dict] = None,
        expr: Optional[str] = None,
        timeout: Optional[int] = None,
        **kwargs: Any,
    ) -> List[Tuple[Document, float]]:
        """Perform a search on a query string and return results with score.

        For more information about the search parameters, take a look at the pymilvus
        documentation found here:
        https://milvus.io/api-reference/pymilvus/v2.2.6/Collection/search().md

        Args:
            query (str): The text being searched.
            k (int, optional): The amount of results to return. Defaults to 4.
            param (dict): The search params for the specified index.
                Defaults to None.
            expr (str, optional): Filtering expression. Defaults to None.
            timeout (int, optional): How long to wait before timeout error.
                Defaults to None.
            kwargs: Collection.search() keyword arguments.

        Returns:
            List[float], List[Tuple[Document, any, any]]:
        """
        if k == 0:
            # pm need to control
            return []
        if not self.col:
            logger.debug('No existing collection to search.')
            return []

        # Embed the query text.
        embedding = self.embedding_func.embed_query(query)

        res = self.similarity_search_with_score_by_vector(embedding=embedding,
                                                          k=k,
                                                          param=param,
                                                          expr=expr,
                                                          timeout=timeout,
                                                          **kwargs)
        return res

    def similarity_search_with_score_by_vector(
        self,
        embedding: List[float],
        k: int = 4,
        param: Optional[dict] = None,
        expr: Optional[str] = None,
        timeout: Optional[int] = None,
        **kwargs: Any,
    ) -> List[Tuple[Document, float]]:
        """Perform a search on a query string and return results with score.

        For more information about the search parameters, take a look at the pymilvus
        documentation found here:
        https://milvus.io/api-reference/pymilvus/v2.2.6/Collection/search().md

        Args:
            embedding (List[float]): The embedding vector being searched.
            k (int, optional): The amount of results to return. Defaults to 4.
            param (dict): The search params for the specified index.
                Defaults to None.
            expr (str, optional): Filtering expression. Defaults to None.
            timeout (int, optional): How long to wait before timeout error.
                Defaults to None.
            kwargs: Collection.search() keyword arguments.

        Returns:
            List[Tuple[Document, float]]: Result doc and score.
        """
        if k == 0:
            # pm need to control
            return []
        if not self.col:
            logger.debug('No existing collection to search.')
            return []

        if param is None:
            param = self.search_params

        # Determine result metadata fields.
        output_fields = self.fields[:]
        output_fields.remove(self._vector_field)

        finally_k = kwargs.pop('k', k)

        ret = []

        for index, one_col in enumerate(self.col):
            search_expr = expr
            if self.col_partition_key[index]:
                # add parttion
                if expr:
                    search_expr = f"{expr} and {self._partition_field}==\"{self.col_partition_key[index]}\""
                else:
                    search_expr = f"{self._partition_field}==\"{self.col_partition_key[index]}\""
            # Perform the search.
            res = one_col.search(
                data=[embedding],
                anns_field=self._vector_field,
                param=param,
                limit=k,
                expr=search_expr,
                output_fields=output_fields,
                timeout=timeout,
                **kwargs,
            )
            # Organize results.
            for result in res[0]:
                meta = {x: result.entity.get(x) for x in output_fields}
                doc = Document(page_content=meta.pop(self._text_field), metadata=meta)
                pair = (doc, result.score)
                ret.append(pair)
            logger.debug(f'MilvusWithPermissionCheck Search {one_col.name} results: {res[0]}')
        ret.sort(key=lambda x: x[1])
        logger.debug(f'MilvusWithPermissionCheck Search all results: {len(ret)}')
        # milvus是分数越小越好，所以直接取前几位就行
        ret = ret[:finally_k]
        logger.debug(f'MilvusWithPermissionCheck Search finally results: {len(ret)}')
        return ret

    @staticmethod
    def _relevance_score_fn(distance: float) -> float:
        """Normalize the distance to a score on a scale [0, 1]."""
        # Todo: normalize the es score on a scale [0, 1]
        return 1 - distance

    def _select_relevance_score_fn(self) -> Callable[[float], float]:
        return self._relevance_score_fn


class ElasticsearchWithPermissionCheck(VectorStore, ABC):
    """
    only search from multi index
    """

    def __init__(
        self,
        elasticsearch_url: str,
        index_name: List[str],
        drop_old: Optional[bool] = False,
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
        self.drop_old = drop_old
        _ssl_verify = ssl_verify or {}
        self.elasticsearch_url = elasticsearch_url
        self.ssl_verify = _ssl_verify
        try:
            self.client = elasticsearch.Elasticsearch(elasticsearch_url, **_ssl_verify)
        except ValueError as e:
            raise ValueError(f'Your elasticsearch client string is mis-formatted. Got error: {e} ')

    def similarity_search(self,
                          query: str,
                          k: int = 4,
                          query_strategy: str = 'match_phrase',
                          must_or_should: str = 'should',
                          **kwargs: Any) -> List[Document]:
        if k == 0:
            # pm need to control
            return []
        docs_and_scores = self.similarity_search_with_score(query,
                                                            k=k,
                                                            query_strategy=query_strategy,
                                                            must_or_should=must_or_should,
                                                            **kwargs)
        documents = [d[0] for d in docs_and_scores]
        return documents

    @staticmethod
    def _relevance_score_fn(distance: float) -> float:
        """Normalize the distance to a score on a scale [0, 1]."""
        # Todo: normalize the es score on a scale [0, 1]
        return distance

    def _select_relevance_score_fn(self) -> Callable[[float], float]:
        return self._relevance_score_fn

    def similarity_search_with_score(self,
                                     query: str,
                                     k: int = 4,
                                     query_strategy: str = 'match_phrase',
                                     must_or_should: str = 'should',
                                     **kwargs: Any) -> List[Tuple[Document, float]]:
        if k == 0:
            # pm need to control
            return []
        assert must_or_should in ['must', 'should'], 'only support must and should.'
        # llm or jiaba extract keywords
        if self.llm_chain:
            keywords_str = self.llm_chain.run(query)
            logger.debug('elasticsearch llm search keywords:', keywords_str)
            try:
                keywords = eval(keywords_str)
                if not isinstance(keywords, list):
                    raise ValueError('Keywords extracted by llm is not list.')
            except Exception:
                keywords = jieba.analyse.extract_tags(query, topK=10, withWeight=False)
        else:
            keywords = jieba.analyse.extract_tags(query, topK=10, withWeight=False)
        keywords = keywords or [query]
        logger.debug(f'finally search keywords: {keywords}')
        match_query = {'bool': {must_or_should: []}}
        for key in keywords:
            match_query['bool'][must_or_should].append({query_strategy: {'text': key}})

        ret = []
        for one_index_name in self.index_name:
            response = self.client_search(self.client, one_index_name, match_query, size=k)
            hits = [hit for hit in response['hits']['hits']]
            for hit in hits:
                ret.append((Document(page_content=hit['_source']['text'],
                                     metadata=hit['_source']['metadata']), hit['_score']))
            logger.debug(
                f'ElasticsearchWithPermissionCheck Search {one_index_name} results: {hits}')
        logger.debug(f'ElasticsearchWithPermissionCheck Search all results: {len(ret)}')
        finally_k = kwargs.pop('finally_k', k)
        ret.sort(key=lambda x: x[1], reverse=True)
        ret = ret[:finally_k]
        logger.debug(f'ElasticsearchWithPermissionCheck Search finally results: {len(ret)}')
        return ret

    def add_texts(
            self,
            texts: Iterable[str],
            metadatas: Optional[List[dict]] = None,
            ids: Optional[List[str]] = None,
            refresh_indices: bool = True,
            **kwargs: Any,
    ) -> List[str]:
        pass

    @classmethod
    def from_texts(
        cls,
        texts: List[str],
        embedding: Embeddings,
        metadatas: Optional[List[dict]] = None,
        ids: Optional[List[str]] = None,
        index_name: Optional[List[str]] = None,
        refresh_indices: bool = True,
        llm: Optional[BaseLLM] = None,
        prompt: Optional[PromptTemplate] = DEFAULT_PROMPT,
        drop_old: Optional[bool] = False,
        **kwargs: Any,
    ):
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
        if llm:
            llm_chain = LLMChain(llm=llm, prompt=prompt)
            vectorsearch = cls(elasticsearch_url,
                               index_name,
                               llm_chain=llm_chain,
                               drop_old=drop_old,
                               **kwargs)
        else:
            vectorsearch = cls(elasticsearch_url, index_name, drop_old=drop_old, **kwargs)

        return vectorsearch

    def client_search(self, client: Any, index_name: str, script_query: Dict, size: int) -> Any:
        version_num = client.info()['version']['number'][0]
        version_num = int(version_num)
        if version_num >= 8:
            response = client.search(index=index_name, query=script_query, size=size)
        else:
            response = client.search(index=index_name, body={'query': script_query, 'size': size})
        return response

    def delete(self, **kwargs: Any) -> None:
        # TODO: Check if this can be done in bulk
        self.client.indices.delete(index=self.index_name)
