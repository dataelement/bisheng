"""同步解析事务使用的全文 Outbox Repository。"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlmodel import Session, select

from bisheng.knowledge.domain.models.knowledge_fulltext_outbox import (
    KnowledgeFulltextAggregateType,
    KnowledgeFulltextDesiredAction,
    KnowledgeFulltextOutbox,
    KnowledgeFulltextOutboxStatus,
)
from bisheng.knowledge.domain.services.knowledge_fulltext_after_commit_service import (
    track_outbox_after_commit,
)


class KnowledgeFulltextOutboxSyncRepositoryImpl:
    def __init__(self, session: Session):
        self.session = session

    def request_file_sync(
        self,
        *,
        file_id: int,
        knowledge_id: int,
        desired_action: KnowledgeFulltextDesiredAction,
        trigger_type: str,
        tenant_id: int,
        max_retries: int,
    ) -> KnowledgeFulltextOutbox:
        if self.session.bind is not None and self.session.bind.dialect.name == "mysql":
            row = self._request_file_sync_mysql(
                file_id=file_id,
                knowledge_id=knowledge_id,
                desired_action=desired_action,
                trigger_type=trigger_type,
                tenant_id=tenant_id,
                max_retries=max_retries,
            )
        else:
            statement = (
                select(KnowledgeFulltextOutbox)
                .where(
                    KnowledgeFulltextOutbox.tenant_id == tenant_id,
                    KnowledgeFulltextOutbox.aggregate_type == KnowledgeFulltextAggregateType.FILE.value,
                    KnowledgeFulltextOutbox.aggregate_id == file_id,
                )
                .with_for_update()
            )
            row = self.session.exec(statement).first()
            if row is None and self.session.bind is not None and self.session.bind.dialect.name == "dm":
                self.session.execute(text("LOCK TABLE knowledge_fulltext_outbox IN EXCLUSIVE MODE"))
                row = self.session.exec(statement).first()
            if row is None:
                row = KnowledgeFulltextOutbox(
                    tenant_id=tenant_id,
                    aggregate_type=KnowledgeFulltextAggregateType.FILE.value,
                    aggregate_id=file_id,
                    knowledge_id=knowledge_id,
                    desired_action=desired_action.value,
                    desired_revision=1,
                    applied_revision=0,
                    trigger_type=trigger_type,
                    status=KnowledgeFulltextOutboxStatus.PENDING.value,
                    max_retries=max_retries,
                )
            else:
                self._merge_request(
                    row,
                    knowledge_id=knowledge_id,
                    desired_action=desired_action,
                    trigger_type=trigger_type,
                    max_retries=max_retries,
                )
            self.session.add(row)
            self.session.flush()
        track_outbox_after_commit(self.session, row)
        return row

    def _request_file_sync_mysql(
        self,
        *,
        file_id: int,
        knowledge_id: int,
        desired_action: KnowledgeFulltextDesiredAction,
        trigger_type: str,
        tenant_id: int,
        max_retries: int,
    ) -> KnowledgeFulltextOutbox:
        table = KnowledgeFulltextOutbox.__table__
        statement = mysql_insert(table).values(
            tenant_id=tenant_id,
            aggregate_type=KnowledgeFulltextAggregateType.FILE.value,
            aggregate_id=file_id,
            knowledge_id=knowledge_id,
            desired_action=desired_action.value,
            desired_revision=1,
            applied_revision=0,
            trigger_type=trigger_type,
            status=KnowledgeFulltextOutboxStatus.PENDING.value,
            retry_count=0,
            max_retries=max_retries,
        )
        self.session.execute(
            statement.on_duplicate_key_update(
                knowledge_id=statement.inserted.knowledge_id,
                desired_action=statement.inserted.desired_action,
                desired_revision=table.c.desired_revision + 1,
                trigger_type=statement.inserted.trigger_type,
                status=KnowledgeFulltextOutboxStatus.PENDING.value,
                retry_count=0,
                max_retries=statement.inserted.max_retries,
                next_retry_at=None,
                lease_owner=None,
                lease_until=None,
                fanout_cursor=None,
                error_summary=None,
            )
        )
        row = self.session.exec(
            select(KnowledgeFulltextOutbox)
            .where(
                KnowledgeFulltextOutbox.tenant_id == tenant_id,
                KnowledgeFulltextOutbox.aggregate_type == KnowledgeFulltextAggregateType.FILE.value,
                KnowledgeFulltextOutbox.aggregate_id == file_id,
            )
            .with_for_update()
        ).one()
        self.session.flush()
        return row

    @staticmethod
    def _merge_request(
        row: KnowledgeFulltextOutbox,
        *,
        knowledge_id: int,
        desired_action: KnowledgeFulltextDesiredAction,
        trigger_type: str,
        max_retries: int,
    ) -> None:
        row.knowledge_id = knowledge_id
        row.desired_action = desired_action.value
        row.desired_revision += 1
        row.trigger_type = trigger_type
        row.status = KnowledgeFulltextOutboxStatus.PENDING.value
        row.retry_count = 0
        row.max_retries = max_retries
        row.next_retry_at = None
        row.lease_owner = None
        row.lease_until = None
        row.fanout_cursor = None
        row.error_summary = None
