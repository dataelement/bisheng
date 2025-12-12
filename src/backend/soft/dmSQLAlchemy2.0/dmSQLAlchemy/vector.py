import os
import enum
import sqlalchemy
import uuid
import contextlib
import logging
import decimal
from dataclasses import dataclass
from typing import Optional, Any, Dict, Tuple, Type, Generator, Iterable, List, Union
from sqlalchemy import types, text, literal_column, String, Column, Text, JSON, DateTime, create_engine, inspect
from sqlalchemy.orm import declarative_base, Session

MAX_DIM = 65535
MIN_DIM = 1

logger = logging.getLogger()

class BreakLoop(Exception):
    pass

def encode_vector(value, dim=None):
    import numpy
    if value is None:
        return value

    if dim is not None and len(value) != dim:
        raise ValueError(f"expected {dim} dimensions, but got {len(value)}")

    if isinstance(value, numpy.ndarray):
        if value.ndim != 1:
            raise ValueError("expected ndim to be 1")
        return f"[{','.join(map(str, value))}]"

    return str(value)

def decode_vector(value: str):
    import numpy
    if value is None:
        return value

    if value == "[]":
        return numpy.array([], dtype=numpy.float32)

    return numpy.array(value[1:-1].split(","), dtype=numpy.float32)

class DistanceMetric(enum.Enum):
    DOT = "DOT"
    COSINE = "COSINE"
    HAMMING = "HAMMING"
    EUCLIDEAN = "EUCLIDEAN"
    MANHATTAN = "MANHATTAN"
    EUCLIDEAN_SQUARED = "EUCLIDEAN_SQUARED"

    def to_sql_func(self):
        if self in DistanceMetric:
            return self.value
        else:
            raise ValueError("Unsupported distance metric")

class VECTORTYPE(types.UserDefinedType):
    __visit_name__ = 'VECTOR'

class VECTOR(VECTORTYPE):
    cache_ok = True

    dim: Optional[int]
    def __init__(self, dim: Optional[int] = None, format: str = None):
        if dim is not None and not isinstance(dim, int):
            raise ValueError("Dimension must be of type integer or None")

        if dim is not None and (dim < MIN_DIM or dim > MAX_DIM):
            raise ValueError(f"The range of dimension values is from {MIN_DIM} to {MAX_DIM}")

        if format is None:
            format = 'FLOAT32'
        else:
            format = format.upper()
        if format not in ['INT8', 'FLOAT32', 'FLOAT64']:
            raise ValueError(f"Unsupported Type by DM, format must be within the  range of INT8,FLOAT32,FLOAT64")

        if dim is None and format is not None:
            raise ValueError(f"Unsupported by DM")

        super(types.UserDefinedType, self).__init__()
        self.dim = dim
        self.format = format

    def get_col_spec(self, **kw):
        if self.dim is None:
            return "VECTOR"
        return f"VECTOR({self.dim})"

    def bind_processor(self, dialect):

        def process(value):
            return encode_vector(value, self.dim)

        return process

    def result_processor(self, dialect, coltype):

        def process(value):
            return decode_vector(value)

        return process

    class comparator_factory(types.UserDefinedType.Comparator):

        def l1_distance(self, other):
            formatted_other = encode_vector(other)
            with_sign_str = "TO_VECTOR('" + formatted_other + "', " + str(self.type.dim) + ", " + self.type.format + ")"
            return sqlalchemy.func.L1_DISTANCE(self, literal_column(with_sign_str)).label(
                "L1_DISTANCE"
            )

        def l2_distance(self, other):
            formatted_other = encode_vector(other)
            with_sign_str = "TO_VECTOR('" + formatted_other + "', " + str(self.type.dim) + ", " + self.type.format + ")"
            return sqlalchemy.func.L2_DISTANCE(self, literal_column(with_sign_str)).label(
                "L2_DISTANCE"
            )

        def cosine_distance(self, other):
            formatted_other = encode_vector(other)
            with_sign_str = "TO_VECTOR('" + formatted_other + "', " + str(self.type.dim) + ", " + self.type.format + ")"
            return sqlalchemy.func.COSINE_DISTANCE(self, literal_column(with_sign_str)).label(
                "COSINE_DISTANCE"
            )

        def inner_product(self, other):
            formatted_other = encode_vector(other)
            with_sign_str = "TO_VECTOR('" + formatted_other + "', " + str(self.type.dim) + ", " + self.type.format + ")"
            return sqlalchemy.func.INNER_PRODUCT(self, literal_column(with_sign_str)).label(
                "INNER_PRODUCT"
            )

        def hamming_distance(self, other):
            formatted_other = encode_vector(other)
            with_sign_str = "TO_VECTOR('" + formatted_other + "', " + str(self.type.dim) + ", " + self.type.format + ")"
            return sqlalchemy.func.HAMMING_DISTANCE(self, literal_column(with_sign_str)).label(
                "HAMMING_DISTANCE"
            )

        def inner_product_negative(self, other):
            formatted_other = encode_vector(other)
            with_sign_str = "TO_VECTOR('" + formatted_other + "', " + str(self.type.dim) + ", " + self.type.format + ")"
            return sqlalchemy.func.INNER_PRODUCT_NEGATIVE(self, literal_column(with_sign_str)).label(
                "INNER_PRODUCT_NEGATIVE"
            )

class VectorAdaptor:

    engine: sqlalchemy.engine

    def __init__(self, engine: sqlalchemy.engine):
        self.engine = engine

    def _check_vector_column(self, column: sqlalchemy.Column):
        if not isinstance(column.type, VECTOR):
            raise ValueError("Not a vector column")

    def has_vector_index(self, conn, owner, table_name, column_name) -> bool:

        query = text(f"SELECT column_name, table_name FROM ALL_IND_COLUMNS "
                     f"WHERE TABLE_OWNER = :owner AND TABLE_NAME = :table_name AND "
                     f"COLUMN_NAME = :column_name").bindparams(owner = owner, table_name = table_name, column_name = column_name)
        result = conn.execute(query)
        result_dict = result.mappings().all()
        for row in result_dict:
            if conn.dialect.denormalize_name(row["column_name"]) == column_name and conn.dialect.denormalize_name(row['table_name']) == table_name:
                return True
        return False

    def create_vector_ivf_index(
        self,
        column: sqlalchemy.Column,
        skip_existing: bool = False,
        metric_name: str = "COSINE",
        index_name: str = None,
        percentage_value: int = 90,
        num_of_partitions: int = None,
    ):
        self._check_vector_column(column)

        if column.type.dim is None:
            raise ValueError(
                "Vector index is only supported for fixed dimension vectors"
            )

        conn = self.engine.connect()
        owner = conn.dialect.denormalize_name(conn.dialect.default_schema_name)
        table_name = conn.dialect.denormalize_name(column.table.name)
        column_name = conn.dialect.denormalize_name(column.name)

        if skip_existing:
            if self.has_vector_index(conn, owner, table_name, column_name):
                return

        index_name = conn.dialect.denormalize_name(conn.dialect.identifier_preparer.quote(index_name or
            f"ivf_ind_{column.name}"
        ))

        query_str = f"CREATE VECTOR INDEX \"%(index_name)s\" on \"%(table_name)s\"(\"%(column_name)s\") ORGANIZATION PARTITIONS\n"\
            "DISTANCE %(metric_name)s WITH TARGET ACCURACY %(percentage_value)s"

        if num_of_partitions is not None:
            query_str += "PARAMETERS(TYPE IVF, NEIGHBOR PARTITIONS " + str(num_of_partitions) + ");"
        metric_name = DistanceMetric(metric_name.upper())

        query_text = query_str % {'index_name' : index_name, 'table_name' : table_name,
                                  'column_name' : column_name,
                                'metric_name' : metric_name.to_sql_func(), 'percentage_value' : percentage_value}
        conn.execute(text(query_text))
        return

    def create_vector_hnsw_index(
        self,
        column: sqlalchemy.Column,
        skip_existing: bool = False,
        metric_name: str = "COSINE",
        index_name: str = None,
        percentage_value: int = 90,
        max_connection: int = None,
        ef_construction: int = None,
    ):
        self._check_vector_column(column)

        if column.type.dim is None:
            raise ValueError(
                "Vector index is only supported for fixed dimension vectors"
            )

        conn = self.engine.connect()
        owner = conn.dialect.denormalize_name(conn.dialect.default_schema_name)
        table_name = conn.dialect.denormalize_name(column.table.name)
        column_name = conn.dialect.denormalize_name(column.name)

        if skip_existing:
            if self.has_vector_index(conn, owner, table_name, column_name):
                return

        index_name = conn.dialect.denormalize_name(conn.dialect.identifier_preparer.quote(index_name or
            f"hnsw_ind_{column.name}"
        ))

        query_str = f"CREATE VECTOR INDEX \"%(index_name)s\" on \"%(table_name)s\"(\"%(column_name)s\") ORGANIZATION GRAPH\n"\
            "DISTANCE %(metric_name)s WITH TARGET ACCURACY %(percentage_value)s"

        if max_connection is not None or ef_construction is not None:
            if max_connection is not None:
                query_str += "PARAMETERS(TYPE HNSW, NEIGHBOR " + str(max_connection)
                if ef_construction is not None:
                    query_str += ", EFCONSTRUCTION " + str(ef_construction) + ");"
                else:
                    query_str += ");"
            else:
                query_str += "PARAMETERS(TYPE HNSW, EFCONSTRUCTION " + str(ef_construction) + ");"
        metric_name = DistanceMetric(metric_name.upper())
        query_text = query_str % {'index_name' : index_name, 'table_name' : table_name, 'column_name' : column_name,
                                  'metric_name' : metric_name.to_sql_func(), 'percentage_value' : percentage_value}
        conn.execute(text(query_text))

        return

    def _check_index_match(self, conn, schema_name, table_name, column_name, index_name):
        query_str = "SELECT index_name FROM ALL_IND_COLUMNS WHERE TABLE_OWNER = :owner AND TABLE_NAME = :table_name AND COLUMN_NAME = :column_name;"
        result = conn.execute(
            text(query_str).bindparams(owner = schema_name, table_name = table_name, column_name = column_name))
        if result.rowcount == 0:
            raise ValueError("There is no index on this vector column")

        for row_dict in result:
            if index_name != conn.dialect.denormalize_name(row_dict[0]):
                raise ValueError("Incorrect index name or column information input")
            else:
                return conn.dialect.denormalize_name(row_dict[0])

    def rebuild_vector_ivf_index(self,
                                 column: sqlalchemy.Column = None,
                                 schema_name: str = None,
                                 index_name: str = None,
                                 metric_name: str = None,
                                 target_accuracy: int = None,
                                 cluster_centers: int = None,
    ):
        if column is None and index_name is None:
            raise ValueError(
                "At least column information or index name is required"
            )

        if column is not None:
            self._check_vector_column(column)

        conn = self.engine.connect()
        schema_name = conn.dialect.denormalize_name(schema_name or conn.dialect.default_schema_name)
        index_name = conn.dialect.denormalize_name(index_name)
        table_name_an = conn.dialect.denormalize_name(column.table.name)
        column_name = conn.dialect.denormalize_name(column.name)

        if column is not None:
            index_name = self._check_index_match(conn, schema_name, table_name_an, column_name, index_name)

        query_str = ("CALL SP_REBUILD_VECTOR_IVFFLAT_INDEX(:schema_name, :index_name, "
                     ":metric_name, :target_accuracy, :cluster_centers);")

        conn.execute(text(query_str).bindparams(schema_name = schema_name, index_name = index_name, metric_name = metric_name,
                                                target_accuracy = target_accuracy, cluster_centers = cluster_centers))

        return

    def rebuild_vector_hnsw_index(self,
                                  column: sqlalchemy.Column = None,
                                  schema_name: str = None,
                                  index_name: str = None,
                                  metric_name: str = None,
                                  percentage_value: int = None,
                                  max_connection: int = None,
                                  ef_construction: int = None
    ):
        if column is None and index_name is None:
            raise ValueError(
                "At least column information or index name is required"
            )

        if column is not None:
            self._check_vector_column(column)

        conn = self.engine.connect()
        schema_name = conn.dialect.denormalize_name(schema_name or conn.dialect.default_schema_name)
        index_name = conn.dialect.denormalize_name(index_name)
        table_name_an = conn.dialect.denormalize_name(column.table.name)
        column_name = conn.dialect.denormalize_name(column.name)

        if column is not None:
            index_name = self._check_index_match(conn, schema_name, table_name_an, column_name, index_name)

        query_str = ("CALL SP_REBUILD_VECTOR_HNSW_INDEX(:schema_name, :index_name, "
                     ":metric_name, :percentage_value, :max_connection, :ef_construction);")

        conn.execute(text(query_str).bindparams(schema_name = schema_name, index_name = index_name, metric_name = metric_name,
                                                percentage_value = percentage_value, max_connection = max_connection, ef_construction = ef_construction))

        return

@dataclass
class QueryResult:
    id: str
    document: str
    metadata: dict
    distance: float

def _create_vector_table_model(
    table_name: str,
    dim: Optional[int] = None,
) -> Tuple[Type[declarative_base], Type]:

    BaseOrm = declarative_base()

    class VectorTableModel(BaseOrm):

        __tablename__ = table_name
        id = Column(
            String(36), primary_key=True, default=lambda: str(uuid.uuid4())
        )
        embedding = Column(
            VECTOR(dim),
            nullable=False,
        )
        document = Column(Text, nullable=True)
        meta = Column(JSON, nullable=True)
        create_time = Column(
            DateTime, server_default=text("CURRENT_TIMESTAMP")
        )
        update_time = Column(
            DateTime,
            server_default=text(
                "CURRENT_TIMESTAMP"
            ),
        )

    return BaseOrm, VectorTableModel

class VectorWordSeek:
    def __init__(
            self,
            connection_str: str = None,
            table_name: str = None,
            vector_dim: Optional[int] = None,
            drop_if_existing: bool = False,
            model = None,
            model_path: str = None,
            engine_args: Optional[Dict[str, Any]] = None,
            **kwargs: Any
    ):
        super().__init__(**kwargs)
        self._conn_str = connection_str
        self._table_name = table_name
        self._vector_dim = vector_dim
        self._drop_if_existing = drop_if_existing
        self._engine_args = engine_args if engine_args else {}
        self._engine = self._create_engine()
        self._model = model
        self._model_path = model_path
        self._vector_col_name = 'embedding'
        self._check_model_dim()
        self._check_table_compatibility()

        self._orm_base, self._table_model = _create_vector_table_model(
            self._table_name, self._vector_dim
        )

    def _create_engine(self) -> sqlalchemy.engine.Engine:
        return create_engine(url=self._conn_str, **self._engine_args)

    def _check_table_compatibility(self) -> None:
        if self._drop_if_existing:
            return

        conn = self._engine.connect()
        schema_name = conn.dialect.denormalize_name(conn.dialect.default_schema_name)
        table_name = conn.dialect.denormalize_name(self._table_name)

        if(conn.dialect.has_table(conn, table_name, schema_name) is False):
            return

        inspector = inspect(self._engine)
        columns = inspector.get_columns(table_name)

        if columns is None or len(columns) != 6:
            raise ValueError(
                "The existing table named" + table_name + "does not match the table to be created"
            )

        try:
            for row_dict in columns:
                if row_dict['name'] not in ['id', 'embedding', 'document', 'meta', 'create_time', 'update_time']:
                    raise BreakLoop
                if row_dict['name'] == 'id':
                    if row_dict['type'].python_type != str or row_dict['type'].length < decimal.Decimal('36'):
                        raise BreakLoop
                if row_dict['name'] == 'embedding':
                    if type(row_dict['type']) != VECTOR or row_dict['type'].dim != self._vector_dim or row_dict['type'].format != 'FLOAT32':
                        raise BreakLoop
        except BreakLoop:
            raise ValueError(
                "The existing table named " + table_name + " does not match the table to be created"
            )

    def _check_model_dim(self):
        if self._model is not None:
            dimension = self._model.get_sentence_embedding_dimension()
        elif self._model_path is not None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self._model_path)
            dimension = self._model.get_sentence_embedding_dimension()
        else:
            raise ValueError("No model has been loaded, model needs to be provided")

        if self._vector_dim is None:
            self._vector_dim = dimension

        if self._vector_dim != dimension:
            raise ValueError(
                "The dimension of model does not match the dimension of the table"
            )

    def create_table(self, drop_if_existing):
        if drop_if_existing:
            self.drop_table()
        with Session(self._engine) as session, session.begin():
            self._orm_base.metadata.create_all(session.get_bind())

    def drop_table(self) -> None:
        with Session(self._engine) as session, session.begin():
            self._orm_base.metadata.drop_all(session.get_bind())

    @contextlib.contextmanager
    def _make_session(self) -> Generator[Session, None, None]:
        yield Session(self._engine)

    def insert(
        self,
        texts: Iterable[str],
        metadatas: Optional[List[dict]] = None,
        ids: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> List[str]:
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')
        else:
            model = self._model
        if ids is None:
            ids = [str(uuid.uuid4()) for _ in texts]
        if not metadatas:
            metadatas = [{} for _ in texts]

        embeddings = [model.encode(document).flatten().tolist() for document in texts]

        with Session(self._engine) as session:
            for document, metadata, embedding, id_val in zip(texts, metadatas, embeddings, ids):
                embeded_doc = self._table_model(
                    id=id_val,
                    embedding=embedding,
                    document=document,
                    meta=metadata,
                )
                session.add(embeded_doc)
            session.commit()

        return ids

    def delete(
        self,
        ids: Optional[List[str]] = None,
        filter: Optional[dict] = None,
        **kwargs: Any,
    ) -> None:
        filter_by = self._build_filter_clause(filter)
        with Session(self._engine) as session:
            if ids is not None:
                filter_by = sqlalchemy.and_(self._table_model.id.in_(ids), filter_by)
            stmt = sqlalchemy.delete(self._table_model).filter(filter_by)
            session.execute(stmt)
            session.commit()

    def query(
        self,
        DistanceMetric: List[float],
        query_vector: List[float],
        count: int = 5,
        filter: Optional[dict] = None,
        **kwargs: Any,
    ) -> List[QueryResult]:
        relevant_docs = self._vector_search(DistanceMetric, query_vector, count, filter, **kwargs)

        return [
            QueryResult(
                document=doc.document,
                metadata=doc.meta,
                id=doc.id,
                distance=doc.distance,
            )
            for doc in relevant_docs
        ]

    def get_distance_func(self, distance_metric):
        if distance_metric == "DOT":
            return self._table_model.embedding.inner_product
        elif distance_metric == "COSINE":
            return self._table_model.embedding.cosine_distance
        elif distance_metric == "HAMMING":
            return self._table_model.embedding.hamming_distance
        elif distance_metric == "EUCLIDEAN":
            return self._table_model.embedding.l2_distance
        elif distance_metric == "MANHATTAN":
            return self._table_model.embedding.l1_distance
        elif distance_metric == "EUCLIDEAN_SQUARED":
            return self._table_model.embedding.inner_product_negative
        elif distance_metric is None:  # default to cosine
            return self._table_model.embedding.cosine_distance
        else:
            raise ValueError(
                f"Got unexpected value for distance: {distance_metric}. "
            )

    def _change_to_vector(self, query):
        if type(query) == tuple or type(query) == list:
            if len(query) != 1 or type(query[0]) != str:
                raise ValueError(
                    f"Got unexpected value : {query}. "
                )
            else:
                query = query[0]
        elif type(query) != str:
            raise ValueError(
                f"Got unexpected value : {query}. "
            )

        if self._model is None:
            from sentence_transformers import SentenceTransformer
            model = SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')
        else:
            model = self._model

        return model.encode(query).flatten().tolist()

    def _vector_search(
        self,
        distance_metric,
        query_embedding: str,
        k: int = 5,
        filter: Optional[Dict[str, str]] = None,
        **kwargs: Any,
    ) -> List[Any]:

        post_filter_enabled = kwargs.get("post_filter_enabled", False)
        post_filter_multiplier = kwargs.get("post_filter_multiplier", 1)

        embedding_vector = self._change_to_vector(query_embedding)

        with Session(self._engine) as session:
            if post_filter_enabled is False or not filter:
                filter_by = self._build_filter_clause(filter)
                results = (
                    session.query(
                        self._table_model.id,
                        self._table_model.meta,
                        self._table_model.document,
                        self.get_distance_func(distance_metric)(embedding_vector).label("distance"),
                    )
                    .filter(filter_by)
                    .order_by(sqlalchemy.asc("distance"))
                    .limit(k)
                    .all()
                )
            else:
                subquery = (
                    session.query(
                        self._table_model.id,
                        self._table_model.meta,
                        self._table_model.document,
                        self.get_distance_func(distance_metric)(embedding_vector).label("distance"),
                    )
                    .order_by(sqlalchemy.asc("distance"))
                    .limit(post_filter_multiplier * k * 10)
                    .subquery()
                )
                filter_by = self._build_filter_clause(filter, subquery.c)
                results = (
                    session.query(
                        subquery.c.id,
                        subquery.c.meta,
                        subquery.c.document,
                        subquery.c.distance,
                    )
                    .filter(filter_by)
                    .order_by(sqlalchemy.asc(subquery.c.distance))
                    .limit(k)
                    .all()
                )
        return results

    def _build_filter_clause(
        self,
        filters: Optional[Dict[str, Any]] = None,
        table_model: Optional[Any] = None,
    ) -> Any:

        if table_model is None:
            table_model = self._table_model

        filter_by = sqlalchemy.true()
        if filters is not None:
            filter_clauses = []

            for key, value in filters.items():
                if key.lower() == "$and":
                    and_clauses = [
                        self._build_filter_clause(condition, table_model)
                        for condition in value
                        if isinstance(condition, dict) and condition is not None
                    ]
                    filter_by_metadata = sqlalchemy.and_(*and_clauses)
                    filter_clauses.append(filter_by_metadata)
                elif key.lower() == "$or":
                    or_clauses = [
                        self._build_filter_clause(condition, table_model)
                        for condition in value
                        if isinstance(condition, dict) and condition is not None
                    ]
                    filter_by_metadata = sqlalchemy.or_(*or_clauses)
                    filter_clauses.append(filter_by_metadata)
                elif key.lower() in [
                    "$in",
                    "$nin",
                    "$gt",
                    "$gte",
                    "$lt",
                    "$lte",
                    "$eq",
                    "$ne",
                ]:
                    raise ValueError(
                        f"Got unexpected filter expression: {filter}. "
                        f"Operator {key} must be followed by a meta key. "
                    )
                elif isinstance(value, dict):
                    filter_by_metadata = self._create_filter_clause(
                        table_model, key, value
                    )

                    if filter_by_metadata is not None:
                        filter_clauses.append(filter_by_metadata)
                else:
                    filter_by_metadata = (
                        sqlalchemy.func.json_extract(table_model.meta, f"$.{key}")
                        == value
                    )
                    filter_clauses.append(filter_by_metadata)

            filter_by = sqlalchemy.and_(filter_by, *filter_clauses)
        return filter_by

    def _create_filter_clause(self, table_model, key, value):
        IN, NIN, GT, GTE, LT, LTE, EQ, NE = (
            "$in",
            "$nin",
            "$gt",
            "$gte",
            "$lt",
            "$lte",
            "$eq",
            "$ne",
        )

        json_key = sqlalchemy.func.json_extract(table_model.meta, f"$.{key}")
        value_case_insensitive = {k.lower(): v for k, v in value.items()}

        if IN in map(str.lower, value):
            filter_by_metadata = json_key.in_(value_case_insensitive[IN])
        elif NIN in map(str.lower, value):
            filter_by_metadata = ~json_key.in_(value_case_insensitive[NIN])
        elif GT in map(str.lower, value):
            filter_by_metadata = json_key > value_case_insensitive[GT]
        elif GTE in map(str.lower, value):
            filter_by_metadata = json_key >= value_case_insensitive[GTE]
        elif LT in map(str.lower, value):
            filter_by_metadata = json_key < value_case_insensitive[LT]
        elif LTE in map(str.lower, value):
            filter_by_metadata = json_key <= value_case_insensitive[LTE]
        elif NE in map(str.lower, value):
            filter_by_metadata = json_key != value_case_insensitive[NE]
        elif EQ in map(str.lower, value):
            filter_by_metadata = json_key == value_case_insensitive[EQ]
        else:
            logger.warning(
                f"Unsupported filter operator: {value}. Consider using "
                "one of $in, $nin, $gt, $gte, $lt, $lte, $eq, $ne, $or, $and."
            )
            filter_by_metadata = None

        return filter_by_metadata

    def execute(self, sql: str, params: Optional[dict] = None, autocommit:bool = False) -> dict:
        try:
            with Session(self._engine) as session, session.begin():
                result = session.execute(sqlalchemy.text(sql), params)
                if autocommit:
                    session.commit()  # Ensure changes are committed for non-SELECT statements.
                if sql.strip().lower().startswith("select"):
                    return {"success": True, "result": result.fetchall(), "error": None}
                else:
                    return {"success": True, "result": result, "error": None}
        except Exception as e:
            # Log the error or handle it as needed
            logger.error(f"SQL execution error: {str(e)}")
            return {"success": False, "result": None, "error": str(e)}

class VectorImageSeek(VectorWordSeek):
    def __init__(
            self,
            connection_str: str = None,
            table_name: str = None,
            vector_dim: Optional[int] = None,
            drop_if_existing: bool = False,
            model = None,
            model_path: str = None,
            engine_args: Optional[Dict[str, Any]] = None,
            **kwargs: Any
    ):
        super().__init__(connection_str, table_name, vector_dim, drop_if_existing, model, model_path, engine_args, **kwargs)
        self._set_preprocess()

    def _set_preprocess(self):
        import torch
        from torchvision import transforms

        preprocess = transforms.Compose([
            transforms.Resize(256),
            transforms.CenterCrop(224),
            transforms.ToTensor(),
            transforms.Normalize(
                mean=[0.485, 0.456, 0.406],
                std=[0.229, 0.224, 0.225]
            )
        ])

        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        resnet = self._model.to(device)
        self._device = device
        self._resnet = resnet
        self._preprocess = preprocess

    def _check_model_dim(self):
        import torch
        test_input = torch.randn(1, 3, 256, 256)
        if self._model is not None:
            output = self._model(test_input).squeeze()
            dimension = output.shape[0]
        elif self._model_path is not None:
            device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            model = torch.jit.load(self._model_path, map_location=device)
            output = model(test_input).squeeze()
            dimension = output.shape[0]
        else:
            raise ValueError("No model has been loaded, model needs to be provided")

        self._model = model

        if self._vector_dim is None:
            self._vector_dim = dimension

        if self._vector_dim != dimension:
            raise ValueError(
                "The dimension of model does not match the dimension of the table"
            )

    def check_and_return_path(self, path):
        if type(path) is not str:
            raise ValueError("The dimension of model does not match the dimension of the table")
        else:
            if os.path.exists(path):
                if os.path.isfile(path) and path.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.pgm', '.pbm')):
                    abs_path = os.path.abspath(path)
                    return [abs_path]
                elif os.path.isdir(path):
                    return [os.path.join(os.path.abspath(path), f)
                                 for f in os.listdir(path)
                                 if f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.bmp', '.pgm', '.pbm'))]
            else:
                raise ValueError(
                    "Path " + path + " does not exists"
                )

    def analyze_input_path(self, path_query):
        path_list = []
        if type(path_query) == tuple or type(path_query) == list:
            for path in path_query:
                path_list += self.check_and_return_path(path)
        elif type(path_query) == str:
            path_list = self.check_and_return_path(path_query)

        return path_list

    def extract_features(self, img_paths):
        import torch
        from PIL import Image

        features = []
        for path in img_paths:
            img = Image.open(path).convert("RGB")
            img_tensor = self._preprocess(img).unsqueeze(0)

            img_tensor = img_tensor.to(self._device)

            with torch.no_grad():
                feature = self._resnet(img_tensor)

            # 转为NumPy数组并压缩为1D向量
            features.append(feature.cpu().numpy().flatten().tolist())

        return features

    def insert(
        self,
        paths: Iterable[str],
        metadatas: Optional[List[dict]] = None,
        ids: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> List[str]:

        path_list = self.analyze_input_path(paths)
        embeddings = self.extract_features(path_list)
        if ids is None:
            ids = [str(uuid.uuid4()) for _ in path_list]
        if not metadatas:
            metadatas = [{} for _ in path_list]

        with Session(self._engine) as session:
            for document, metadata, embedding, id_val in zip(path_list, metadatas, embeddings, ids):
                embeded_doc = self._table_model(
                    id=id_val,
                    embedding=embedding,
                    document=document,
                    meta=metadata,
                )
                session.add(embeded_doc)
            session.commit()

        return ids

    def _change_to_vector(self, query):
        if type(query) == tuple or type(query) == list:
            if len(query) != 1 or type(query[0]) != str:
                raise ValueError(
                    f"Got unexpected value : {query}. "
                )
            else:
                query = query[0]
        elif type(query) != str:
            raise ValueError(
                f"Got unexpected value : {query}. "
            )

        path_list = self.analyze_input_path(query)

        if path_list is None or len(path_list) == 0:
            raise ValueError(
                f"No images of the specified type were retrieved at the specified path: {query}, only png, jpg, jpeg, gif, bmp, pgm, pbm image types are supported. "
            )
        elif len(path_list) > 1:
            raise ValueError(
                f"There are multiple images in specified path : {query}. "
            )
        return self.extract_features(path_list)[0]



