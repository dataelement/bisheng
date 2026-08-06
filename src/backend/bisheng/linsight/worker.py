import argparse
import asyncio
import logging
import pickle
import socket
import uuid
from functools import partial
from multiprocessing import Manager, Process, set_start_method
from multiprocessing.managers import ValueProxy
from typing import Any, Union

from bisheng.common.services.config_service import settings
from bisheng.core.cache.redis_conn import RedisClient
from bisheng.core.cache.redis_manager import get_redis_client_sync
from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.core.logger import set_logger_config
from bisheng.linsight.domain.models.linsight_session_version import (
    LinsightSessionVersionDao,
    SessionVersionStatusEnum,
)
from bisheng.linsight.domain.task_exec import LinsightWorkflowTask

logger = logging.getLogger(__name__)

# Session-version statuses that are terminal: a queue item pointing at such a
# session must be discarded (never run / never resumed). Used by the worker's
# pre-flight non-terminal guard so a stale resume payload cannot revive a task
# that was terminated/completed/failed during its park (waiting) period.
_TERMINAL_SESSION_STATUSES = frozenset(
    {
        SessionVersionStatusEnum.COMPLETED,
        SessionVersionStatusEnum.FAILED,
        SessionVersionStatusEnum.SOP_GENERATION_FAILED,
        SessionVersionStatusEnum.TERMINATED,
    }
)


def encode_queue_item(
    session_version_id: str,
    resume: bool = False,
    user_input: Any = None,
    continue_question: str | None = None,
    tenant_id: int | None = None,
) -> dict:
    """Build a Linsight queue item.

    park-and-release uses JSON-shaped dict items so a resume pick-up can be told
    apart from a fresh task. ``resume=True`` items carry the user's answer and are
    lpush'd to the head of the queue by the /workbench/user-input endpoint so the
    parked task continues ahead of newly-queued tasks (PRD §4.4.4).

    ``continue_question`` (F035 multi-turn) carries a follow-up user turn for an
    already-finished conversation: the worker feeds it as a new HumanMessage into
    the SAME thread (thread_id = session_version_id) so the agent keeps prior
    context. Distinct from ``resume`` (which answers a parked ask_user interrupt).
    """
    item = {
        "session_version_id": session_version_id,
        "resume": resume,
        "user_input": user_input,
        "continue_question": continue_question,
    }
    if tenant_id is not None:
        item["tenant_id"] = tenant_id
    return item


def parse_queue_item(raw: Any) -> dict:
    """Normalise a raw queue item into ``{session_version_id, resume, user_input, continue_question}``.

    Backward compatible: a bare ``session_version_id`` string (the legacy queue
    format) is treated as a new task (``resume=False``).
    """
    if isinstance(raw, dict):
        return {
            "session_version_id": raw.get("session_version_id"),
            "resume": bool(raw.get("resume", False)),
            "user_input": raw.get("user_input"),
            "continue_question": raw.get("continue_question"),
            "tenant_id": raw.get("tenant_id"),
        }
    # Legacy bare-string item == new task.
    return {
        "session_version_id": raw,
        "resume": False,
        "user_input": None,
        "continue_question": None,
        "tenant_id": None,
    }


def _item_session_version_id(raw: Any) -> str | None:
    """Extract the session_version_id from a queue item (dict or legacy string)."""
    return parse_queue_item(raw)["session_version_id"]


def _item_is_resume(raw: Any) -> bool:
    return parse_queue_item(raw)["resume"]


class NodeManager:
    _instance = None

    def __init__(self, redis_client, node_id, fga_manager=None):
        # generate unique node ID
        self.node_id = node_id
        self.redis: RedisClient = redis_client
        self.fga_manager = fga_manager
        self.heartbeat_key = f"linsight:node:heartbeat:{self.node_id}"
        # Heartbeat interval (seconds)
        self.interval = 5
        # Redis key expiration time (seconds)
        self.ttl = 15

    @classmethod
    def get_instance(cls, node_id, fga_manager=None):
        if not cls._instance:
            redis_client = get_redis_client_sync()
            cls._instance = cls(redis_client, node_id, fga_manager)
        elif fga_manager is not None:
            cls._instance.fga_manager = fga_manager
        return cls._instance

    async def start_heartbeat(self):
        """Start the heartbeat task to indicate node liveness"""
        logger.info(f"Starting heartbeat for node: {self.node_id}")
        while True:
            try:
                # set heartbeat key with expiration
                await self.redis.aset(self.heartbeat_key, "1", expiration=self.ttl)
                if self.fga_manager is not None:
                    healthy = await self.fga_manager.heartbeat()
                    if not healthy:
                        raise RuntimeError("Linsight F048 runtime heartbeat is not ready")
            except Exception as e:
                logger.error(f"Heartbeat failed: {e}")
            await asyncio.sleep(self.interval)

    async def register_task_ownership(self, session_version_id):
        """Register task ownership to this node"""
        key = f"linsight:task:owner:{session_version_id}"
        # Set the node ID as the owner of the task with a TTL
        await self.redis.aset(key, self.node_id, expiration=86400)  # 1 day expiration

    async def release_task_ownership(self, session_version_id):
        """Release task ownership"""
        key = f"linsight:task:owner:{session_version_id}"
        await self.redis.adelete(key)

    async def is_node_alive(self, target_node_id):
        """Check if a target node is alive based on its heartbeat"""
        if not target_node_id:
            return False
        key = f"linsight:node:heartbeat:{target_node_id}"
        exists = await self.redis.aexists(key)
        return exists > 0


# LinsightQueue queue
class LinsightQueue:
    def __init__(self, name, namespace, redis):
        self.__db: RedisClient = redis
        self.key = f"{namespace}:{name}"

    async def qsize(self):
        return await self.__db.allen(self.key)  # Back to queuelistNumber of inner elements

    async def put(self, data, timeout=None):
        await self.__db.arpush(self.key, data, expiration=timeout)  # Add a new element to the far right of the queue

    async def put_head(self, data, timeout=None):
        # Add a new element to the far LEFT (head) of the queue so it is picked
        # up before any tail-queued task. Used by park-and-release for resume
        # items (PRD §4.4.4: an answered task continues ahead of new tasks).
        # RedisClient.alpush does not pickle, but ablpop/lrange unpickle, so we
        # must pickle here to keep the queue's serialization uniform with put().
        payload = pickle.dumps(data) if not isinstance(data, bytes) else data
        await self.__db.alpush(self.key, payload, expiration=timeout)

    async def get_wait(self, timeout=None):
        # Returns the first element of the queue, if empty, wait until an element is queued (the timeout threshold istimeout, if isNonehas been waiting)
        item = await self.__db.ablpop(self.key, timeout=timeout)
        return item

    async def get_nowait(self):
        # Returns the first element of the queue directly, if the queue is emptyNone
        item = await self.__db.alpop(self.key)
        return item

    # Get the position of a task's data in the queue
    async def index(self, session_version_id):
        """
        Get the queue position of a task addressed by its session_version_id.

        Position semantics (C1, consumed by frontend Track H): the returned
        1-based index counts ONLY new (resume=False) tasks ahead of the target,
        because resume items are lpush'd to the head to jump the queue and must
        NOT inflate other users' perceived wait position. A resume item itself
        has no queue position (returns 0). Items are addressed by
        session_version_id, tolerating both dict and legacy bare-string entries.

        :param session_version_id: the session_version_id to locate
        :return: 1-based position among new tasks; 0 if not found / not a new task
        """
        items = await self.__db.alrange(self.key)
        position = 0
        for item in items:
            if _item_is_resume(item):
                # Resume items jump the queue; they don't count toward position.
                continue
            position += 1
            if _item_session_version_id(item) == session_version_id:
                return position
        return 0

    # Delete a task data
    async def remove(self, session_version_id):
        """
        Delete all queue items (new or resume) for a session_version_id.

        Addresses items by session_version_id so callers (e.g. terminate) need
        not reconstruct the exact payload. Tolerates legacy bare-string entries.
        """
        items = await self.__db.alrange(self.key)
        for item in items:
            if _item_session_version_id(item) == session_version_id:
                await self.__db.alrem(self.key, item)


class ScheduleCenterProcess(Process):
    def __init__(
        self,
        max_concurrency: ValueProxy | None = None,
        node_id: ValueProxy | None = None,
    ):
        """
        Dispatch Center Process
        :param max_concurrency: Maximum number of concurrent tasks allowed per process
        """
        super().__init__()
        self.daemon = True
        self.queue: LinsightQueue | None = None
        # Semaphores
        self.semaphore: asyncio.Semaphore | None = None
        self.node_manager: NodeManager | None = None
        self.heartbeat_task: asyncio.Task | None = None
        self.repair_tasks: set[asyncio.Task] = set()
        self.max_concurrency: Union[int, ValueProxy] | None = max_concurrency
        self.node_id: ValueProxy | None = node_id

    def handle_task_result(self, task: asyncio.Task, session_version_id: str | None = None):
        try:
            task.result()  # Re-raise task exceptions in the callback.
        except Exception as e:
            logger.exception("Task failed with exception: %s", e)
            # task_exec owns the normal failure path; reaching here means it could
            # not record a terminal status (its own handler raised, the worker was
            # cancelled, ...). Without this net the session stays IN_PROGRESS and
            # the frontend spins on it forever.
            if session_version_id:
                repair_task = asyncio.create_task(self._force_fail_stranded_session(session_version_id, e))
                repair_tasks = getattr(self, "repair_tasks", None)
                if repair_tasks is None:
                    repair_tasks = self.repair_tasks = set()
                repair_tasks.add(repair_task)
                repair_task.add_done_callback(repair_tasks.discard)
        finally:
            # Release semaphore
            if self.semaphore:
                logger.info("Releasing semaphore after task completion.")
                self.semaphore.release()

    async def _force_fail_stranded_session(self, session_version_id: str, error: BaseException) -> None:
        """Last-resort terminal write for a task that died without recording one.

        Deliberately re-reads the session and gives up when it is already
        terminal: task_exec's own failure path is richer (it emits the classified
        error event and fails the sub-tasks), so this must never overwrite what
        that path already wrote. Tenant filter is bypassed for the same reason as
        ``_session_is_terminal`` — the standalone worker holds no tenant context.
        """
        try:
            with bypass_tenant_filter():
                session = await LinsightSessionVersionDao.get_by_id(session_version_id)
                if session is None or session.status in _TERMINAL_SESSION_STATUSES:
                    return
                try:
                    from bisheng.common.services.llm_error_classifier import classify_for_event

                    classified = classify_for_event(error)
                    error_type, error_code, detail = (
                        classified.error_type,
                        classified.error_code,
                        classified.detail,
                    )
                except Exception:  # classification is a nicety, the terminal write is not
                    error_type, error_code, detail = "unknown", None, str(error)
                session.status = SessionVersionStatusEnum.FAILED
                session.output_result = {
                    "error_message": f"Task aborted unexpectedly: {error}",
                    "error_code": error_code,
                    "error_type": error_type,
                    "detail": detail,
                }
                await LinsightSessionVersionDao.insert_one(session)
            logger.warning(
                f"Force-failed stranded session {session_version_id} (task died before recording a terminal status)"
            )
        except Exception:
            logger.exception("Failed to force-fail stranded session %s", session_version_id)

    def _release_semaphore(self):
        """Release the concurrency slot once, guarding against over-release."""
        if self.semaphore and self.semaphore._value < self.max_concurrency:
            self.semaphore.release()

    async def _session_is_terminal(self, session_version_id: str) -> bool | None:
        """Pre-flight guard: is the session terminal (or missing)?

        Returns True if terminal, None if the session does not exist, False if
        the task may run/resume. park-and-release relies on this so a stale
        resume payload (e.g. the task was terminated during its park) does not
        revive a finished task — the worker discards such items (design §4.6).
        Tenant filter is bypassed because the standalone worker has no admin
        tenant context (it is restored per-task inside task_exec).
        """
        with bypass_tenant_filter():
            session = await LinsightSessionVersionDao.get_by_id(session_version_id)
        if session is None:
            return None
        return session.status in _TERMINAL_SESSION_STATUSES

    async def process_one_item(self) -> bool:
        """Pick one queue item and dispatch it. Assumes a concurrency slot is
        already held by the caller.

        Returns True if a task coroutine was spawned (the slot will be released
        later by ``handle_task_result`` once the task finishes OR parks at an
        interrupt); False if no task was spawned (empty queue / terminal /
        missing session) — in which case the slot is released here immediately.
        """
        node_manager = self.node_manager or NodeManager.get_instance(self.node_id.value)

        raw_item = await self.queue.get_wait()
        if raw_item is None:
            logger.info("No item found in queue, waiting...")
            self._release_semaphore()
            return False

        item = parse_queue_item(raw_item)
        session_version_id = item["session_version_id"]
        if not session_version_id:
            logger.error(f"Malformed queue item discarded: {raw_item!r}")
            self._release_semaphore()
            return False

        # Pre-flight non-terminal guard (design §4.6): discard items that point
        # at a finished/terminated/missing session so a parked task cannot be
        # revived after the user terminated it.
        terminal = await self._session_is_terminal(session_version_id)
        if terminal is None:
            logger.warning(f"Queue item for missing session {session_version_id} discarded")
            self._release_semaphore()
            return False
        if terminal:
            logger.info(f"Queue item for terminal session {session_version_id} discarded")
            self._release_semaphore()
            return False

        # Register task ownership
        await node_manager.register_task_ownership(session_version_id)

        exec_task = LinsightWorkflowTask()
        tenant_kwargs = {"tenant_id": item["tenant_id"]} if item.get("tenant_id") is not None else {}
        if item.get("continue_question") is not None:
            logger.info(
                f"Continuing conversation session_version_id: {session_version_id} on node {node_manager.node_id}"
            )
            task = asyncio.create_task(
                exec_task.async_continue(
                    session_version_id,
                    question=item["continue_question"],
                    **tenant_kwargs,
                )
            )
        elif item["resume"]:
            logger.info(f"Resuming session_version_id: {session_version_id} on node {node_manager.node_id}")
            task = asyncio.create_task(
                exec_task.async_resume(
                    session_version_id,
                    user_input=item["user_input"],
                    **tenant_kwargs,
                )
            )
        else:
            logger.info(f"Processing session_version_id: {session_version_id} on node {node_manager.node_id}")
            task = asyncio.create_task(exec_task.async_run(session_version_id, **tenant_kwargs))

        # When the task finishes OR parks (interrupt -> coroutine returns), the
        # done callback releases the slot. park-and-release therefore frees the
        # concurrency slot the moment the agent parks for user input — no slot
        # is held during the (possibly very long) waiting period.
        task.add_done_callback(partial(self.handle_task_result, session_version_id=session_version_id))
        return True

    async def async_run(self):
        """
        Asynchronous Run Method for Process
        :return:
        """
        logger.info("ScheduleCenterProcess started...")

        while True:
            await self.semaphore.acquire()  # Acquire semaphore, limit concurrency
            try:
                await self.process_one_item()
            except Exception as e:
                logger.error(f"Error in ScheduleCenterProcess: {e}")
                self._release_semaphore()
                continue

    def run(self):
        """
        Run Process
        :return:
        """

        set_logger_config(settings.logger_conf)

        if self.max_concurrency is not None:
            self.max_concurrency = self.max_concurrency.value  # Dapatkan ValueProxy Actual value
        else:
            self.max_concurrency = 32
            logger.warning("No max_concurrency provided, using default value of 32.")

        self.semaphore = asyncio.Semaphore(self.max_concurrency)
        logger.info(f"Semaphore initialized with max concurrency: {self.semaphore._value}")

        redis_client = get_redis_client_sync()
        self.queue = LinsightQueue("queue", namespace="linsight", redis=redis_client)

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        if settings.openfga.enabled:
            from bisheng.api.services.f048_permission_runtime import (
                initialize_f048_worker_runtime,
            )
            from bisheng.core.context import initialize_app_context
            from bisheng.department.domain.services.department_projection_scope import (
                get_department_projection_scope,
                register_department_projection_runtime_context,
            )
            from bisheng.permission.application.process_runtime import (
                register_f048_permission_runtime_context,
            )

            loop.run_until_complete(initialize_app_context(settings, instance_role="linsight"))

            async def initialize(client):
                return await initialize_f048_worker_runtime(
                    client,
                    external_scopes={
                        "department": get_department_projection_scope(),
                    },
                )

            register_f048_permission_runtime_context(initialize)
            register_department_projection_runtime_context()

        # 启动心跳
        self.node_manager = NodeManager.get_instance(
            self.node_id.value,
            fga_manager=None,
        )
        self.heartbeat_task = loop.create_task(self.node_manager.start_heartbeat())

        # 启动主逻辑
        for _ in range(10000):  # 你的原始逻辑
            try:
                loop.run_until_complete(self.async_run())
            except Exception as e:
                logger.error(f"Unhandled exception in main loop: {e}")
        from bisheng.core.context import close_app_context

        loop.run_until_complete(close_app_context())
        loop.close()


def start_schedule_center_process(
    worker_num: int = 4,
    max_concurrency: ValueProxy | None = None,
    node_id: ValueProxy | None = None,
):
    """

    Start Schedule Center Process Workers
    :param worker_num: Number of worker processes to start
    :param max_concurrency: Maximum number of concurrent tasks allowed per process
    :return:

    Args:
        node_id:
    """
    logger.info(f"Starting {worker_num} ScheduleCenterProcess workers...")
    if worker_num <= 0:
        logger.error("worker_num must be greater than 0")
        return
    processes = []
    for _ in range(worker_num):
        process = ScheduleCenterProcess(max_concurrency, node_id)
        process.start()
        logger.info(f"Started ScheduleCenterProcess with PID: {process.pid}")
        processes.append(process)

    logger.info(f"Started {len(processes)} ScheduleCenterProcess workers successfully.")
    return processes


if __name__ == "__main__":
    set_start_method("spawn", force=True)  # make sure that people are using the spawn Method Starts a New Process

    parser = argparse.ArgumentParser()
    parser.add_argument("--worker_num", type=int, default=4, help="Number of processes, defaults to4")
    # Maximum number of concurrency for a single process
    parser.add_argument(
        "--max_concurrency",
        type=int,
        default=32,
        help="Maximum number of concurrency for a single process, defaults to32",
    )

    args = parser.parse_args()

    process_manager = Manager()

    node_id = process_manager.Value("s", f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}")

    max_concurrency = process_manager.Value("i", args.max_concurrency)

    # Check for incomplete tasks and terminate
    from bisheng.linsight.domain.utils import check_and_terminate_incomplete_tasks

    asyncio.run(check_and_terminate_incomplete_tasks(node_id.value))

    try:
        processes = start_schedule_center_process(
            worker_num=args.worker_num, max_concurrency=max_concurrency, node_id=node_id
        )
        if processes:
            for p in processes:
                p.join()  # Wait for all processes to end
    except KeyboardInterrupt:
        logger.info("ScheduleCenterProcess interrupted by user.")
        logger.info("Stopping ScheduleCenterProcess workers...")
