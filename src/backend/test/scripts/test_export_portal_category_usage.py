# ruff: noqa: RUF001, RUF002, RUF003
"""使用实际查询验证库存、租户边界和去重口径，模拟 ES 查询边界。"""

import csv
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, event
from sqlmodel import Session

from scripts.export_portal_category_usage import (
    UsageRepository,
    build_parser,
    called_file_ids,
    create_dashboard_es_client,
    es_nodes,
    summarize,
    write_report,
)


def test_inventory_and_usage_report(tmp_path, monkeypatch):
    from bisheng.core.context.tenant import current_tenant_id, set_current_tenant_id, strict_tenant_filter
    from bisheng.core.database import tenant_filter

    repo = UsageRepository(None)
    engine = create_engine("sqlite://")
    metadata = MetaData()
    # 独立精简表结构避免 SQLite 不支持生产表的 ON UPDATE 默认值；查询仍使用真实 ORM 模型。
    specs = {
        repo.Space: "id tenant_id type state is_favorite",
        repo.Scope: "id tenant_id space_id level",
        repo.File: "id tenant_id knowledge_id file_type status reference_document_id entry_type entry_status deleted_at file_encoding split_rule user_id",
        repo.Version: "id document_id knowledge_file_id is_primary",
        repo.Config: "key value",
        repo.Department: "id tenant_id name path",
        repo.UserDepartment: "id user_id department_id is_primary",
    }
    tables = {}
    strings = {
        "level",
        "entry_type",
        "entry_status",
        "deleted_at",
        "file_encoding",
        "split_rule",
        "key",
        "value",
        "name",
        "path",
    }
    for model, names in specs.items():
        tables[model] = Table(
            model.__tablename__,
            metadata,
            *[Column(name, String if name in strings else Integer) for name in names.split()],
        )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            tables[repo.Space].insert(),
            [
                {"id": i, "tenant_id": 2 if i == 4 else 1, "type": 3, "is_favorite": False, "state": 5 if i == 5 else 1}
                for i in range(1, 6)
            ],
        )
        connection.execute(
            tables[repo.Scope].insert(),
            [
                {"id": i, "tenant_id": 2 if i == 4 else 1, "space_id": i, "level": "personal" if i == 2 else "public"}
                for i in range(1, 6)
            ],
        )
        files = []
        for i in range(1, 14):
            files.append(
                {
                    "id": i,
                    "tenant_id": 2 if i == 5 else 1,
                    "knowledge_id": 1,
                    "file_type": 1,
                    "status": 2,
                    "reference_document_id": None,
                    "entry_type": None,
                    "entry_status": None,
                    "deleted_at": None,
                    "file_encoding": "SG-PREFIX-POL-PP-202609-000001",
                    "user_id": i,
                }
            )
        files[0].update(reference_document_id=100, entry_type="manager", entry_status="active")
        files[1].update(reference_document_id=100, entry_type="share", entry_status="active", knowledge_id=3)
        files[2].update(knowledge_id=2)
        files[3].update(file_type=0)
        files[4].update(knowledge_id=4)
        files[5].update(deleted_at="2026-09-01", reference_document_id=100)
        files[6].update(status=3)
        files[7].update(reference_document_id=200, entry_type="share", entry_status="invalid")
        files[8].update(knowledge_id=5)
        files[9].update(reference_document_id=300, entry_type="publish", entry_status="preparing")
        # 11 为旧版本；12 为没有分类的有效文件；13 为第二份政策制度。
        files[11].update(file_encoding=None)
        connection.execute(tables[repo.File].insert(), files)
        connection.execute(
            tables[repo.Department].insert(),
            [
                {"id": 10, "tenant_id": 1, "name": "目标组织", "path": "/10/"},
                {"id": 11, "tenant_id": 1, "name": "子组织", "path": "/10/11/"},
                {"id": 12, "tenant_id": 1, "name": "孙组织", "path": "/10/11/12/"},
                {"id": 100, "tenant_id": 1, "name": "目标组织", "path": "/100/"},
                {"id": 21, "tenant_id": 2, "name": "跨租户子组织", "path": "/10/21/"},
                {"id": 30, "tenant_id": 1, "name": "无效路径", "path": ""},
                {"id": 31, "tenant_id": 1, "name": "空组织", "path": "/31/"},
            ],
        )
        connection.execute(
            tables[repo.UserDepartment].insert(),
            [
                {"id": 1, "user_id": 1, "department_id": 11, "is_primary": 1},
                {"id": 2, "user_id": 2, "department_id": 100, "is_primary": 1},
                {"id": 3, "user_id": 2, "department_id": 10, "is_primary": 0},
                {"id": 4, "user_id": 12, "department_id": 12, "is_primary": 1},
                {"id": 5, "user_id": 13, "department_id": 10, "is_primary": 1},
                {"id": 6, "user_id": 3, "department_id": 10, "is_primary": 1},
            ],
        )
        connection.execute(
            tables[repo.Version].insert(), [{"id": 1, "document_id": 100, "knowledge_file_id": 11, "is_primary": 0}]
        )
        connection.execute(
            tables[repo.Config].insert(),
            [
                {
                    "key": "shougang_portal_config",
                    "value": json.dumps(
                        {
                            "portal": {
                                "document_types": [
                                    {"code": "POL", "label": "政策制度", "children": [{"code": "POL-A"}]},
                                    {"code": "STD", "label": "标准规范"},
                                ]
                            }
                        }
                    ),
                }
            ],
        )
    tenant_filter.register_tenant_filter_events()
    tenant_filter._tenant_aware_tables = tenant_filter._discover_tenant_aware_tables()
    statements = []
    event.listen(engine, "before_cursor_execute", lambda conn, cursor, stmt, params, ctx, many: statements.append(stmt))
    token = set_current_tenant_id(1)
    try:
        with strict_tenant_filter(), Session(engine) as session:
            repo.session = session
            inventory = repo.inventory()
            assert {row["id"] for row in inventory} == {1, 2, 12, 13}
            from contextlib import nullcontext

            from bisheng.telemetry.domain.repositories.implementations import (
                knowledge_statistics_repository_impl as dashboard_repo,
            )

            monkeypatch.setattr(dashboard_repo, "get_sync_db_session", lambda: nullcontext(session))
            identities = dashboard_repo.KnowledgeStatisticsRepositoryImpl.identities([1, 2, 6, 11, 12, 13])
            assert identities == {
                1: "document:100",
                2: "document:100",
                6: "document:100",
                11: "document:100",
                12: "file:12",
                13: "file:13",
            }
            assert dashboard_repo.KnowledgeStatisticsRepositoryImpl.aliases(set(identities.values())) == identities
            aliases = repo.historical_aliases(inventory)
            assert set(aliases) == {1, 2, 6, 11, 12, 13}
            rows = summarize(repo.categories(1), inventory, {aliases[11], aliases[2], aliases[6]})
            assert rows == [["政策制度", 2, 1, "50.00%"], ["标准规范", 0, 0, "0.00%"], ["未分类", 1, 0, "0.00%"]]
            # 根组织、子组织、孙组织入选；同名旁支、兼职组织、个人库不混入。
            scope = repo.department_scope(10)
            assert {row["id"] for row in scope["departments"]} == {10, 11, 12}
            scoped_inventory = repo.inventory(scope)
            assert {row["id"] for row in scoped_inventory} == {1, 12, 13}
            assert {row["id"] for row in repo.inventory(repo.department_scope(11))} == {1, 12}
            assert repo.inventory(repo.department_scope(31)) == []
            # 唯一调用发生在组织外的分享入口，仍归入目标组织的同一份知识。
            scoped_aliases = repo.historical_aliases(scoped_inventory)
            assert set(scoped_aliases) == {1, 2, 6, 11, 12, 13}
            called_ids = called_file_ids(
                FakeES(
                    documents=[
                        {"file_id": "2", "space_level": "public", "record_type": "download_daily", "download_count": 3},
                        {"file_id": "3", "space_level": "personal", "record_type": "preview_daily", "preview_count": 8},
                    ]
                ),
                "dataset",
                sorted(scoped_aliases),
            )
            assert (
                summarize(repo.categories(1), scoped_inventory, {scoped_aliases[file_id] for file_id in called_ids})
                == rows
            )
            for invalid_id in (21, 999):
                with pytest.raises(ValueError, match="不存在或不属于当前租户"):
                    repo.department_scope(invalid_id)
            with pytest.raises(ValueError, match="层级路径无效"):
                repo.department_scope(30)
            # 成员关系表没有租户字段，必须只使用已验证属于当前租户的组织 ID。
            session.execute(
                tables[repo.UserDepartment]
                .update()
                .where(tables[repo.UserDepartment].c.user_id == 13)
                .values(department_id=21)
            )
            assert statements.pop().lstrip().upper().startswith("UPDATE")
            assert {row["id"] for row in repo.inventory(scope)} == {1, 12}
            session.execute(tables[repo.UserDepartment].delete().where(tables[repo.UserDepartment].c.user_id == 12))
            assert statements.pop().lstrip().upper().startswith("DELETE")
            assert {row["id"] for row in repo.inventory(scope)} == {1}
            session.rollback()
    finally:
        current_tenant_id.reset(token)
        engine.dispose()
    assert all(stmt.lstrip().upper().startswith("SELECT") for stmt in statements)
    directory = tmp_path / "report"
    write_report(directory, rows, {"知识总数": 3})
    with (directory / "知识分类调用统计.csv").open(encoding="utf-8-sig") as stream:
        result = list(csv.reader(stream))
    assert result[1] == ["政策制度", "2", "1", "50.00%"]
    assert not (directory / "未完成.txt").exists()
    with pytest.raises(FileExistsError):
        write_report(directory, [], {})


class FakeES:
    def __init__(self, failure=None, documents=None):
        self.indices = SimpleNamespace(exists=lambda **kwargs: failure != "missing")
        self.failure = failure
        self.batches = []
        self.documents = (
            documents
            if documents is not None
            else [
                {
                    "file_id": str(file_id),
                    "space_level": "department",
                    "record_type": record_type,
                    metric: int(file_id % divisor == remainder),
                }
                for file_id in range(1, 806)
                for record_type, metric, divisor, remainder in [
                    ("preview_daily", "preview_count", 2, 1),
                    ("download_daily", "download_count", 3, 0),
                ]
            ]
        )

    def search(self, **kwargs):
        filters = kwargs["query"]["bool"]["filter"]
        batch = next(item["terms"]["file_id"] for item in filters if "file_id" in item.get("terms", {}))
        self.batches.extend(int(value) for value in batch)
        assert all(isinstance(value, str) for value in batch)
        assert kwargs["aggs"]["files"]["terms"]["size"] == len(batch)
        assert kwargs["allow_partial_search_results"] is False
        matched = [
            doc
            for doc in self.documents
            if all(all(doc.get(field) in values for field, values in clause["terms"].items()) for clause in filters)
        ]
        buckets = []
        for file_id in sorted({doc["file_id"] for doc in matched}):
            docs = [doc for doc in matched if doc["file_id"] == file_id]
            bucket = {"key": file_id, "doc_count": len(docs)}
            for name, metric in kwargs["aggs"]["files"]["aggs"].items():
                field, expected = next(iter(metric["filter"]["term"].items()))
                sum_field = metric["aggs"]["count"]["sum"]["field"]
                bucket[name] = {
                    "count": {"value": sum(doc.get(sum_field, 0) for doc in docs if doc.get(field) == expected)}
                }
            buckets.append(bucket)
        return {
            "timed_out": self.failure == "timeout",
            "terminated_early": self.failure == "terminated",
            "_shards": {"failed": int(self.failure == "shard")},
            "aggregations": {
                "files": {
                    "sum_other_doc_count": int(self.failure == "truncated"),
                    "buckets": buckets,
                }
            },
        }


def test_event_union_covers_all_batches_without_counting_repeats():
    client = FakeES()
    ids = list(range(1, 806))
    assert called_file_ids(client, "dataset", ids) == {
        file_id for file_id in ids if file_id % 2 == 1 or file_id % 3 == 0
    }
    assert set(client.batches) == set(ids)


def test_dataset_merges_daily_counts_excludes_personal_and_unrelated_records():
    def doc(file_id, record_type, **values):
        return {"file_id": str(file_id), "space_level": "public", "record_type": record_type, **values}

    documents = [
        doc(1, "preview_daily", preview_count=2, local_date="2026-09-20"),
        doc(1, "preview_daily", preview_count=3, local_date="2026-09-21"),
        doc(1, "download_daily", download_count=9),
        doc(2, "download_daily", download_count=4),
        doc(3, "preview_daily", preview_count=0),
        doc(3, "download_daily", download_count=0),
        doc(4, "favorite_daily", favorite_count=99, preview_count=99),
        doc(5, "portal_engagement_daily", preview_count=99, download_count=99),
        doc(6, "preview_daily", preview_count=99, space_level="personal"),
        doc(7, "preview_daily", preview_count=0, download_count=99),
        doc(8, "download_daily", download_count=0, preview_count=99),
        doc(9, "preview_daily", preview_count=99, space_level="unknown"),
        doc(10, "file", preview_count=99),
        doc(11, "preview_daily", preview_count=99, space_level=None),
        doc(12, "preview_daily", preview_count=99),
    ]
    assert called_file_ids(FakeES(documents=documents), "dataset", list(range(1, 12))) == {1, 2}


def test_verbose_distinguishes_request_start_and_received_response(capsys):
    class BrokenES(FakeES):
        def search(self, **kwargs):
            raise ConnectionError("unavailable")

    with pytest.raises(ConnectionError):
        called_file_ids(BrokenES(), "dataset", [1], verbose=True)
    failed_log = capsys.readouterr().err
    assert "准备查询 ES 批次=1" in failed_log
    assert "已收到 ES 响应：批次=" not in failed_log
    called_file_ids(FakeES(), "dataset", [1], verbose=True)
    log = capsys.readouterr().err
    assert "已收到 ES 响应：批次=1 有统计记录文件数=1 已调用文件数=1" in log


def test_es_node_diagnostics_omit_credentials():
    from elasticsearch import Elasticsearch

    # 初始化客户端不连接服务，验证真实客户端的节点结构与脱敏输出。
    with Elasticsearch("http://localhost:9200", basic_auth=("diagnostic-user", "test-only")) as client:
        assert es_nodes(client) == "localhost:9200"


def test_client_uses_dashboard_configuration_and_dataset_default():
    settings = SimpleNamespace(
        get_search_conf=lambda: SimpleNamespace(elasticsearch_url="http://localhost:9201", ssl_verify={})
    )
    with create_dashboard_es_client(settings) as client:
        assert es_nodes(client) == "localhost:9201"
    assert build_parser().parse_args(["--tenant-id", "1"]).es_index == "mid_knowledge_space_content_stat"
    assert build_parser().parse_args(["--tenant-id", "1"]).department_id is None
    assert build_parser().parse_args(["--tenant-id", "1", "--department-id", "10"]).department_id == 10


@pytest.mark.parametrize("failure", ["missing", "timeout", "shard", "truncated", "terminated"])
def test_incomplete_telemetry_fails_instead_of_reporting_zero(failure):
    with pytest.raises(ValueError):
        called_file_ids(FakeES(failure), "dataset", [1])


def test_distinct_id_namespaces_and_conflicting_categories():
    categories = [{"code": "POL", "label": "政策制度"}]
    inventory = [
        {"id": 1, "document_id": 9, "file_encoding": "SG-POL-PP-123"},
        {"id": 9, "document_id": None, "file_encoding": "SG-POL-PP-123"},
    ]
    assert summarize(categories, inventory, {("file", 9)}) == [["政策制度", 2, 1, "50.00%"]]
    inventory.append({"id": 2, "document_id": 9, "file_encoding": "SG-STD-PP-123"})
    with pytest.raises(ValueError, match="分类冲突"):
        summarize(categories, inventory, set())
