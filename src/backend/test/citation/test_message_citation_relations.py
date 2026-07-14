from collections import defaultdict

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine
from sqlmodel import Session

from bisheng.citation.domain.models.message_citation import MessageCitation, MessageCitationRelation
from bisheng.citation.domain.repositories.implementations.message_citation_repository_impl import (
    MessageCitationRepositoryImpl,
)
from bisheng.citation.domain.schemas.citation_schema import (
    CitationRegistryItemSchema,
    CitationType,
    RagCitationItemSchema,
    RagCitationPayloadSchema,
)
from bisheng.citation.domain.services.citation_registry_service import CitationRegistryService
from bisheng.core.database.alembic.versions import v2_6_0_f055_message_citation_relation as migration


class FakeMessageCitationRepository:
    def __init__(self):
        self.entities: dict[str, MessageCitation] = {}
        self.relations: dict[int, list[str]] = defaultdict(list)
        self.next_entity_id = 1
        self.next_relation_id = 1

    async def find_by_message_id(self, message_id: int) -> list[MessageCitation]:
        return self.find_by_message_id_sync(message_id)

    def find_by_message_id_sync(self, message_id: int) -> list[MessageCitation]:
        return [self.entities[citation_id] for citation_id in self.relations[message_id]]

    async def find_by_citation_ids(self, citation_ids: list[str]) -> list[MessageCitation]:
        return self.find_by_citation_ids_sync(citation_ids)

    def find_by_citation_ids_sync(self, citation_ids: list[str]) -> list[MessageCitation]:
        return [self.entities[citation_id] for citation_id in citation_ids if citation_id in self.entities]

    async def bulk_create(self, citations: list[MessageCitation]) -> list[MessageCitation]:
        return self.bulk_create_sync(citations)

    def bulk_create_sync(self, citations: list[MessageCitation]) -> list[MessageCitation]:
        for citation in citations:
            citation.id = self.next_entity_id
            self.next_entity_id += 1
            self.entities[citation.citation_id] = citation
        return citations

    async def bulk_create_relations(
        self,
        relations: list[MessageCitationRelation],
    ) -> list[MessageCitationRelation]:
        return self.bulk_create_relations_sync(relations)

    def bulk_create_relations_sync(
        self,
        relations: list[MessageCitationRelation],
    ) -> list[MessageCitationRelation]:
        for relation in relations:
            relation.id = self.next_relation_id
            self.next_relation_id += 1
            self.relations[relation.message_id].append(relation.citation_id)
        return relations


def build_registry_item(citation_id: str = "knowledgesearch_shared") -> CitationRegistryItemSchema:
    return CitationRegistryItemSchema(
        citationId=citation_id,
        type=CitationType.RAG,
        sourcePayload=RagCitationPayloadSchema(
            knowledgeId=131,
            documentId=1305,
            documentName="source.pdf",
            items=[
                RagCitationItemSchema(
                    itemId="1",
                    chunkId="chunk-1",
                    content="shared citation payload",
                )
            ],
        ),
    )


async def test_reuses_one_citation_entity_across_messages():
    repository = FakeMessageCitationRepository()
    service = CitationRegistryService(repository)
    item = build_registry_item()

    first_result = await service.save_citations(1737, [item], chat_id="chat-1", flow_id="flow-1")
    second_result = await service.save_citations(1738, [item], chat_id="chat-1", flow_id="flow-1")
    repeated_result = await service.save_citations(1738, [item], chat_id="chat-1", flow_id="flow-1")

    assert len(repository.entities) == 1
    assert repository.entities[item.citationId].message_id == 1737
    assert repository.relations == {
        1737: [item.citationId],
        1738: [item.citationId],
    }
    assert [entity.citation_id for entity in first_result] == [item.citationId]
    assert [entity.citation_id for entity in second_result] == [item.citationId]
    assert [entity.citation_id for entity in repeated_result] == [item.citationId]


def test_sync_save_reuses_one_citation_entity_across_messages():
    repository = FakeMessageCitationRepository()
    service = CitationRegistryService(repository)
    item = build_registry_item("knowledgesearch_sync")

    service.save_citations_sync(2001, [item])
    service.save_citations_sync(2002, [item])

    assert len(repository.entities) == 1
    assert repository.relations == {
        2001: [item.citationId],
        2002: [item.citationId],
    }


def test_repository_reads_citations_through_message_relation():
    engine = create_engine("sqlite://")
    MessageCitation.__table__.create(engine)
    MessageCitationRelation.__table__.create(engine)

    with Session(engine) as session:
        session.add(
            MessageCitation(
                citation_id="knowledgesearch_joined",
                message_id=3001,
                citation_type="rag",
                source_payload={"items": []},
            )
        )
        session.add_all(
            [
                MessageCitationRelation(tenant_id=1, message_id=3001, citation_id="knowledgesearch_joined"),
                MessageCitationRelation(tenant_id=1, message_id=3002, citation_id="knowledgesearch_joined"),
            ]
        )
        session.commit()

        repository = MessageCitationRepositoryImpl(session)

        assert [item.citation_id for item in repository.find_by_message_id_sync(3001)] == ["knowledgesearch_joined"]
        assert [item.citation_id for item in repository.find_by_message_id_sync(3002)] == ["knowledgesearch_joined"]


def test_migration_backfills_existing_message_citations():
    engine = create_engine("sqlite://")
    metadata = sa.MetaData()
    chat_message = sa.Table(
        "chatmessage",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
    )
    message_citation = sa.Table(
        "message_citation",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("citation_id", sa.String(length=128), nullable=False),
    )
    metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(chat_message.insert().values(id=1737, tenant_id=9))
        connection.execute(
            message_citation.insert().values(
                id=1048,
                message_id=1737,
                citation_id="knowledgesearch_caa5bcd2",
            )
        )

        context = MigrationContext.configure(connection)
        with Operations.context(context):
            migration.upgrade()

        relation = sa.Table("message_citation_relation", sa.MetaData(), autoload_with=connection)
        rows = connection.execute(sa.select(relation.c.tenant_id, relation.c.message_id, relation.c.citation_id)).all()

        assert rows == [(9, 1737, "knowledgesearch_caa5bcd2")]

        with Operations.context(context):
            migration.downgrade()
        assert not sa.inspect(connection).has_table("message_citation_relation")
