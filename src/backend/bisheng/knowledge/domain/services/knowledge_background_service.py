"""默认队列只推进发布/清理状态, 内容修复仍由投影链路交给解析 worker。"""

import asyncio
import json
import time
from datetime import datetime, timedelta
from typing import NoReturn
from uuid import uuid4

from loguru import logger

from bisheng.core.context.tenant import bypass_tenant_filter, current_tenant_id
from bisheng.core.database import get_async_db_session
from bisheng.knowledge.domain.repositories.implementations.knowledge_background_repository_impl import (
    KnowledgeBackgroundRepositoryImpl as Repository,
)
from bisheng.utils.task_dispatch import run_sync_dispatch


class _PublishedProjectionStopped(RuntimeError):
    """下游终止或等待超时，应保留诊断并停止自动发布重试。"""


class KnowledgeBackgroundService:
    async def repository_call(self, method, *args, **kwargs):
        async with get_async_db_session() as session:
            result = await session.run_sync(lambda sync: getattr(Repository(sync), method)(*args, **kwargs))
            await session.commit()
            return result

    async def drain(self, limit: int = 100) -> dict:
        with bypass_tenant_filter():
            refs = await self.repository_call("due", limit)
        outcomes = {}
        deadline = time.monotonic() + 600
        for job_id, tenant_id in refs:
            if deadline - time.monotonic() < 125:
                break
            outcomes[job_id] = await self.process(job_id, tenant_id)
        return outcomes

    async def process(self, job_id: str, tenant_id: int) -> str:
        token = current_tenant_id.set(tenant_id)
        owner = uuid4().hex
        try:
            job = await self.repository_call("claim", job_id, owner, datetime.now())
            if job is None:
                return "not_due"
            payload = dict(job.payload)
            try:
                handler = getattr(self, f"_{job.kind}")
                status = await asyncio.wait_for(handler(job, owner, payload), timeout=120)
                error = "child_operation_exhausted" if status == "dead" else None
            except _PublishedProjectionStopped as exc:
                status, error = "dead", str(exc)[:1000]
                logger.warning("auto publish projection stopped job_id={} detail={}", job.id, error)
            except Exception as exc:
                status = "dead" if job.attempts >= Repository.MAX_ATTEMPTS else "pending"
                error = f"{type(exc).__name__}:{exc}"[:1000]
                logger.exception("knowledge background operation failed kind={} id={}", job.kind, job.id)
            settled = await self.repository_call("settle", job.id, owner, status=status, payload=payload, error=error)
            return status if settled else "lease_lost"
        finally:
            current_tenant_id.reset(token)

    async def _checkpoint(self, job, owner, payload):
        if not await self.repository_call("settle", job.id, owner, status="processing", payload=payload):
            raise RuntimeError("background operation lease lost")

    @staticmethod
    def _wait(payload):
        deadline = payload.setdefault("wait_deadline", (datetime.now() + timedelta(hours=2)).isoformat())
        if datetime.now() >= datetime.fromisoformat(deadline):
            raise RuntimeError("projection_wait_expired")
        return "waiting"

    async def _auto_publish(self, job, owner, payload):
        from bisheng.knowledge.domain.services.auto_publish_service import AutoPublishService

        if "projection_ids" not in payload:
            # 有原命令时必须按该命令校验, 不能拿其他目标的已发布入口代替。
            existing = (
                []
                if "publish_context" in payload
                else await self.repository_call(
                    "existing_auto_publish_projections",
                    payload["file_id"],
                )
            )
            if existing:
                # 发布事务可能已提交而结果登记前进程中断, 从持久化入口恢复等待阶段。
                payload["projection_ids"] = existing
            else:

                async def save_publish_context(context):
                    payload["publish_context"] = context
                    await self._checkpoint(job, owner, payload)

                result = await AutoPublishService.execute(
                    file_id=payload["file_id"],
                    tenant_id=job.tenant_id,
                    publish_context=payload.get("publish_context"),
                    save_publish_context=save_publish_context,
                )
                if result.skipped:
                    payload["skip_reason"] = result.skip_reason
                    return "skipped"
                payload["projection_ids"] = [result.manager_file_id, result.publish_entry_id]
            await self._checkpoint(job, owner, payload)
        from bisheng.knowledge.rag.shared_space_storage import get_shared_storage_conf

        ids = payload["projection_ids"]
        entries = await self.repository_call("files", ids)
        document_id = payload.get("projection_document_id") or payload.get("publish_context", {}).get("document_id")
        if document_id is None and entries:
            document_id = entries[0].reference_document_id
            payload["projection_document_id"] = document_id
        if Repository.projections_ready(entries, ids, job.tenant_id, document_id):
            return "done"
        by_id = {entry.id: entry for entry in entries}
        details = [
            {
                "file_id": file_id,
                "document_id": entry.reference_document_id,
                "status": entry.projection_status,
                "entry_status": entry.entry_status,
                "attempts": int(entry.projection_retry_count or 0),
                "error": entry.projection_last_error,
            }
            if (entry := by_id.get(file_id)) is not None
            else {"file_id": file_id, "error": "entry_missing"}
            for file_id in ids
        ]

        def stop(reason: str) -> NoReturn:
            payload["projection_failure"] = {"reason": reason, "entries": details}
            raise _PublishedProjectionStopped(
                "published_projection_" + reason + ":" + json.dumps(details, ensure_ascii=False)
            )

        if len(set(ids)) != 2 or set(by_id) != set(ids):
            stop("missing")
        if any(
            entry.deleted_at is not None
            or entry.entry_status in {"deleting", "invalid"}
            or entry.tenant_id != job.tenant_id
            or entry.reference_document_id != document_id
            or entry.reference_document_id is None
            for entry in entries
        ):
            stop("unavailable")
        max_attempts = int(get_shared_storage_conf().projection_max_retries)
        if any(
            entry.projection_status == "failed"
            and (
                int(entry.projection_retry_count or 0) >= max_attempts
                or str(entry.projection_last_error or "").startswith("retry_exhausted:")
                or "document_content_rebuild_budget_exhausted" in str(entry.projection_last_error or "")
            )
            for entry in entries
        ):
            stop("exhausted")
        try:
            return self._wait(payload)
        except RuntimeError:
            stop("wait_expired")

    async def _container(self, job, owner, payload):
        folders = await self.repository_call("files", [payload["folder_id"]])
        if folders and (
            folders[0].deleted_at is None
            or folders[0].deleted_at.replace(microsecond=0).isoformat() != payload["deleted_at"]
        ):
            return "skipped"
        if not payload.get("enumerated"):
            async with get_async_db_session() as session:

                def page(sync):
                    repo = Repository(sync)
                    entries = repo.container_entries(
                        space_id=payload["space_id"], prefix=payload["prefix"], after_id=payload.get("cursor", 0)
                    )
                    for entry in entries:
                        repo.request(
                            tenant_id=job.tenant_id,
                            kind="container_entry",
                            identity=f"{job.id}:{entry.id}",
                            parent_id=job.id,
                            payload={"entry_id": entry.id, "container": dict(payload)},
                        )
                    return [entry.id for entry in entries]

                ids = await session.run_sync(page)
                if ids:
                    payload["cursor"] = ids[-1]
                payload["enumerated"] = len(ids) < 100
                if not await session.run_sync(
                    lambda sync: Repository(sync).settle(job.id, owner, status="processing", payload=payload)
                ):
                    raise RuntimeError("container lease lost")
                await session.commit()
            if not payload["enumerated"]:
                return "waiting"
        statuses = await self.repository_call("children_statuses", job.id)
        if any(status == "dead" for status in statuses):
            return "dead"
        return "done" if all(status in {"done", "skipped"} for status in statuses) else "waiting"

    async def _container_entry(self, job, owner, payload):
        from bisheng.worker.knowledge.document_projection import (
            _build_distribution_cleanup_service,
            enqueue_document_projection_entries,
        )

        container = payload["container"]
        folders = await self.repository_call("files", [container["folder_id"]])
        if folders and (
            folders[0].deleted_at is None
            or folders[0].deleted_at.replace(microsecond=0).isoformat() != container["deleted_at"]
        ):
            return "skipped"
        entries = await self.repository_call("files", [payload["entry_id"]])
        if not entries:
            return "done"
        entry = entries[0]
        # 回收已完成本容器的删除决策, 保留文件及关系等待还原或到期。
        if entry.deleted_at is not None:
            return "done"
        path = str(entry.file_level_path or "")
        prefix = container["prefix"]
        if int(entry.knowledge_id) != int(container["space_id"]) or not (path == prefix or path.startswith(prefix + "/")):
            return "skipped"
        if not payload.get("cleanup_requested") and entry.entry_status != "deleting":
            async with get_async_db_session() as session:
                service = await _build_distribution_cleanup_service(session)
                outcome = await service.cleanup_entry(entry)
                if outcome.action.value in {"failed", "skipped"}:
                    raise RuntimeError(outcome.error or "entry_cleanup_not_started")
            payload["cleanup_requested"] = True
            await self._checkpoint(job, owner, payload)
        await run_sync_dispatch(enqueue_document_projection_entries,tenant_id=job.tenant_id, entry_ids=[entry.id])
        return self._wait(payload)

    async def _delete_file(self, job, owner, payload):
        from bisheng.api.services.knowledge_imp import _artifact_owned_object_name, _knowledge_file_owned_object_names
        from bisheng.core.ai import FakeEmbeddings
        from bisheng.core.storage.minio.minio_manager import get_minio_storage
        from bisheng.knowledge.domain.knowledge_rag import KnowledgeRag
        from bisheng.knowledge.domain.models.knowledge import Knowledge

        # 意图可先于源删除提交; 只在源行确实消失后执行, 防止回滚或恢复后误删。
        if await self.repository_call("files", [payload["file_id"]]):
            return self._wait(payload)
        if payload.get("knowledge") is None:
            raise RuntimeError("deletion_storage_snapshot_missing")
        knowledge = Knowledge.model_validate(payload["knowledge"])
        completed = payload.setdefault("completed_stages", [])
        file_id = payload["file_id"]
        if knowledge.type != 3:
            for stage in ("milvus", "es"):
                if stage in completed:
                    continue

                def remove(stage=stage):
                    if stage == "milvus":
                        vector = KnowledgeRag.init_knowledge_milvus_vectorstore_sync(
                            0, knowledge=knowledge, embeddings=FakeEmbeddings()
                        )
                        if vector.col:
                            vector.col.delete(expr=f"document_id in [{int(file_id)}]", timeout=10)
                    else:
                        store = KnowledgeRag.init_knowledge_es_vectorstore_sync(knowledge=knowledge)
                        index = knowledge.index_name or knowledge.collection_name
                        if store.client.indices.exists(index=index):
                            result = store.client.delete_by_query(
                                index=index, query={"term": {"metadata.document_id": file_id}}
                            )
                            if result.get("failures") or result.get("timed_out"):
                                raise RuntimeError("ES_delete_incomplete")

                await asyncio.to_thread(remove)
                completed.append(stage)
                await self._checkpoint(job, owner, payload)
        if payload.get("clear_minio"):
            objects = _knowledge_file_owned_object_names(payload["file"]) if len(payload["file"]) > 1 else set()
            objects.update(name for a in payload.get("artifacts", []) if (name := _artifact_owned_object_name(a)))
            storage = await get_minio_storage()
            for object_name in sorted(objects):
                stage = f"object:{object_name}"
                if stage in completed:
                    continue
                if await self.repository_call("object_is_referenced", object_name):
                    payload.setdefault("retained_objects", []).append(object_name)
                else:
                    await storage.remove_object(bucket_name=storage.bucket, object_name=object_name)
                completed.append(stage)
                await self._checkpoint(job, owner, payload)
        return "done"
