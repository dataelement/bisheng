from typing import Optional, List, Dict

from langchain_core.embeddings import Embeddings
from pymilvus import DataType, MilvusException
from pymilvus.orm.connections import connections

from bisheng.common.schemas.rag_schema import RagMetadataFieldSchema
from bisheng.common.services.config_service import settings
from bisheng.core.vectorstore import Milvus

_default_index_params = {"index_type": "HNSW", "metric_type": "L2", "params": {"M": 8, "efConstruction": 64}}

#: element_type strings accepted in ``RagMetadataFieldSchema.kwargs['element_type']``
#: for ``field_type='array_int64'`` (mapped to pymilvus DataType members).
_ARRAY_ELEMENT_TYPE_MAP = {
    'int8': DataType.INT8,
    'int16': DataType.INT16,
    'int32': DataType.INT32,
    'int64': DataType.INT64,
    'float': DataType.FLOAT,
    'double': DataType.DOUBLE,
    'boolean': DataType.BOOL,
    'text': DataType.VARCHAR,
    'varchar': DataType.VARCHAR,
}


def build_array_field_kwargs(schema: RagMetadataFieldSchema) -> dict:
    """Translate ``array_int64`` (and other array_*) kwargs into pymilvus
    ``DataType.ARRAY`` field kwargs.

    ``element_type`` is converted from its string form to the pymilvus
    ``DataType`` member and ``max_capacity`` is passed through unchanged
    (Milvus 2.5 allows 1-4096). The input schema's ``kwargs`` dict is never
    mutated.
    """
    source_kwargs = dict(schema.kwargs or {})
    element_type = source_kwargs.pop('element_type', 'int64')
    pymilvus_element = _ARRAY_ELEMENT_TYPE_MAP.get(str(element_type))
    if pymilvus_element is None:
        # Tolerate callers already passing a DataType member.
        if isinstance(element_type, DataType):
            pymilvus_element = element_type
        else:
            raise ValueError(
                f"unsupported array element_type {element_type!r} for field "
                f"{schema.field_name!r}"
            )
    array_kwargs = dict(source_kwargs)
    array_kwargs['element_type'] = pymilvus_element
    if 'max_capacity' not in array_kwargs:
        raise ValueError(
            f"array field {schema.field_name!r} requires max_capacity in kwargs"
        )
    return array_kwargs


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
            elif schema.field_type.startswith('array_'):
                # e.g. 'array_int64' -> DataType.ARRAY with element_type +
                # max_capacity passthrough (shared SPACE knowledge_ids).
                milvus_metadata_schema[schema.field_name] = {
                    'dtype': DataType.ARRAY,
                    'kwargs': build_array_field_kwargs(schema),
                }

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
