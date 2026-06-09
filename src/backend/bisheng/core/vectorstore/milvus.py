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
from typing import Any

from langchain_milvus import Milvus as _LangchainMilvus
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
