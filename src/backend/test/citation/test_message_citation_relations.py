from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import Session, select
from sqlmodel.ext.asyncio.session import AsyncSession

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
from bisheng.citation.domain.services.citation_prompt_helper import (
    CITATION_END_MARKER,
    CITATION_START_MARKER,
)
from bisheng.citation.domain.services.citation_registry_service import CitationRegistryService
from bisheng.database.models.message import ChatMessage
from scripts.backfill_message_citation_relations import backfill


def _build_registry_item(
    citation_id: str = "knowledgesearch_shared",
    *,
    access_scope: str = "per_user",
) -> CitationRegistryItemSchema:
    return CitationRegistryItemSchema(
        citationId=citation_id,
        type=CitationType.RAG,
        accessScope=access_scope,
        sourcePayload=RagCitationPayloadSchema(
            knowledgeId=None,
            documentId=None,
            documentName="河北天气.txt",
            items=[
                RagCitationItemSchema(
                    itemId="1",
                    chunkId="chunk-1",
                    content="shared temporary knowledge answer",
                )
            ],
        ),
    )


def _build_entity(
    citation_id: str,
    message_id: int,
    *,
    access_scope: str = "per_user",
) -> MessageCitation:
    item = _build_registry_item(citation_id, access_scope=access_scope)
    return MessageCitation(
        citation_id=citation_id,
        message_id=message_id,
        chat_id="chat-1",
        flow_id="flow-1",
        citation_type=item.type.value,
        access_scope=item.accessScope,
        source_payload=CitationRegistryService.dump_source_payload(item.sourcePayload),
    )


def _create_sync_schema(engine) -> None:
    MessageCitation.__table__.create(engine)
    MessageCitationRelation.__table__.create(engine)


async def _create_async_schema(engine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(MessageCitation.__table__.create)
        await connection.run_sync(MessageCitationRelation.__table__.create)


def test_sync_save_reuses_one_citation_across_messages_and_retries():
    engine = create_engine("sqlite://")
    _create_sync_schema(engine)

    with Session(engine) as session:
        service = CitationRegistryService(MessageCitationRepositoryImpl(session))
        item = _build_registry_item(access_scope="shared")

        first_result = service.save_citations_sync(440386, [item], chat_id="chat-1", flow_id="flow-1")
        second_result = service.save_citations_sync(440387, [item], chat_id="chat-1", flow_id="flow-1")
        repeated_result = service.save_citations_sync(440387, [item], chat_id="chat-1", flow_id="flow-1")

        citations = list(session.exec(select(MessageCitation)).all())
        relations = list(
            session.exec(select(MessageCitationRelation).order_by(MessageCitationRelation.message_id.asc())).all()
        )

    assert len(citations) == 1
    assert citations[0].message_id == 440386
    assert citations[0].access_scope == "shared"
    assert [(relation.message_id, relation.citation_id) for relation in relations] == [
        (440386, item.citationId),
        (440387, item.citationId),
    ]
    assert [citation.citation_id for citation in first_result] == [item.citationId]
    assert [citation.citation_id for citation in second_result] == [item.citationId]
    assert [citation.citation_id for citation in repeated_result] == [item.citationId]


async def test_async_save_reuses_one_citation_across_messages():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    await _create_async_schema(engine)

    async with AsyncSession(engine, expire_on_commit=False) as session:
        service = CitationRegistryService(MessageCitationRepositoryImpl(session))
        item = _build_registry_item("knowledgesearch_async")

        await service.save_citations(1001, [item], chat_id="chat-1", flow_id="flow-1")
        await service.save_citations(1002, [item], chat_id="chat-1", flow_id="flow-1")

        citations = list((await session.exec(select(MessageCitation))).all())
        relations = list((await session.exec(select(MessageCitationRelation))).all())

    await engine.dispose()
    assert len(citations) == 1
    assert {(relation.message_id, relation.citation_id) for relation in relations} == {
        (1001, item.citationId),
        (1002, item.citationId),
    }


async def test_repository_reads_relation_and_legacy_rows_without_duplicates():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    await _create_async_schema(engine)

    async with AsyncSession(engine, expire_on_commit=False) as session:
        session.add(_build_entity("knowledgesearch_legacy", 2001))
        session.add(
            MessageCitationRelation(
                tenant_id=1,
                message_id=2002,
                citation_id="knowledgesearch_legacy",
            )
        )
        session.add(
            MessageCitationRelation(
                tenant_id=1,
                message_id=2001,
                citation_id="knowledgesearch_legacy",
            )
        )
        await session.commit()

        repository = MessageCitationRepositoryImpl(session)
        legacy_owner = await repository.find_by_message_id(2001)
        related_message = await repository.find_by_message_id(2002)
        grouped = await repository.find_by_message_ids_grouped([2001, 2002])

    await engine.dispose()
    assert [citation.citation_id for citation in legacy_owner] == ["knowledgesearch_legacy"]
    assert [citation.citation_id for citation in related_message] == ["knowledgesearch_legacy"]
    assert {
        message_id: [citation.citation_id for citation in citations] for message_id, citations in grouped.items()
    } == {
        2001: ["knowledgesearch_legacy"],
        2002: ["knowledgesearch_legacy"],
    }


def test_ensure_citations_recovers_a_unique_key_race(tmp_path):
    database_path = tmp_path / "citation-race.db"
    engine_a = create_engine(f"sqlite:///{database_path}")
    engine_b = create_engine(f"sqlite:///{database_path}")
    _create_sync_schema(engine_a)

    with Session(engine_a) as session_a, Session(engine_b) as session_b:
        repository_a = MessageCitationRepositoryImpl(session_a)
        repository_b = MessageCitationRepositoryImpl(session_b)
        candidate_a = _build_entity("knowledgesearch_race", 3001)
        candidate_b = _build_entity("knowledgesearch_race", 3002)
        original_find = repository_a.find_by_citation_ids_sync
        state = {"injected": False}

        def find_with_competing_insert(citation_ids):
            result = original_find(citation_ids)
            if not state["injected"]:
                state["injected"] = True
                session_a.rollback()
                repository_b.bulk_create_sync([candidate_b])
            return result

        repository_a.find_by_citation_ids_sync = find_with_competing_insert
        result = repository_a.ensure_citations_sync([candidate_a])
        citations = list(session_a.exec(select(MessageCitation)).all())

    assert [citation.citation_id for citation in result] == ["knowledgesearch_race"]
    assert len(citations) == 1
    assert citations[0].message_id == 3002


def test_ensure_relations_recovers_a_unique_key_race(tmp_path):
    database_path = tmp_path / "relation-race.db"
    engine_a = create_engine(f"sqlite:///{database_path}")
    engine_b = create_engine(f"sqlite:///{database_path}")
    _create_sync_schema(engine_a)

    with Session(engine_a) as session_a, Session(engine_b) as session_b:
        session_a.add(_build_entity("knowledgesearch_relation_race", 4001))
        session_a.commit()

        repository_a = MessageCitationRepositoryImpl(session_a)
        desired_relation = MessageCitationRelation(
            tenant_id=1,
            message_id=4001,
            citation_id="knowledgesearch_relation_race",
        )
        original_find = repository_a._find_relations_sync
        state = {"injected": False}

        def find_with_competing_insert(relation_keys):
            result = original_find(relation_keys)
            if not state["injected"]:
                state["injected"] = True
                session_a.rollback()
                session_b.add(
                    MessageCitationRelation(
                        tenant_id=1,
                        message_id=4001,
                        citation_id="knowledgesearch_relation_race",
                    )
                )
                session_b.commit()
            return result

        repository_a._find_relations_sync = find_with_competing_insert
        result = repository_a.ensure_relations_sync([desired_relation])
        relations = list(session_a.exec(select(MessageCitationRelation)).all())

    assert [(relation.message_id, relation.citation_id) for relation in result] == [
        (4001, "knowledgesearch_relation_race")
    ]
    assert len(relations) == 1


async def test_backfill_recovers_legacy_and_marker_relations_idempotently():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    await _create_async_schema(engine)
    async with engine.begin() as connection:
        await connection.run_sync(ChatMessage.__table__.create)

    citation_id = "knowledgesearch_backfill"
    citation_marker = f"{CITATION_START_MARKER}{citation_id}:1{CITATION_END_MARKER}"
    missing_marker = f"{CITATION_START_MARKER}knowledgesearch_missing:1{CITATION_END_MARKER}"

    async with AsyncSession(engine, expire_on_commit=False) as session:
        session.add(
            _build_entity(
                citation_id,
                5001,
            )
        )
        session.add_all(
            [
                ChatMessage(
                    id=5001,
                    tenant_id=9,
                    user_id=1,
                    chat_id="chat-1",
                    flow_id="flow-1",
                    is_bot=True,
                    type="over",
                    category="output",
                    message=citation_marker,
                ),
                ChatMessage(
                    id=5002,
                    tenant_id=9,
                    user_id=1,
                    chat_id="chat-1",
                    flow_id="flow-1",
                    is_bot=True,
                    type="over",
                    category="output",
                    message=citation_marker,
                ),
                ChatMessage(
                    id=5003,
                    tenant_id=9,
                    user_id=1,
                    chat_id="other-chat",
                    flow_id="flow-1",
                    is_bot=True,
                    type="over",
                    category="output",
                    message=citation_marker,
                ),
                ChatMessage(
                    id=5004,
                    tenant_id=9,
                    user_id=1,
                    chat_id="chat-1",
                    flow_id="flow-1",
                    is_bot=True,
                    type="over",
                    category="output",
                    message=missing_marker,
                ),
            ]
        )
        await session.commit()

        dry_run = await backfill(
            session,
            apply=False,
            recover_markers=True,
            batch_size=2,
        )
        assert list((await session.exec(select(MessageCitationRelation))).all()) == []

        applied = await backfill(
            session,
            apply=True,
            recover_markers=True,
            batch_size=2,
        )
        repeated = await backfill(
            session,
            apply=True,
            recover_markers=True,
            batch_size=2,
        )
        relations = list(
            (
                await session.exec(select(MessageCitationRelation).order_by(MessageCitationRelation.message_id.asc()))
            ).all()
        )

    await engine.dispose()
    assert dry_run.created == 2
    assert dry_run.skipped_missing_citation == 1
    assert dry_run.skipped_scope_mismatch == 1
    assert applied.created == 2
    assert repeated.created == 0
    assert repeated.skipped_existing == 2
    assert [(relation.tenant_id, relation.message_id, relation.citation_id) for relation in relations] == [
        (9, 5001, citation_id),
        (9, 5002, citation_id),
    ]
