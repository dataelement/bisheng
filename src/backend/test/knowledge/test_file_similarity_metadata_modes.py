"""两套相似规则的配置、候选结果与跨库正文边界。"""

import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bisheng.core.config.settings import KnowledgeConf
from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeDao
from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile
from test.knowledge.test_knowledge_version_service_similar_scan import _build_svc


def configure(monkeypatch, **rules):
    conf = KnowledgeConf(version_management={"enabled": True, **rules})
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_version_service.bisheng_settings",
        SimpleNamespace(async_get_knowledge=AsyncMock(return_value=conf)),
    )
    return conf.version_management


async def seed(session, file_id, space_id=1, encoding="GF-ZD-SC-20261000000001", subcategory="A", **kwargs):
    file = KnowledgeFile(
        id=file_id,
        knowledge_id=space_id,
        file_name=f"file{file_id}.pdf",
        file_type=1,
        status=2,
        simhash="aaaaaaaaaaaaaaaa",
        file_encoding=encoding,
        file_subcategory_code=subcategory,
        **kwargs,
    )
    session.add(file)
    doc = KnowledgeDocument(knowledge_id=space_id)
    session.add(doc)
    await session.flush()
    version = KnowledgeDocumentVersion(document_id=doc.id, knowledge_file_id=file_id, version_no=1, is_primary=True)
    session.add(version)
    await session.flush()
    doc.primary_version_id = version.id
    await session.commit()
    return file


@pytest.mark.parametrize("entrypoint", ["cached", "publish", "generic"])
async def test_each_metadata_mode_controls_candidate_selection(async_db_session, monkeypatch, entrypoint):
    session = async_db_session
    target_space = 1 if entrypoint == "cached" else 2
    session.add_all([Knowledge(id=i, name=f"s{i}", type=3, user_id=1) for i in [1, 2]])
    await session.commit()
    await seed(session, 100)
    for file_id, encoding, subcategory in [
        (200, "GF-ZD-SC-20261000000002", "A"),
        (201, "GF-ZD-SC-20261000000003", "B"),
        (202, "GF-BG-SC-20261000000004", "A"),
        (203, "GF-ZD-SC-20261000000005", None),
        (204, "GF-ZD-CW-20261000000006", "A"),
        (205, "OTHER-ZD-SC-20261000000007", "A"),
        (206, "GF--SC-20261000000008", "A"),
    ]:
        file = await seed(session, file_id, target_space, encoding, subcategory)
        file.simhash = "aaaaaaaaaaaaaa55"  # 八位不同, 相似度0.875。
        session.add(file)
    await session.commit()
    svc = _build_svc(session)

    async def candidates():
        if entrypoint == "cached":
            await svc.refresh_similar_candidates_for_file(100, limit=10)
            return await svc.get_similar_candidates_for_file(100, limit=10)
        method = (
            svc.get_shougang_publish_similar_candidates_for_file_in_space
            if entrypoint == "publish"
            else svc.get_similar_candidates_for_file_in_space
        )
        return await method(100, target_space, limit=10)

    configure(
        monkeypatch,
        enable_tfidf_refine=False,
        same_metadata={"simhash_similarity_threshold": 0.8},
        different_metadata={"simhash_similarity_threshold": 0.95},
    )
    assert {c.primary_knowledge_file_id for c in await candidates()} == {200}

    configure(
        monkeypatch,
        enable_tfidf_refine=False,
        same_metadata={"simhash_similarity_threshold": 0.95},
        different_metadata={"simhash_similarity_threshold": 0.8},
    )
    assert {c.primary_knowledge_file_id for c in await candidates()} == {201, 202, 203, 204, 206}


async def test_publish_refines_using_each_library_and_keeps_permission_filter(async_db_session, monkeypatch):
    session = async_db_session
    session.add_all([Knowledge(id=i, name=f"s{i}", type=3, user_id=1) for i in [1, 2]])
    await session.commit()
    await seed(session, 100)
    await seed(session, 200, 2)
    await seed(session, 201, 2, subcategory="B")
    await seed(session, 202, 2)
    svc = _build_svc(session)
    configure(
        monkeypatch,
        same_metadata={"tfidf_similarity_threshold": 0.8},
        different_metadata={"enable_tfidf_refine": False},
    )
    monkeypatch.setattr(
        KnowledgeDao, "aquery_by_id", AsyncMock(side_effect=lambda i: SimpleNamespace(id=i, type=3, tenant_id=1))
    )
    texts = {1: {100: "苹果 苹果 苹果"}, 2: {200: "炼钢设备维护", 201: "不需要复核"}}

    async def search(*, index, size, query, _source):
        filters = query["bool"]["filter"]
        file_ids = filters[0]["terms"]["metadata.content_file_id"]
        space_id = filters[1]["term"]["metadata.knowledge_ids"]
        assert index == "tenant1-shared" and size == 10000
        assert (space_id, set(file_ids)) in [(1, {100}), (2, {200})]
        return {
            "hits": {
                "hits": [
                    {"_source": {"text": texts[space_id][file_id], "metadata": {"content_file_id": file_id}}}
                    for file_id in file_ids
                ]
            }
        }

    search_mock = AsyncMock(side_effect=search)
    monkeypatch.setattr(
        "bisheng.core.search.elasticsearch.manager.get_es_connection",
        AsyncMock(return_value=SimpleNamespace(search=search_mock)),
    )
    monkeypatch.setattr(
        "bisheng.knowledge.rag.shared_space_storage.aresolve_space_shared_routing",
        AsyncMock(return_value=SimpleNamespace(index_name="tenant1-shared")),
    )
    monkeypatch.setattr(
        importlib.import_module("bisheng.core.cache.redis_manager"),
        "get_redis_client",
        AsyncMock(side_effect=ConnectionError("test offline")),
    )
    allowed = AsyncMock(side_effect=lambda file_id: file_id != 202)
    candidates = await svc.get_shougang_publish_similar_candidates_for_file_in_space(100, 2, can_view_file=allowed)
    assert [c.primary_knowledge_file_id for c in candidates] == [201]
    assert search_mock.await_count == 2
    assert {c.args[0] for c in allowed.await_args_list} == {200, 201, 202}


@pytest.mark.parametrize(
    "payload",
    [
        {"same_metadata": {"simhash_similarity_threshold": 1.1}},
        {"different_metadata": {"tfidf_similarity_threshold": -0.1}},
        {"same_metadata": []},
    ],
)
def test_invalid_mode_config_is_rejected_before_database_write(monkeypatch, payload):
    import yaml

    from bisheng.api.v1 import endpoints
    from bisheng.common.errcode.server import SystemConfigInvalidError

    persist = MagicMock()
    load = MagicMock()
    monkeypatch.setattr(endpoints.ConfigDao, "get_config", load)
    monkeypatch.setattr(endpoints.ConfigDao, "insert_config", persist)
    with pytest.raises(SystemConfigInvalidError):
        endpoints.save_config({"data": yaml.safe_dump({"knowledges": {"version_management": payload}})}, object())
    persist.assert_not_called()
    load.assert_not_called()


def test_legacy_config_falls_back_per_field_and_keeps_false_zero():
    from bisheng.core.config.settings import VersionManagementConf

    config = VersionManagementConf(
        simhash_similarity_threshold=0.9,
        enable_tfidf_refine=True,
        tfidf_similarity_threshold=0.5,
        same_metadata={"enable_tfidf_refine": False, "tfidf_similarity_threshold": 0},
    )
    same = config.resolve_similarity_rule(True)
    different = config.resolve_similarity_rule(False)
    assert same.model_dump() == {
        "simhash_similarity_threshold": 0.9,
        "enable_tfidf_refine": False,
        "tfidf_similarity_threshold": 0,
    }
    assert different.model_dump() == {
        "simhash_similarity_threshold": 0.9,
        "enable_tfidf_refine": True,
        "tfidf_similarity_threshold": 0.5,
    }
    assert VersionManagementConf().resolve_similarity_rule(True).simhash_similarity_threshold == 0.85


@pytest.mark.parametrize(
    "encoding,subcategory,expected",
    [
        (" gf-zd-sc-20261000000001 ", " a ", "same_metadata"),
        ("GF-BG-SC-20261000000001", "A", "different_metadata"),
        ("GF-ZD-CW-20261000000001", "A", "different_metadata"),
        ("GF-ZD-SC-20261000000001", None, "different_metadata"),
        ("GF--SC-20261000000001", "A", "different_metadata"),
        ("GF-ZD--20261000000001", "A", "different_metadata"),
    ],
)
def test_mode_compares_all_three_nonempty_metadata_values(encoding, subcategory, expected):
    from bisheng.knowledge.domain.services.knowledge_file_similarity_policy import metadata_mode

    source = KnowledgeFile(file_encoding="GF-ZD-SC-20261000000000", file_subcategory_code="A")
    candidate = KnowledgeFile(file_encoding=encoding, file_subcategory_code=subcategory)
    assert metadata_mode(source, candidate) == expected
    assert metadata_mode(KnowledgeFile(), KnowledgeFile()) == "different_metadata"


def test_valid_mode_config_save_preserves_old_fields_and_clears_cache(monkeypatch):
    import yaml

    from bisheng.api.v1 import endpoints

    stored = SimpleNamespace(value="")
    persist = MagicMock()
    cache = MagicMock()
    monkeypatch.setattr(endpoints.ConfigDao, "get_config", lambda _: stored)
    monkeypatch.setattr(endpoints.ConfigDao, "insert_config", persist)
    monkeypatch.setattr(endpoints, "get_redis_client_sync", lambda: cache)
    data = yaml.safe_dump(
        {
            "knowledges": {
                "version_management": {
                    "simhash_similarity_threshold": 0.92,
                    "same_metadata": {"enable_tfidf_refine": False},
                }
            }
        }
    )
    endpoints.save_config({"data": data}, object())
    assert stored.value == data
    persist.assert_called_once_with(stored)
    cache.delete.assert_called_once_with("config:initdb_config")


async def test_mode_thresholds_apply_to_merge_validation_and_preserve_tenant_boundary(async_db_session, monkeypatch):
    session = async_db_session
    source = await seed(session, 100)
    candidate = await seed(session, 200, subcategory="B")
    configure(monkeypatch, enable_tfidf_refine=False, different_metadata={"simhash_similarity_threshold": 0.9})
    svc = _build_svc(session)
    assert await svc._similarity_matches_threshold(source, candidate)
    candidate.tenant_id = 99
    assert not await svc._similarity_matches_threshold(source, candidate)


async def test_different_mode_refine_threshold_and_missing_es_degrade(async_db_session, monkeypatch):
    session = async_db_session
    source = await seed(session, 100)
    same = await seed(session, 200)
    different = await seed(session, 201, subcategory="B")
    configure(
        monkeypatch,
        same_metadata={"tfidf_similarity_threshold": 0.8},
        different_metadata={"tfidf_similarity_threshold": 0},
    )
    monkeypatch.setattr(KnowledgeDao, "aquery_by_id", AsyncMock(return_value=SimpleNamespace(id=1)))
    svc = _build_svc(session)
    monkeypatch.setattr(svc, "_fetch_chunk_texts", AsyncMock(return_value={100: "苹果", 200: "炼钢", 201: "炼钢"}))
    monkeypatch.setattr(
        svc, "_tokenize_files_cached", AsyncMock(side_effect=lambda items: [text.split() for _, text in items])
    )
    result = await svc._score_similarity_candidates(source, [same, different])
    assert [(file.id, refined) for _, refined, file in result] == [(201, 0)]
    svc._fetch_chunk_texts.return_value = {}
    result = await svc._score_similarity_candidates(source, [same, different])
    assert [(file.id, refined) for _, refined, file in result] == [(200, None), (201, None)]


async def test_secondary_category_change_during_refresh_recalculates_and_keeps_resolved(async_db_session, monkeypatch):
    session = async_db_session
    source = await seed(session, 100, similar_status=2)
    await seed(session, 200)
    configure(
        monkeypatch,
        enable_tfidf_refine=False,
        same_metadata={"simhash_similarity_threshold": 0},
        different_metadata={"simhash_similarity_threshold": 1},
    )
    svc = _build_svc(session)
    calculate = svc._calculate_similarity_candidate_rows
    calls = 0

    async def change_once(*args, **kwargs):
        nonlocal calls
        calls += 1
        result = await calculate(*args, **kwargs)
        if calls == 1:
            source.file_subcategory_code = "B"
            await svc.knowledge_file_repo.update(source)
        return result

    monkeypatch.setattr(svc, "_calculate_similarity_candidate_rows", change_once)
    assert await svc.refresh_similar_candidates_for_file(100) == 1
    assert calls == 2
    assert source.similar_status == 2
    assert await svc.get_similar_candidates_for_file(100) == []


async def test_cross_classification_candidate_can_be_merged_as_new_primary(async_db_session, monkeypatch):
    session = async_db_session
    await seed(session, 100)
    await seed(session, 200, encoding="GF-BG-CW-20261000000002", subcategory="B")
    configure(monkeypatch, enable_tfidf_refine=False)
    svc = _build_svc(session)
    monkeypatch.setattr(svc, "_notify_favorite_version_changed", AsyncMock())
    monkeypatch.setattr(
        "bisheng.knowledge.domain.services.knowledge_audit_telemetry_service."
        "KnowledgeAuditTelemetryService.audit_link_file_version",
        MagicMock(),
    )
    source_version = await svc.version_repo.find_by_knowledge_file_id(200)
    current_version = await svc.version_repo.find_by_knowledge_file_id(100)
    result = await svc.merge_source_document_into_current(100, source_version.document_id)
    primary = await svc.version_repo.find_primary(current_version.document_id)
    assert result.new_version_no == 2
    assert primary.knowledge_file_id == 200
    assert len(await svc.version_repo.find_by_document_id(result.document_id)) == 2
