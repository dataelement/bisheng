"""Tenant-scoped SQL checkpoints and bounded Redis leases."""

import json
import threading
from contextlib import ExitStack, contextmanager

from redis.exceptions import LockError, RedisError
from sqlmodel import select

from bisheng.knowledge.docflow.client import DocFlowBusy, DocFlowError
from bisheng.knowledge.domain.models.docflow_job import DocFlowJob


class DocFlowState:
    def __init__(self, tenant_id, session_factory=None, redis=None, storage=None):
        if tenant_id is None:
            raise DocFlowError("DocFlow requires an explicit tenant context")
        self.tenant_id = int(tenant_id)
        if session_factory is None:
            from bisheng.core.database import get_sync_db_session

            session_factory = get_sync_db_session
        self.session_factory = session_factory
        if redis is None:
            from bisheng.core.cache.redis_manager import get_redis_client_sync

            redis = get_redis_client_sync().connection
        self.redis = redis
        self.storage = storage

    def read(self, key):
        with self.session_factory() as session:
            row = session.exec(
                select(DocFlowJob).where(DocFlowJob.id == key, DocFlowJob.tenant_id == self.tenant_id)
            ).first()
            return dict(row.state) if row else {}

    def write(self, key, state, scope="parse"):
        with self.session_factory() as session:
            row = session.exec(
                select(DocFlowJob).where(DocFlowJob.id == key, DocFlowJob.tenant_id == self.tenant_id)
            ).first()
            if row is None:
                row = DocFlowJob(id=key, tenant_id=self.tenant_id, scope=scope, state=state)
            else:
                row.state = dict(state)
            session.add(row)
            session.commit()

    def _storage(self):
        if self.storage is None:
            from bisheng.core.storage.minio.minio_manager import get_minio_storage_sync

            self.storage = get_minio_storage_sync()
        return self.storage

    def load_artifact(self, name):
        storage = self._storage()
        if not storage.object_exists_sync(bucket_name=storage.tmp_bucket, object_name=name):
            return None
        return json.loads(storage.get_object_sync(bucket_name=storage.tmp_bucket, object_name=name))

    def save_artifact(self, key, result):
        name = f"docflow/{self.tenant_id}/{key}.json"
        storage = self._storage()
        storage.put_object_sync(
            bucket_name=storage.tmp_bucket,
            object_name=name,
            file=json.dumps(result, ensure_ascii=False).encode("utf-8"),
            content_type="application/json",
        )
        return name

    @contextmanager
    def lease(self, key, wait=10, global_scope=False):
        scope = "global" if global_scope else str(self.tenant_id)
        lock = self.redis.lock(f"docflow:{{{scope}}}:{key}", timeout=90, blocking_timeout=wait, thread_local=False)
        if not lock.acquire():
            raise DocFlowBusy("DocFlow task is already running; retry after it finishes")
        stopped = threading.Event()
        lost = threading.Event()

        def heartbeat():
            while not stopped.wait(20):
                try:
                    if not lock.extend(90, replace_ttl=True):
                        lost.set()
                        return
                except (RedisError, LockError):
                    lost.set()
                    return

        def check():
            if lost.is_set() or not lock.owned():
                raise DocFlowError("DocFlow lease lost; aborting stale task")

        worker = threading.Thread(target=heartbeat, daemon=True)
        worker.start()
        try:
            yield check
            check()
        finally:
            stopped.set()
            worker.join(timeout=2)
            if lock.owned():
                lock.release()

    @contextmanager
    def capacity(self, account, maximum):
        # Shared by all tenants/workers using the same remote account. A slot is
        # held through polling, rather than allowing an unbounded remote backlog.
        with ExitStack() as stack:
            for index in range(maximum):
                try:
                    owned = stack.enter_context(self.lease(f"slot:{account}:{index}", wait=0, global_scope=True))
                except DocFlowBusy:
                    continue
                yield owned
                return
            raise DocFlowBusy("DocFlow account concurrency limit reached; retry later")
