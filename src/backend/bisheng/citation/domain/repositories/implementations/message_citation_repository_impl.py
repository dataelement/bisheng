from collections import defaultdict

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from bisheng.citation.domain.models.message_citation import MessageCitation, MessageCitationRelation
from bisheng.citation.domain.repositories.interfaces.message_citation_repository import MessageCitationRepository
from bisheng.common.repositories.implementations.base_repository_impl import BaseRepositoryImpl


class MessageCitationRepositoryImpl(BaseRepositoryImpl[MessageCitation, int], MessageCitationRepository):
    """Repository implementation for message citation records."""

    def __init__(self, session: AsyncSession | Session):
        super().__init__(session, MessageCitation)

    async def find_by_message_id(self, message_id: int) -> list[MessageCitation]:
        """Find citations through relations while retaining legacy-row compatibility."""
        relation_query = (
            select(MessageCitationRelation, MessageCitation)
            .join(
                MessageCitation,
                MessageCitation.citation_id == MessageCitationRelation.citation_id,
            )
            .where(MessageCitationRelation.message_id == message_id)
            .order_by(MessageCitationRelation.id.asc())
        )
        relation_result = await self.session.exec(relation_query)
        related_citations = [citation for _, citation in relation_result.all()]

        legacy_query = (
            select(MessageCitation).where(MessageCitation.message_id == message_id).order_by(MessageCitation.id.asc())
        )
        legacy_result = await self.session.exec(legacy_query)
        return self._deduplicate_citations(related_citations, list(legacy_result.all()))

    def find_by_message_id_sync(self, message_id: int) -> list[MessageCitation]:
        """Synchronously find citations with legacy-row compatibility."""
        relation_query = (
            select(MessageCitationRelation, MessageCitation)
            .join(
                MessageCitation,
                MessageCitation.citation_id == MessageCitationRelation.citation_id,
            )
            .where(MessageCitationRelation.message_id == message_id)
            .order_by(MessageCitationRelation.id.asc())
        )
        relation_result = self.session.exec(relation_query)
        related_citations = [citation for _, citation in relation_result.all()]

        legacy_query = (
            select(MessageCitation).where(MessageCitation.message_id == message_id).order_by(MessageCitation.id.asc())
        )
        legacy_result = self.session.exec(legacy_query)
        return self._deduplicate_citations(related_citations, list(legacy_result.all()))

    async def find_by_citation_id(self, citation_id: str) -> MessageCitation | None:
        """Find one citation by its business citation ID."""
        query = select(MessageCitation).where(MessageCitation.citation_id == citation_id)
        result = await self.session.exec(query)
        return result.first()

    async def bulk_create(self, citations: list[MessageCitation]) -> list[MessageCitation]:
        """Create citations in batch."""
        if not citations:
            return []
        return await self.bulk_save(citations)

    def bulk_create_sync(self, citations: list[MessageCitation]) -> list[MessageCitation]:
        """Create citations in batch synchronously."""
        if not citations:
            return []
        return self.bulk_save_sync(citations)

    async def ensure_citations(self, citations: list[MessageCitation]) -> list[MessageCitation]:
        """Create missing global citation rows and recover duplicate-key races."""
        desired = {citation.citation_id: citation for citation in citations}
        citation_ids = list(desired)
        if not citation_ids:
            return []

        while True:
            existing = await self.find_by_citation_ids(citation_ids)
            existing_ids = {citation.citation_id for citation in existing}
            missing_ids = [citation_id for citation_id in citation_ids if citation_id not in existing_ids]
            if not missing_ids:
                return self._order_citations(existing, citation_ids)

            self.session.add_all([self._clone_citation(desired[citation_id]) for citation_id in missing_ids])
            try:
                await self.session.commit()
            except IntegrityError:
                await self.session.rollback()
                after_conflict = await self.find_by_citation_ids(citation_ids)
                after_conflict_ids = {citation.citation_id for citation in after_conflict}
                if not after_conflict_ids.difference(existing_ids):
                    raise

    def ensure_citations_sync(self, citations: list[MessageCitation]) -> list[MessageCitation]:
        """Synchronously create missing rows and recover duplicate-key races."""
        desired = {citation.citation_id: citation for citation in citations}
        citation_ids = list(desired)
        if not citation_ids:
            return []

        while True:
            existing = self.find_by_citation_ids_sync(citation_ids)
            existing_ids = {citation.citation_id for citation in existing}
            missing_ids = [citation_id for citation_id in citation_ids if citation_id not in existing_ids]
            if not missing_ids:
                return self._order_citations(existing, citation_ids)

            self.session.add_all([self._clone_citation(desired[citation_id]) for citation_id in missing_ids])
            try:
                self.session.commit()
            except IntegrityError:
                self.session.rollback()
                after_conflict = self.find_by_citation_ids_sync(citation_ids)
                after_conflict_ids = {citation.citation_id for citation in after_conflict}
                if not after_conflict_ids.difference(existing_ids):
                    raise

    async def ensure_relations(
        self,
        relations: list[MessageCitationRelation],
    ) -> list[MessageCitationRelation]:
        """Create missing message-citation relations and recover concurrent inserts."""
        desired = {(relation.message_id, relation.citation_id): relation for relation in relations}
        relation_keys = list(desired)
        if not relation_keys:
            return []

        while True:
            existing = await self._find_relations(relation_keys)
            existing_keys = {(relation.message_id, relation.citation_id) for relation in existing}
            missing_keys = [relation_key for relation_key in relation_keys if relation_key not in existing_keys]
            if not missing_keys:
                return self._order_relations(existing, relation_keys)

            self.session.add_all([self._clone_relation(desired[relation_key]) for relation_key in missing_keys])
            try:
                await self.session.commit()
            except IntegrityError:
                await self.session.rollback()
                after_conflict = await self._find_relations(relation_keys)
                after_conflict_keys = {(relation.message_id, relation.citation_id) for relation in after_conflict}
                if not after_conflict_keys.difference(existing_keys):
                    raise

    def ensure_relations_sync(
        self,
        relations: list[MessageCitationRelation],
    ) -> list[MessageCitationRelation]:
        """Synchronously create missing relations and recover concurrent inserts."""
        desired = {(relation.message_id, relation.citation_id): relation for relation in relations}
        relation_keys = list(desired)
        if not relation_keys:
            return []

        while True:
            existing = self._find_relations_sync(relation_keys)
            existing_keys = {(relation.message_id, relation.citation_id) for relation in existing}
            missing_keys = [relation_key for relation_key in relation_keys if relation_key not in existing_keys]
            if not missing_keys:
                return self._order_relations(existing, relation_keys)

            self.session.add_all([self._clone_relation(desired[relation_key]) for relation_key in missing_keys])
            try:
                self.session.commit()
            except IntegrityError:
                self.session.rollback()
                after_conflict = self._find_relations_sync(relation_keys)
                after_conflict_keys = {(relation.message_id, relation.citation_id) for relation in after_conflict}
                if not after_conflict_keys.difference(existing_keys):
                    raise

    async def find_by_citation_ids(self, citation_ids: list[str]) -> list[MessageCitation]:
        """Find citations by multiple business citation IDs."""
        if not citation_ids:
            return []

        query = (
            select(MessageCitation)
            .where(col(MessageCitation.citation_id).in_(citation_ids))
            .order_by(MessageCitation.id.asc())
        )
        result = await self.session.exec(query)
        return list(result.all())

    def find_by_citation_ids_sync(self, citation_ids: list[str]) -> list[MessageCitation]:
        """Synchronously find citations by multiple business citation IDs."""
        if not citation_ids:
            return []

        query = (
            select(MessageCitation)
            .where(col(MessageCitation.citation_id).in_(citation_ids))
            .order_by(MessageCitation.id.asc())
        )
        result = self.session.exec(query)
        return list(result.all())

    async def find_by_message_ids_grouped(self, message_ids: list[int]) -> dict[int, list[MessageCitation]]:
        """Find citations for messages through relations and legacy ownership."""
        if not message_ids:
            return {}

        relation_query = (
            select(MessageCitationRelation, MessageCitation)
            .join(
                MessageCitation,
                MessageCitation.citation_id == MessageCitationRelation.citation_id,
            )
            .where(col(MessageCitationRelation.message_id).in_(message_ids))
            .order_by(MessageCitationRelation.message_id.asc(), MessageCitationRelation.id.asc())
        )
        relation_result = await self.session.exec(relation_query)

        grouped_citations: defaultdict[int, list[MessageCitation]] = defaultdict(list)
        seen_by_message: defaultdict[int, set[str]] = defaultdict(set)
        for relation, citation in relation_result.all():
            grouped_citations[relation.message_id].append(citation)
            seen_by_message[relation.message_id].add(citation.citation_id)

        legacy_query = (
            select(MessageCitation)
            .where(col(MessageCitation.message_id).in_(message_ids))
            .order_by(MessageCitation.message_id.asc(), MessageCitation.id.asc())
        )
        legacy_result = await self.session.exec(legacy_query)
        for citation in legacy_result.all():
            if citation.citation_id in seen_by_message[citation.message_id]:
                continue
            grouped_citations[citation.message_id].append(citation)
            seen_by_message[citation.message_id].add(citation.citation_id)

        return dict(grouped_citations)

    async def _find_relations(
        self,
        relation_keys: list[tuple[int, str]],
    ) -> list[MessageCitationRelation]:
        message_ids = list({message_id for message_id, _ in relation_keys})
        citation_ids = list({citation_id for _, citation_id in relation_keys})
        key_set = set(relation_keys)
        query = (
            select(MessageCitationRelation)
            .where(
                col(MessageCitationRelation.message_id).in_(message_ids),
                col(MessageCitationRelation.citation_id).in_(citation_ids),
            )
            .order_by(MessageCitationRelation.id.asc())
        )
        result = await self.session.exec(query)
        return [relation for relation in result.all() if (relation.message_id, relation.citation_id) in key_set]

    def _find_relations_sync(
        self,
        relation_keys: list[tuple[int, str]],
    ) -> list[MessageCitationRelation]:
        message_ids = list({message_id for message_id, _ in relation_keys})
        citation_ids = list({citation_id for _, citation_id in relation_keys})
        key_set = set(relation_keys)
        query = (
            select(MessageCitationRelation)
            .where(
                col(MessageCitationRelation.message_id).in_(message_ids),
                col(MessageCitationRelation.citation_id).in_(citation_ids),
            )
            .order_by(MessageCitationRelation.id.asc())
        )
        result = self.session.exec(query)
        return [relation for relation in result.all() if (relation.message_id, relation.citation_id) in key_set]

    @staticmethod
    def _deduplicate_citations(*citation_groups: list[MessageCitation]) -> list[MessageCitation]:
        citations: list[MessageCitation] = []
        seen: set[str] = set()
        for group in citation_groups:
            for citation in group:
                if citation.citation_id in seen:
                    continue
                seen.add(citation.citation_id)
                citations.append(citation)
        return citations

    @staticmethod
    def _order_citations(
        citations: list[MessageCitation],
        citation_ids: list[str],
    ) -> list[MessageCitation]:
        citation_map = {citation.citation_id: citation for citation in citations}
        return [citation_map[citation_id] for citation_id in citation_ids if citation_id in citation_map]

    @staticmethod
    def _order_relations(
        relations: list[MessageCitationRelation],
        relation_keys: list[tuple[int, str]],
    ) -> list[MessageCitationRelation]:
        relation_map = {(relation.message_id, relation.citation_id): relation for relation in relations}
        return [relation_map[relation_key] for relation_key in relation_keys if relation_key in relation_map]

    @staticmethod
    def _clone_citation(citation: MessageCitation) -> MessageCitation:
        return MessageCitation(
            citation_id=citation.citation_id,
            message_id=citation.message_id,
            chat_id=citation.chat_id,
            flow_id=citation.flow_id,
            citation_type=citation.citation_type,
            access_scope=citation.access_scope,
            source_payload=citation.source_payload,
        )

    @staticmethod
    def _clone_relation(relation: MessageCitationRelation) -> MessageCitationRelation:
        return MessageCitationRelation(
            tenant_id=relation.tenant_id,
            message_id=relation.message_id,
            citation_id=relation.citation_id,
        )
