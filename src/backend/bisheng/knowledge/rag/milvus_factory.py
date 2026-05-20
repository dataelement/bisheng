from typing import Optional, List, Dict

from langchain_core.embeddings import Embeddings
from pymilvus import DataType, MilvusException
from pymilvus.orm.connections import connections

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

        milvus_kwargs = dict(
            embedding_function=embedding_function,
            collection_name=collection_name,
            connection_args=connection_args,
            auto_id=True,
            index_params=_default_index_params,
            metadata_schema=milvus_metadata_schema,
            **kwargs
        )
        try:
            return Milvus(**milvus_kwargs)
        except MilvusException as exc:
            if not MilvusFactory._is_closed_channel_error(exc):
                raise
            connections.disconnect(MilvusFactory._get_connection_alias(connection_args))
            return Milvus(**milvus_kwargs)

    @staticmethod
    def _is_closed_channel_error(exc: MilvusException) -> bool:
        return "Cannot invoke RPC on closed channel" in str(exc)

    @staticmethod
    def _get_connection_alias(connection_args: dict) -> str:
        if connection_args.get("alias"):
            return connection_args["alias"]

        uri = connection_args.get("uri") or "http://localhost:19530"
        db_name = connection_args.get("db_name", "")
        user = connection_args.get("user", "")
        token = connection_args.get("token", "")
        auth = user
        if not auth and token:
            import hashlib

            md5 = hashlib.new("md5", usedforsecurity=False)
            md5.update(token.encode())
            auth = md5.hexdigest()

        return "-".join(str(value) for value in (uri, db_name, auth) if value)
