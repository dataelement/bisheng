"""按批重试 OpenFGA 失败元组, Redis 锁与数据库租约一起续期。

领取时预扣尝试次数, 进程中断也计入 max_retries 预算。
成功标记 succeeded, 耗尽标记 dead; 同一元组按入队顺序执行。
"""

from __future__ import annotations

import logging

from bisheng.worker.main import bisheng_celery

logger = logging.getLogger(__name__)

LOCK_KEY = "bisheng:lock:retry_failed_tuples"
LOCK_TTL = 60  # seconds — must be > typical execution time


@bisheng_celery.task(acks_late=True)
def retry_failed_tuples():
    """Retry pending failed tuple operations."""
    _retry_failed_tuples_sync()


def _retry_failed_tuples_sync() -> None:
    from datetime import datetime
    from threading import Event, Thread
    from uuid import uuid4

    from bisheng.core.context.tenant import bypass_tenant_filter
    from bisheng.core.database import get_sync_db_session
    from bisheng.core.openfga.manager import get_fga_client
    from bisheng.permission.domain.repositories.implementations.failed_tuple_repository_impl import (
        FailedTupleRepositoryImpl,
    )

    redis = _get_redis()
    if redis is None:
        raise RuntimeError("OpenFGA retry lock unavailable")
    connection = redis.connection
    owner = uuid4().hex
    if not connection.set(LOCK_KEY, owner, nx=True, ex=LOCK_TTL):
        return
    stopped, lost = Event(), Event()
    renew_script = (
        "if redis.call('get',KEYS[1]) == ARGV[1] then return redis.call('expire',KEYS[1],ARGV[2]) end return 0"
    )
    release_script = "if redis.call('get',KEYS[1]) == ARGV[1] then return redis.call('del',KEYS[1]) end return 0"

    def guard():
        if lost.is_set() or not connection.eval(renew_script, 1, LOCK_KEY, owner, LOCK_TTL):
            raise RuntimeError("OpenFGA retry lock lost")

    def heartbeat():
        while not stopped.wait(20):
            try:
                guard()
                with bypass_tenant_filter(), get_sync_db_session() as session:
                    FailedTupleRepositoryImpl(session).renew(owner, datetime.utcnow())
                    session.commit()
            except Exception:
                logger.exception("OpenFGA retry lease renewal failed")
                lost.set()
                return

    thread = Thread(target=heartbeat, daemon=True)
    thread.start()
    try:
        fga = get_fga_client()
        if fga is None:
            raise RuntimeError("FGAClient not available")
        with bypass_tenant_filter(), get_sync_db_session() as session:
            items = FailedTupleRepositoryImpl(session).claim(owner, datetime.utcnow())
            session.commit()
        # 每个元组只领取最早未完成操作; 不把后来的删除越过早先失败的写入。
        outcomes = {}
        for tenant_id, action in sorted({(item.tenant_id, item.action) for item in items}):
            group = [item for item in items if item.tenant_id == tenant_id and item.action == action]
            for start in range(0, len(group), 20):
                batch = group[start : start + 20]
                guard()
                values = [{"user": i.fga_user, "relation": i.relation, "object": i.object} for i in batch]
                try:
                    if action not in {"write", "delete"}:
                        raise ValueError("unknown tuple action")
                    fga.write_tuples_sync(**{("writes" if action == "write" else "deletes"): values})
                    outcomes.update({item.id: None for item in batch})
                except Exception:
                    logger.warning("OpenFGA retry batch failed; isolating %d items", len(batch), exc_info=True)
                    for item, value in zip(batch, values):
                        guard()
                        try:
                            if action not in {"write", "delete"}:
                                raise ValueError("unknown tuple action")
                            fga.write_tuples_sync(**{("writes" if action == "write" else "deletes"): [value]})
                            outcomes[item.id] = None
                        except Exception as exc:
                            message = str(exc)[:500]
                            outcomes[item.id] = None if _is_idempotent_tuple_error(action, message) else message
                guard()
                with bypass_tenant_filter(), get_sync_db_session() as session:
                    FailedTupleRepositoryImpl(session).settle(owner, outcomes, datetime.utcnow())
                    session.commit()
                outcomes.clear()
    finally:
        stopped.set()
        thread.join(timeout=1)
        connection.eval(release_script, 1, LOCK_KEY, owner)


def _get_redis():
    """Get RedisClient. Returns None if unavailable."""
    try:
        from bisheng.core.cache.redis_manager import get_redis_client_sync

        return get_redis_client_sync()
    except Exception:
        logger.exception("OpenFGA retry Redis unavailable")
        return None


def _is_idempotent_tuple_error(action: str, error_msg: str) -> bool:
    text = error_msg.lower()
    if action == "write":
        return "already exists" in text or "cannot write a tuple which already exists" in text
    if action == "delete":
        return "does not exist" in text or "did not exist" in text or "tuple to be deleted did not exist" in text
    return False
