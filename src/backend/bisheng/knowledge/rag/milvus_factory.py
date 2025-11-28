from typing import Optional, List, Dict

from langchain_core.embeddings import Embeddings
from pymilvus import DataType

from bisheng.common.schemas.rag_schema import RagMetadataFieldSchema
from bisheng.common.services.config_service import settings
from bisheng.core.vectorstore import Milvus

_default_index_params = {"index_type": "HNSW", "metric_type": "L2", "params": {"M": 8, "efConstruction": 64}}


class MilvusFactory:

    @staticmethod
    def init_vectorstore(collection_name: str, embedding_function: Embeddings, **kwargs) -> Milvus:
        conf = settings.get_vectors_conf().milvus
        connection_args = conf.connection_args.copy()
        if connection_args.get('host') and connection_args.get('port'):
            uri = f"http://{connection_args.pop('host')}:{connection_args.pop('port')}"
            connection_args['uri'] = uri

        metadata_schemas: Optional[List[RagMetadataFieldSchema]] = kwargs.pop('metadata_schemas', None)

        milvus_metadata_schema: Optional[Dict[str, any]] = None

        for schema in metadata_schemas or []:
            if milvus_metadata_schema is None:
                milvus_metadata_schema = {}
            schema_kwargs = schema.kwargs or {}
            if schema.field_type == 'text':
                milvus_metadata_schema[schema.field_name] = {'dtype': DataType.VARCHAR,
                                                             "kwargs": schema_kwargs}
            elif schema.field_type == 'int8':
                milvus_metadata_schema[schema.field_name] = {'dtype': DataType.INT8, "kwargs": schema_kwargs}
            elif schema.field_type == 'int16':
                milvus_metadata_schema[schema.field_name] = {'dtype': DataType.INT16, "kwargs": schema_kwargs}
            elif schema.field_type == 'int32':
                milvus_metadata_schema[schema.field_name] = {'dtype': DataType.INT32, "kwargs": schema_kwargs}
            elif schema.field_type == 'int64':
                milvus_metadata_schema[schema.field_name] = {'dtype': DataType.INT64, "kwargs": schema_kwargs}
            elif schema.field_type == 'float':
                milvus_metadata_schema[schema.field_name] = {'dtype': DataType.FLOAT, "kwargs": schema_kwargs}
            elif schema.field_type == 'double':
                milvus_metadata_schema[schema.field_name] = {'dtype': DataType.DOUBLE, "kwargs": schema_kwargs}
            elif schema.field_type == 'json':
                milvus_metadata_schema[schema.field_name] = {'dtype': DataType.JSON, "kwargs": schema_kwargs}
            elif schema.field_type == 'boolean':
                milvus_metadata_schema[schema.field_name] = {'dtype': DataType.BOOL, "kwargs": schema_kwargs}

        return Milvus(
            embedding_function=embedding_function,
            collection_name=collection_name,
            connection_args=connection_args,
            auto_id=True,
            index_params=_default_index_params,
            metadata_schema=milvus_metadata_schema,
            **kwargs
        )
