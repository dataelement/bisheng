"""pymilvus 2.6 compatibility wrapper for langchain-milvus.

langchain-milvus 0.3.x connects to Milvus via the new ``MilvusClient`` whose
``_using`` alias (``cm-<id>``) is only a *legacy-compat label* — pymilvus 2.6 does
**not** register an ORM ``connections`` entry under it. Yet langchain-milvus still
reads collection metadata through the ORM ``Collection(using=self.alias)`` in its
``col`` property (e.g. ``_extract_fields`` during ``__init__``), which raises
``ConnectionNotExistException: should create connection first`` for any existing
collection.

This wrapper registers a real ORM connection — stable per (uri, db) so it is reused
across instances rather than leaked per ``MilvusClient`` — and repoints ``self.alias``
to it the first time ``col`` is accessed. ``self.alias`` is only consumed by the ORM
``col`` path (MilvusClient operations use ``self.client`` independently), so repointing
it is safe and fixes every ``self.col`` access at once.

Remove this shim once langchain-milvus reads collections via ``MilvusClient`` instead
of the deprecated ORM ``Collection`` API.
"""

import threading
from collections.abc import Callable
from typing import Any

from langchain_milvus import Milvus as _LangchainMilvus
from loguru import logger
from pymilvus import connections

_ORM_CONNECT_KEYS = ("uri", "host", "port", "user", "password", "token", "db_name", "secure")


class Milvus(_LangchainMilvus):
    _orm_lock = threading.Lock()

    def __init__(self, *args: Any, connection_args: dict | None = None, **kwargs: Any):
        # Set before super().__init__: `col` (and thus this override) is invoked during
        # the parent constructor via `_extract_fields`.
        self._bisheng_conn_args = dict(connection_args or {})
        self._bisheng_orm_ready = False
        super().__init__(*args, connection_args=connection_args, **kwargs)

    def _ensure_orm_connection(self) -> str:
        """Register (once) and return a stable ORM connection alias for this endpoint."""
        ca = self._bisheng_conn_args
        alias = f"bisheng_orm::{ca.get('uri') or ca.get('host')}::{ca.get('db_name', '')}"
        with self._orm_lock:
            if not connections.has_connection(alias):
                connect_args = {k: v for k, v in ca.items() if k in _ORM_CONNECT_KEYS}
                connections.connect(alias=alias, **connect_args)
        return alias

    @property
    def col(self):
        if not self._bisheng_orm_ready:
            self.alias = self._ensure_orm_connection()
            self._bisheng_orm_ready = True
        return _LangchainMilvus.col.fget(self)

    @col.setter
    def col(self, value) -> None:
        _LangchainMilvus.col.fset(self, value)

    def _ensure_fields_loaded(self) -> None:
        """Repopulate ``self.fields`` if it was never extracted from the collection.

        ``self.fields`` is a one-shot snapshot taken at ``__init__``/``_init`` time
        and drives which metadata keys survive ``_prepare_insert_list`` (keys not in
        ``self.fields`` are silently dropped). langchain-milvus only re-extracts the
        snapshot inside ``_init``, which runs *only when the collection is absent*.

        Under concurrent first-time uploads to a new knowledge base, every worker
        except the one that wins the schema-creation race constructs its instance
        while the collection still does not exist, leaving ``self.fields`` empty.
        Once a peer creates the collection, those waiting instances never refresh —
        so their inserts drop every metadata field (including the non-nullable
        ``document_id``), fail, and strand the file in a terminal FAILED state.

        Refresh the snapshot here whenever it is empty but the collection now
        exists. Best-effort: a failure to read the schema must not block the insert
        (the absent collection / genuine error paths are handled downstream).
        """
        if self.fields:
            return
        try:
            if self.client.has_collection(self.collection_name):
                self._extract_fields()
        except Exception:
            # Non-critical: leave fields as-is and let the normal insert path
            # surface any real schema/connection error.
            logger.warning(
                "milvus _ensure_fields_loaded failed for collection={}; proceeding without field refresh",
                self.collection_name,
                exc_info=True,
            )

    def add_texts(self, *args: Any, **kwargs: Any) -> list[str]:
        self._ensure_fields_loaded()
        return super().add_texts(*args, **kwargs)

    async def aadd_texts(self, *args: Any, **kwargs: Any) -> list[str]:
        self._ensure_fields_loaded()
        return await super().aadd_texts(*args, **kwargs)

    def _select_relevance_score_fn(self) -> Callable[[float], float]:
        try:
            return super()._select_relevance_score_fn()
        except ValueError as exc:
            if "No index params provided" not in str(exc):
                raise

        metric_type = "L2"
        if self.index_params:
            index_params = self._as_list(self.index_params)
            if len(index_params) == 1:
                metric_type = index_params[0].get("metric_type") or metric_type

        if metric_type in {"IP", "COSINE"}:
            return lambda score: (score + 1) / 2.0
        return lambda distance: 1 - distance / 4.0
