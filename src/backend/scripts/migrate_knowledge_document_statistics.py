#!/usr/bin/env python3
# ruff: noqa: RUF001, RUF002, RUF003
"""保留历史调用数据，在新索引完成校验后切换知识空间统计；默认只读预检。

须从后端目录执行。--apply 前暂停业务写入及统计 worker/beat；详见 README。
不调用旧的删除重建脚本，不修改数据库，不清理原始事件或 Redis 回放位置。
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

SOURCE = "mid_knowledge_space_content_stat"


class Fingerprint:
    """逐记录内容校验，独立于分页顺序；计数与指标合计同时核对。"""

    def __init__(self):
        self.counts = Counter()
        self.sums = Counter()
        self.digest = 0

    def add(self, identity, source):
        payload = json.dumps([str(identity), source], sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        self.digest = (self.digest + int.from_bytes(hashlib.sha256(payload.encode()).digest(), "big")) % (2**256)
        self.counts[source.get("record_type", "missing")] += 1
        for field in ("preview_count", "download_count", "favorite_count"):
            self.sums[field] += source.get(field, 0) or 0

    def report(self):
        return {"records": dict(self.counts), "operation_counts": dict(self.sums), "sha256_sum": f"{self.digest:064x}"}


def current_files():
    from bisheng.worker.telemetry.mid_table import _build_knowledge_space_content_records, _get_success_space_file_rows

    page = 1
    while rows := _get_success_space_file_rows(page, 500):
        records, _ = _build_knowledge_space_content_records(rows, {})
        for record in records:
            source = record.model_dump()
            identity = source.pop("es_id")
            # 此字段只记录投影运行时间，不参与库存内容一致性比较。
            source.pop("projection_updated_at", None)
            yield identity, source
        page += 1


def scan(client, index):
    """完整读取快照；即使空页也检查超时、分片状态和精确总条数。"""
    response = client.search(
        index=index,
        query={"match_all": {}},
        size=500,
        sort="_doc",
        scroll="2m",
        track_total_hits=True,
        allow_partial_search_results=False,
    )
    scroll_id = response.get("_scroll_id")
    count = 0
    total = response["hits"]["total"]
    try:
        if total.get("relation") != "eq":
            raise RuntimeError("ES 未返回精确记录总数，停止迁移")
        while True:
            scroll_id = response.get("_scroll_id", scroll_id)
            if (
                response.get("timed_out")
                or response.get("terminated_early")
                or response.get("_shards", {}).get("failed", 0)
            ):
                raise RuntimeError("ES 快照读取不完整，停止迁移")
            hits = response["hits"]["hits"]
            count += len(hits)
            yield from hits
            if not hits:
                break
            if not scroll_id:
                raise RuntimeError("ES 快照缺少分页游标，停止迁移")
            response = client.scroll(scroll_id=scroll_id, scroll="2m")
        if count != total["value"]:
            raise RuntimeError("ES 快照读取条数与精确总数不一致，停止迁移")
    finally:
        if scroll_id:
            client.clear_scroll(scroll_id=scroll_id)


def inspect(client, index, renew=lambda: None):
    fingerprint = Fingerprint()
    for number, hit in enumerate(scan(client, index)):
        if number % 500 == 0:
            renew()
        fingerprint.add(hit["_id"], hit["_source"])
    return fingerprint.report()


def history_diagnostics(client, index, renew=lambda: None):
    from bisheng.telemetry.domain.repositories.implementations.knowledge_statistics_repository_impl import (
        KnowledgeStatisticsRepositoryImpl,
    )

    file_ids = set()
    missing_file_records = 0
    for number, hit in enumerate(scan(client, index)):
        if number % 500 == 0:
            renew()
        source = hit["_source"]
        if source.get("record_type") == "file":
            continue
        try:
            file_id = int(source.get("file_id"))
        except (TypeError, ValueError):
            missing_file_records += 1
            continue
        file_ids.add(file_id)
    identities = KnowledgeStatisticsRepositoryImpl.identities(sorted(file_ids))
    missing = sorted(file_ids - identities.keys())
    return {
        "historical_file_count": len(file_ids),
        "unresolved_file_count": len(missing),
        "unresolved_file_ids_sample": missing[:20],
        "records_without_file_id": missing_file_records,
    }


def migrate(client, args, *, files=current_files, renew=lambda: True):
    source_info = client.indices.get(index=SOURCE)
    if len(source_info) != 1:
        raise ValueError("源名称必须仅指向一个实体索引，不能合并多个索引迁移")
    physical, info = next(iter(source_info.items()))
    if physical == SOURCE and info.get("aliases"):
        raise ValueError("源实体索引还有其他别名，需先明确这些别名的切换范围")
    for target in (args.target_index, args.backup_index):
        if not target or not re.fullmatch(r"mid_knowledge_space_content_stat-[a-z0-9-]+", target):
            raise ValueError("目标和备份索引须使用 mid_knowledge_space_content_stat- 前缀及小写字母数字连字符")
        if client.indices.exists(index=target):
            raise ValueError("目标或备份索引已存在，请使用新名称；不会覆盖已有索引")
    if args.target_index == args.backup_index:
        raise ValueError("目标和备份索引不能相同")
    report = {"source": SOURCE, "source_physical": physical, "target": args.target_index, "backup": args.backup_index}
    if not args.apply:
        report.update(mode="dry-run", source_statistics=inspect(client, physical))
        inventory = Fingerprint()
        for identity, source in files():
            inventory.add(identity, source)
        report["current_inventory"] = inventory.report()
        report["history_link_diagnostics"] = history_diagnostics(client, physical)
        return report
    if not args.writers_paused or args.confirm_index != SOURCE:
        raise ValueError("执行须声明 --writers-paused 并通过 --confirm-index 指定准确源索引")

    def lease():
        if not renew():
            raise RuntimeError("统计迁移锁已丢失，停止切换")

    original_block = info.get("settings", {}).get("index", {}).get("blocks", {}).get("write", "false")
    switched = False
    switch_attempted = False
    client.indices.put_settings(index=physical, settings={"index.blocks.write": True})
    try:
        from elasticsearch.helpers import bulk

        from bisheng.telemetry.domain.mid_table.base import common_settings
        from bisheng.telemetry.domain.mid_table.knowledge_space_content import KnowledgeSpaceContentStat

        lease()
        client.indices.refresh(index=physical)
        target_settings = copy.deepcopy(common_settings)
        for key in ("number_of_shards", "number_of_replicas"):
            if key in info.get("settings", {}).get("index", {}):
                target_settings[key] = info["settings"]["index"][key]
        client.indices.create(
            index=args.target_index,
            settings=target_settings,
            mappings={
                "properties": KnowledgeSpaceContentStat(ensure_sync_index=False)._mappings,
            },
        )
        source_fingerprint, expected, inventory_fingerprint = Fingerprint(), Fingerprint(), Fingerprint()
        pending = []

        def append(identity, source):
            expected.add(identity, source)
            pending.append({"_op_type": "create", "_index": args.target_index, "_id": identity, "_source": source})
            if len(pending) >= 500:
                flush()

        def flush():
            lease()
            if pending:
                bulk(client, pending, raise_on_error=True, raise_on_exception=True)
                pending.clear()

        for number, hit in enumerate(scan(client, physical)):
            if number % 500 == 0:
                lease()
            source_fingerprint.add(hit["_id"], hit["_source"])
            if hit["_source"].get("record_type") != "file":
                append(hit["_id"], hit["_source"])
        for identity, source in files():
            inventory_fingerprint.add(identity, source)
            append(identity, source)
        flush()
        client.indices.refresh(index=args.target_index)
        actual = inspect(client, args.target_index, lease)
        if actual != expected.report():
            raise RuntimeError("新索引内容或调用次数校验失败，未切换")
        second_inventory = Fingerprint()
        for number, (identity, source) in enumerate(files()):
            if number % 500 == 0:
                lease()
            second_inventory.add(identity, source)
        if second_inventory.report() != inventory_fingerprint.report():
            raise RuntimeError("重建期间数据库库存发生变化，未切换；请暂停业务写入后重试")
        lease()
        client.indices.clone(index=physical, target=args.backup_index, wait_for_active_shards="1")
        client.indices.refresh(index=args.backup_index)
        if inspect(client, args.backup_index, lease) != source_fingerprint.report():
            raise RuntimeError("备份内容校验失败，未切换")
        client.indices.put_mapping(
            index=args.target_index,
            _meta={
                "document_statistics_version": 1,
                "source_backup": args.backup_index,
                "backup_validation": source_fingerprint.report(),
                "target_validation": actual,
                "migrated_at": datetime.now().astimezone().isoformat(),
            },
        )
        report["history_link_diagnostics"] = history_diagnostics(client, physical, lease)
        lease()
        actions = [
            {"remove_index": {"index": physical}}
            if physical == SOURCE
            else {"remove": {"index": physical, "alias": SOURCE}},
            {"add": {"index": args.target_index, "alias": SOURCE, "is_write_index": True}},
        ]
        switch_attempted = True
        response = client.indices.update_aliases(actions=actions)
        if not response.get("acknowledged"):
            raise RuntimeError("索引切换应答不确定，请检查别名；所有备份保留")
        switched = True
        report.update(mode="apply", validated=actual, switched=True, source_statistics=source_fingerprint.report())
        return report
    finally:
        # 切换请求已发出但应答失败时不猜测最终状态，保留只读源/备份以便人工核查。
        if not switched and not switch_attempted:
            client.indices.put_settings(index=physical, settings={"index.blocks.write": original_block})


def rollback(client, args, *, renew=lambda: True):
    """只允许无新增写入的原样回退；继续保留新索引，禁止覆盖。"""
    info = client.indices.get(index=SOURCE)
    if list(info) != [args.target_index]:
        raise ValueError("当前别名未指向指定目标索引，拒绝回退")
    metadata = info[args.target_index].get("mappings", {}).get("_meta", {})
    if metadata.get("source_backup") != args.backup_index:
        raise ValueError("备份与当前迁移记录不匹配，拒绝回退")

    def lease():
        if not renew():
            raise RuntimeError("迁移锁已丢失，停止回退")

    if inspect(client, args.backup_index, lease) != metadata.get("backup_validation"):
        raise RuntimeError("备份校验不一致，拒绝回退")
    if inspect(client, args.target_index, lease) != metadata.get("target_validation"):
        raise RuntimeError("迁移后已有新写入，须先核对新增数据；拒绝直接回退")
    report = {
        "mode": "rollback" if args.apply else "rollback-dry-run",
        "source": args.target_index,
        "restore": args.backup_index,
    }
    if not args.apply:
        return report
    if not args.writers_paused or args.confirm_index != SOURCE:
        raise ValueError("回退须声明暂停写入，并确认准确源索引")
    lease()
    client.indices.put_settings(index=args.target_index, settings={"index.blocks.write": True})
    client.indices.refresh(index=args.target_index)
    if inspect(client, args.target_index, lease) != metadata.get("target_validation"):
        raise RuntimeError("回退预检后有新写入，已阻止切换；目标保持只读，请核查")
    client.indices.put_settings(index=args.backup_index, settings={"index.blocks.write": False})
    response = client.indices.update_aliases(
        actions=[
            {"remove": {"index": args.target_index, "alias": SOURCE}},
            {"add": {"index": args.backup_index, "alias": SOURCE, "is_write_index": True}},
        ]
    )
    if not response.get("acknowledged"):
        raise RuntimeError("回退应答不确定，请检查别名；新旧索引均保留")
    report["switched"] = True
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config")
    parser.add_argument("--target-index", required=True)
    parser.add_argument("--backup-index", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--rollback", action="store_true", help="校验迁移后尚无新写入，再回切已验证备份")
    parser.add_argument("--writers-paused", action="store_true")
    parser.add_argument("--confirm-index")
    args = parser.parse_args()
    if args.config:
        os.environ["config"] = args.config
    from bisheng.common.services.config_service import settings
    from bisheng.core.context.tenant import bypass_tenant_filter
    from bisheng.telemetry.domain.mid_table.knowledge_space_content import KnowledgeSpaceContentStat
    from scripts.export_portal_category_usage import create_dashboard_es_client

    token = None
    try:
        if args.apply:
            token = KnowledgeSpaceContentStat.acquire_lock_sync()
            if token is None:
                raise RuntimeError("统计同步正在运行，请暂停后重试")
        with bypass_tenant_filter(), create_dashboard_es_client(settings) as client:
            operation = rollback if args.rollback else migrate
            result = operation(
                client, args, renew=lambda: not args.apply or KnowledgeSpaceContentStat.renew_lock_sync(token)
            )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(f"迁移失败：{type(exc).__name__}。保留已创建的目标和备份，请核查后使用新名称重试。", file=sys.stderr)
        if isinstance(exc, (ValueError, RuntimeError)):
            print(str(exc), file=sys.stderr)
        return 1
    finally:
        if token:
            KnowledgeSpaceContentStat.release_lock_sync(token)


if __name__ == "__main__":
    raise SystemExit(main())
