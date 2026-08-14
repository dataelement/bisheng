from unittest.mock import AsyncMock

import pytest
from elastic_transport import ApiResponseMeta, HttpHeaders, NodeConfig
from elasticsearch import BadRequestError, NotFoundError

from bisheng.knowledge.domain import knowledge_fulltext_constants as constants
from bisheng.knowledge.domain.repositories.implementations.knowledge_fulltext_index_repository_impl import (
    KnowledgeFulltextIndexConfigurationError,
    KnowledgeFulltextIndexRepositoryImpl,
)
from bisheng.knowledge.domain.schemas.knowledge_fulltext_schema import KnowledgeFulltextDocument


def _compatible_index_responses(repository: KnowledgeFulltextIndexRepositoryImpl):
    index_name = constants.physical_index_name()
    definition = repository.build_index_definition()
    settings = definition["settings"]
    mapping_response = {index_name: {"mappings": definition["mappings"]}}
    settings_response = {
        index_name: {
            "settings": {
                "index": {
                    "max_ngram_diff": str(settings["index.max_ngram_diff"]),
                    "analysis": settings["analysis"],
                }
            }
        }
    }
    return mapping_response, settings_response


def _bad_request(error_type: str, reason: str | None = None) -> BadRequestError:
    return BadRequestError(
        error_type,
        meta=ApiResponseMeta(
            status=400,
            http_version="1.1",
            headers=HttpHeaders(),
            duration=0.0,
            node=NodeConfig("http", "localhost", 9200),
        ),
        body={"error": {"type": error_type, "reason": reason or error_type}, "status": 400},
    )


def test_index_definition_is_strict_and_contains_search_multifields():
    repository = KnowledgeFulltextIndexRepositoryImpl(AsyncMock())

    definition = repository.build_index_definition()
    mappings = definition["mappings"]
    properties = mappings["properties"]

    assert mappings["dynamic"] == "strict"
    for field_name in ("file_name", "display_title", "summary", "content", "tags"):
        assert properties[field_name]["type"] == "text"
        assert "substring" in properties[field_name]["fields"]
    for field_name in ("file_name", "display_title", "tags"):
        assert properties[field_name]["fields"]["keyword"]["type"] == "keyword"
    assert "tenant_id" not in properties
    assert "user_metadata" not in properties
    assert properties["original_knowledge_id"] == {"type": "long"}
    assert properties["original_knowledge_name"] == {"type": "keyword"}
    assert definition["settings"]["analysis"]["analyzer"]


def test_substring_analyzer_supports_single_character_matches():
    repository = KnowledgeFulltextIndexRepositoryImpl(AsyncMock())

    definition = repository.build_index_definition()
    settings = definition["settings"]
    tokenizer = settings["analysis"]["tokenizer"]["fulltext_substring_tokenizer"]
    query_analyzer = settings["analysis"]["analyzer"]["fulltext_substring_query_analyzer"]
    properties = definition["mappings"]["properties"]

    assert tokenizer["min_gram"] == 1
    assert tokenizer["max_gram"] == 20
    assert settings["index.max_ngram_diff"] == 19
    assert query_analyzer == {
        "type": "custom",
        "tokenizer": "keyword",
        "filter": ["lowercase"],
    }
    for field_name in ("file_name", "display_title", "summary", "content", "tags"):
        assert properties[field_name]["fields"]["substring"]["analyzer"] == "fulltext_substring_index_analyzer"


async def test_upsert_uses_file_id_and_delete_scope_uses_knowledge_id():
    client = AsyncMock()
    repository = KnowledgeFulltextIndexRepositoryImpl(client)
    document = KnowledgeFulltextDocument.minimal(
        file_id=11,
        knowledge_id=22,
        file_name="制度汇编.pdf",
        content="安全生产管理办法",
        sync_revision=3,
    )

    await repository.upsert(document)
    await repository.delete_scope(22)

    client.update.assert_awaited_once()
    assert client.update.await_args.kwargs["id"] == "11"
    assert client.update.await_args.kwargs["index"] == "knowledge_fulltext"
    client.delete_by_query.assert_awaited_once_with(
        index="knowledge_fulltext",
        query={"term": {"knowledge_id": 22}},
        conflicts="proceed",
        refresh=False,
    )


async def test_alias_conflict_fails_closed_without_mutation():
    client = AsyncMock()
    client.indices.get_alias.return_value = {
        "knowledge_fulltext_v1": {},
        "knowledge_fulltext_v2": {},
    }
    repository = KnowledgeFulltextIndexRepositoryImpl(client)

    with pytest.raises(KnowledgeFulltextIndexConfigurationError, match="multiple"):
        await repository.ensure_index()

    client.indices.create.assert_not_awaited()
    client.indices.update_aliases.assert_not_awaited()


async def test_first_initialization_creates_versioned_index_and_write_alias():
    client = AsyncMock()
    client.indices.get_alias.side_effect = NotFoundError("missing", meta=None, body=None)
    client.indices.exists.return_value = False
    repository = KnowledgeFulltextIndexRepositoryImpl(client)

    await repository.ensure_index()

    client.indices.create.assert_awaited_once()
    assert client.indices.create.await_args.kwargs["index"] == "knowledge_fulltext_v1"
    client.indices.update_aliases.assert_awaited_once_with(
        actions=[
            {
                "add": {
                    "index": "knowledge_fulltext_v1",
                    "alias": "knowledge_fulltext",
                    "is_write_index": True,
                }
            }
        ]
    )


async def test_concurrent_first_initialization_validates_winner_and_continues():
    client = AsyncMock()
    repository = KnowledgeFulltextIndexRepositoryImpl(client)
    mapping_response, settings_response = _compatible_index_responses(repository)
    client.indices.get_alias.side_effect = NotFoundError("missing", meta=None, body=None)
    client.indices.exists.return_value = False
    client.indices.create.side_effect = _bad_request(
        "resource_already_exists_exception",
        "index was created by another consumer",
    )
    client.indices.get_mapping.return_value = mapping_response
    client.indices.get_settings.return_value = settings_response

    await repository.ensure_index()

    client.indices.get_mapping.assert_awaited_once_with(index="knowledge_fulltext_v1")
    client.indices.get_settings.assert_awaited_once_with(index="knowledge_fulltext_v1")
    client.indices.update_aliases.assert_awaited_once()


async def test_first_initialization_does_not_swallow_other_bad_requests():
    client = AsyncMock()
    repository = KnowledgeFulltextIndexRepositoryImpl(client)
    client.indices.get_alias.side_effect = NotFoundError("missing", meta=None, body=None)
    client.indices.exists.return_value = False
    client.indices.create.side_effect = _bad_request("mapper_parsing_exception")

    with pytest.raises(BadRequestError, match="mapper_parsing_exception"):
        await repository.ensure_index()

    client.indices.get_mapping.assert_not_awaited()
    client.indices.get_settings.assert_not_awaited()
    client.indices.update_aliases.assert_not_awaited()


async def test_existing_compatible_index_initialization_is_idempotent():
    client = AsyncMock()
    repository = KnowledgeFulltextIndexRepositoryImpl(client)
    physical_index_name = constants.physical_index_name()
    mapping_response, settings_response = _compatible_index_responses(repository)
    client.indices.get_alias.return_value = {physical_index_name: {}}
    client.indices.get_mapping.return_value = mapping_response
    client.indices.get_settings.return_value = settings_response

    await repository.ensure_index()

    client.indices.create.assert_not_awaited()
    client.indices.update_aliases.assert_not_awaited()


async def test_existing_v1_missing_only_engagement_fields_is_additively_upgraded():
    client = AsyncMock()
    repository = KnowledgeFulltextIndexRepositoryImpl(client)
    index_name = constants.physical_index_name()
    compatible_mapping, settings_response = _compatible_index_responses(repository)
    old_mapping = {
        index_name: {
            "mappings": {
                "dynamic": "strict",
                "properties": {
                    key: value
                    for key, value in compatible_mapping[index_name]["mappings"]["properties"].items()
                    if key not in {"preview_count", "download_count", "engagement_updated_at"}
                },
            }
        }
    }
    client.indices.get_alias.return_value = {index_name: {}}
    client.indices.get_mapping.side_effect = [old_mapping, compatible_mapping]
    client.indices.get_settings.return_value = settings_response

    await repository.ensure_index()

    client.indices.put_mapping.assert_awaited_once_with(
        index=index_name,
        properties={
            "preview_count": {"type": "long"},
            "download_count": {"type": "long"},
            "engagement_updated_at": {"type": "date"},
        },
    )


async def test_existing_v1_missing_source_knowledge_fields_is_additively_upgraded():
    client = AsyncMock()
    repository = KnowledgeFulltextIndexRepositoryImpl(client)
    index_name = constants.physical_index_name()
    compatible_mapping, settings_response = _compatible_index_responses(repository)
    missing_fields = {"original_knowledge_id", "original_knowledge_name"}
    old_mapping = {
        index_name: {
            "mappings": {
                "dynamic": "strict",
                "properties": {
                    key: value
                    for key, value in compatible_mapping[index_name]["mappings"]["properties"].items()
                    if key not in missing_fields
                },
            }
        }
    }
    client.indices.get_alias.return_value = {index_name: {}}
    client.indices.get_mapping.side_effect = [old_mapping, compatible_mapping]
    client.indices.get_settings.return_value = settings_response

    await repository.ensure_index()

    client.indices.put_mapping.assert_awaited_once_with(
        index=index_name,
        properties={
            "original_knowledge_id": {"type": "long"},
            "original_knowledge_name": {"type": "keyword"},
        },
    )


async def test_existing_v1_rejects_incompatible_additive_field_type():
    client = AsyncMock()
    repository = KnowledgeFulltextIndexRepositoryImpl(client)
    index_name = constants.physical_index_name()
    compatible_mapping, settings_response = _compatible_index_responses(repository)
    incompatible_mapping = compatible_mapping.copy()
    incompatible_mapping[index_name] = {
        "mappings": {
            "dynamic": "strict",
            "properties": {
                **compatible_mapping[index_name]["mappings"]["properties"],
                "original_knowledge_id": {"type": "keyword"},
            },
        }
    }
    client.indices.get_alias.return_value = {index_name: {}}
    client.indices.get_mapping.return_value = incompatible_mapping
    client.indices.get_settings.return_value = settings_response

    with pytest.raises(KnowledgeFulltextIndexConfigurationError, match="mapping"):
        await repository.ensure_index()

    client.indices.put_mapping.assert_not_awaited()


async def test_fulltext_id_scan_uses_short_pit_and_stable_file_id_cursor():
    client = AsyncMock()
    client.open_point_in_time.return_value = {"id": "pit-1"}
    client.search.return_value = {
        "pit_id": "pit-2",
        "hits": {"hits": [{"_source": {"file_id": 12}}, {"_source": {"file_id": 13}}]},
    }
    repository = KnowledgeFulltextIndexRepositoryImpl(client)

    result = await repository.list_file_ids(after_file_id=11, limit=2)

    assert result == [12, 13]
    client.search.assert_awaited_once_with(
        size=2,
        query={"bool": {"filter": [{"range": {"file_id": {"gt": 11}}}]}},
        sort=[{"file_id": {"order": "asc"}}, "_shard_doc"],
        source_includes=["file_id"],
        pit={"id": "pit-1", "keep_alive": "1m"},
    )
    client.close_point_in_time.assert_awaited_once_with(id="pit-2")


async def test_read_only_preflight_validates_active_alias_without_mutation():
    client = AsyncMock()
    repository = KnowledgeFulltextIndexRepositoryImpl(client)
    index_name = constants.physical_index_name()
    mapping_response, settings_response = _compatible_index_responses(repository)
    client.indices.get_alias.return_value = {
        index_name: {
            "aliases": {
                constants.KNOWLEDGE_FULLTEXT_INDEX_ALIAS: {"is_write_index": True},
            }
        }
    }
    client.indices.get_mapping.return_value = mapping_response
    client.indices.get_settings.return_value = settings_response

    await repository.validate_read_index()

    client.indices.create.assert_not_awaited()
    client.indices.put_mapping.assert_not_awaited()
    client.indices.update_aliases.assert_not_awaited()


async def test_existing_file_ids_uses_bounded_read_only_mget():
    client = AsyncMock()
    client.mget.return_value = {
        "docs": [
            {"_id": "7", "found": True},
            {"_id": "8", "found": False},
            {"_id": "9", "found": True},
        ]
    }
    repository = KnowledgeFulltextIndexRepositoryImpl(client)

    result = await repository.existing_file_ids([7, 8, 9])

    assert result == {7, 9}
    client.mget.assert_awaited_once_with(
        index=constants.KNOWLEDGE_FULLTEXT_INDEX_ALIAS,
        ids=["7", "8", "9"],
        source=False,
    )


async def test_existing_index_with_incompatible_analyzer_fails_closed():
    client = AsyncMock()
    repository = KnowledgeFulltextIndexRepositoryImpl(client)
    physical_index_name = constants.physical_index_name()
    mapping_response, settings_response = _compatible_index_responses(repository)
    settings_response[physical_index_name]["settings"]["index"]["analysis"]["tokenizer"][
        "fulltext_substring_tokenizer"
    ]["min_gram"] = "2"
    client.indices.get_alias.return_value = {physical_index_name: {}}
    client.indices.get_mapping.return_value = mapping_response
    client.indices.get_settings.return_value = settings_response

    with pytest.raises(KnowledgeFulltextIndexConfigurationError, match="settings"):
        await repository.ensure_index()

    client.indices.update_aliases.assert_not_awaited()


async def test_explicit_version_switch_is_atomic_and_checks_expected_source(monkeypatch):
    client = AsyncMock()
    monkeypatch.setattr(constants, "KNOWLEDGE_FULLTEXT_INDEX_SCHEMA_VERSION", 2)
    repository = KnowledgeFulltextIndexRepositoryImpl(client)
    client.indices.exists.return_value = False
    client.indices.get_alias.return_value = {"knowledge_fulltext_v1": {}}

    await repository.switch_alias(expected_current_index="knowledge_fulltext_v1")

    client.indices.update_aliases.assert_awaited_once_with(
        actions=[
            {"remove": {"index": "knowledge_fulltext_v1", "alias": "knowledge_fulltext"}},
            {
                "add": {
                    "index": "knowledge_fulltext_v2",
                    "alias": "knowledge_fulltext",
                    "is_write_index": True,
                }
            },
        ]
    )


async def test_explicit_version_switch_rejects_concurrent_alias_change(monkeypatch):
    client = AsyncMock()
    monkeypatch.setattr(constants, "KNOWLEDGE_FULLTEXT_INDEX_SCHEMA_VERSION", 3)
    repository = KnowledgeFulltextIndexRepositoryImpl(client)
    client.indices.exists.return_value = False
    client.indices.get_alias.return_value = {"knowledge_fulltext_v2": {}}

    with pytest.raises(KnowledgeFulltextIndexConfigurationError, match="changed concurrently"):
        await repository.switch_alias(expected_current_index="knowledge_fulltext_v1")

    client.indices.create.assert_not_awaited()
    client.indices.update_aliases.assert_not_awaited()
