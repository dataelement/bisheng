#!/usr/bin/env python3
"""一次性脚本：合并审核通过时产生的重复标签行。

## 背景

审核通过一个标签时，后台做了两件互不相干的写入：

1. 把标签名注册进 **审核人选择的标签库** —— 留下一行 ``tag``，
   ``user_id`` 是审核人、``create_time`` 是审核当下、没有审核留痕、没有文件关联。
2. 把审核记录搬进 ``tag`` —— 数据是对的（原提报人、原创建时间、审核留痕、
   文件关联），但标签库取的是 ``review_tag.business_id``，也就是
   **提出该标签的库**，而不是审核人选的那个。

于是一次通过留下两行。历史上出现过两种形态：

- **跨库重复**：两行落在不同标签库 —— 库对的那行没数据，数据对的那行库不对。
- **同库重复**：搬迁已经用对了标签库，但"这行是不是已经存在"的查询受 MySQL
  REPEATABLE READ 影响看不见第 1 步刚提交的行，于是在同一个库里又插了一条。

两种都已在代码里修掉，本脚本负责清理修复之前产生的存量数据。

## 合并规则

按 ``(tenant_id, name)`` 分组。**有文件关联的那行**是数据行 —— 只有搬迁写出来的
行才带文件关联，原提报人、原创建时间、审核留痕也都在它身上；没有文件关联的那行
是第 1 步留下的空壳。

- **跨库**：留下**空壳所在的库**（那才是审核人选的），把数据行的
  ``user_id`` / ``create_time`` / ``reviewer_id`` / ``review_time`` 和文件关联
  搬过去，然后删掉数据行。
- **同库**：不存在"哪个库才对"的问题，直接留下数据行、删掉空壳，**不改任何字段**。

## 用法

在 ``src/backend`` 目录下运行：

    # Dry-run（默认，只打印将要做什么，不写 DB）
    python scripts/merge_duplicate_approved_tags.py

    # 只看某个租户
    python scripts/merge_duplicate_approved_tags.py --tenant 1

    # 真正应用
    python scripts/merge_duplicate_approved_tags.py --apply

## 安全保证

- **只处理刚好两行、且能明确区分 keeper/donor 的组**。三行以上、两行都有
  文件关联、两行都没有文件关联、或创建时间无法区分的，一律跳过并打印原因，
  留给人工判断——绝不猜。
- 只碰 ``business_type='tag_library'`` 的行，应用标签/知识标签不受影响。
- 单次事务，失败整体回滚。
- Dry-run 是默认行为，必须显式 ``--apply`` 才会写库。
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from sqlalchemy import text as sa_text  # noqa: E402

from bisheng.core.context.tenant import bypass_tenant_filter  # noqa: E402
from bisheng.core.database import get_sync_db_session  # noqa: E402

SCAN_SQL = sa_text("""
    SELECT t.id, t.tenant_id, t.name, t.business_id, t.resource_type,
           t.user_id, t.create_time, t.reviewer_id, t.review_time,
           (SELECT COUNT(*) FROM taglink tl WHERE tl.tag_id = t.id) AS link_count
    FROM tag t
    WHERE t.business_type = 'tag_library'
      AND (:tenant_id IS NULL OR t.tenant_id = :tenant_id)
    ORDER BY t.tenant_id, t.name, t.id
""")

MERGE_TAG_SQL = sa_text("""
    UPDATE tag
       SET user_id = :user_id,
           create_time = :create_time,
           reviewer_id = :reviewer_id,
           review_time = :review_time
     WHERE id = :keeper_id
""")

MOVE_LINKS_SQL = sa_text("UPDATE taglink SET tag_id = :keeper_id WHERE tag_id = :donor_id")

DROP_CLASHING_LINKS_SQL = sa_text("""
    DELETE FROM taglink
     WHERE tag_id = :donor_id
       AND resource_id IN (SELECT resource_id FROM (
             SELECT resource_id FROM taglink WHERE tag_id = :keeper_id
           ) AS kept)
""")

DELETE_TAG_SQL = sa_text("DELETE FROM tag WHERE id = :donor_id")


class Row:
    __slots__ = (
        "business_id",
        "create_time",
        "id",
        "link_count",
        "name",
        "resource_type",
        "review_time",
        "reviewer_id",
        "tenant_id",
        "user_id",
    )

    def __init__(self, record):
        (
            self.id,
            self.tenant_id,
            self.name,
            self.business_id,
            self.resource_type,
            self.user_id,
            self.create_time,
            self.reviewer_id,
            self.review_time,
            self.link_count,
        ) = record

    def __repr__(self) -> str:
        return (
            f"tag.id={self.id} lib={self.business_id} user={self.user_id} "
            f"links={self.link_count} created={self.create_time} reviewer={self.reviewer_id}"
        )


def _carries_the_data(row: Row) -> bool:
    """Whether this row holds the real values rather than being a placeholder.

    The file links are the tell: only the row written by moving the review
    record has them, and it is also the one carrying the original proposer,
    submission time and audit trail. Copying fields off a placeholder would
    blank exactly what the merge is meant to preserve.
    """
    return row.link_count > 0


def classify(rows: list[Row]) -> tuple[Row | None, Row | None, str | None]:
    """Return ``(keeper, donor, skip_reason)`` for one duplicated name.

    Deliberately conservative: anything that does not match the exact shape this
    bug produces is left untouched. A wrong guess here silently rewrites who
    proposed a tag, which is not recoverable.
    """
    if len(rows) != 2:
        return None, None, f"{len(rows)} 行，只处理刚好 2 行的情况"

    with_links = [row for row in rows if row.link_count > 0]
    without_links = [row for row in rows if row.link_count == 0]
    if len(with_links) != 1 or len(without_links) != 1:
        return None, None, "两行的文件关联情况相同，无法区分哪行是审核人选的库"

    keeper, donor = without_links[0], with_links[0]
    if keeper.business_id == donor.business_id:
        # 同一个库里的两行 —— 修复过程中的第二种形态：搬迁已经用对了标签库，
        # 但"这行是不是已经存在"的查询受 MySQL REPEATABLE READ 影响看不见
        # 注册那一步刚提交的行，于是在同一个库里又插了一条。
        #
        # 这时没有"哪个库才对"的问题，只需要留下有数据的那行、删掉空壳，
        # 所以 keeper/donor 与跨库的情况正好相反。
        return donor, keeper, None
    if keeper.create_time is None or donor.create_time is None:
        return None, None, "创建时间缺失，无法确认先后"
    if keeper.create_time < donor.create_time:
        return None, None, "无关联的那行反而更早，形态不符"
    return keeper, donor, None


def main() -> int:
    parser = argparse.ArgumentParser(description="合并审核通过产生的重复标签行")
    parser.add_argument("--apply", action="store_true", help="真正写库，默认只做 dry-run")
    parser.add_argument("--tenant", type=int, default=None, help="只处理指定租户")
    args = parser.parse_args()

    # Scripts run outside the request lifecycle, so the automatic tenant filter
    # has no tenant to inject and would narrow these tables to nothing.
    with bypass_tenant_filter(), get_sync_db_session() as session:
        records = list(session.execute(SCAN_SQL, {"tenant_id": args.tenant}))

    grouped: dict[tuple[int, str], list[Row]] = defaultdict(list)
    for record in records:
        row = Row(record)
        grouped[(row.tenant_id, row.name)].append(row)

    duplicates = {key: rows for key, rows in grouped.items() if len(rows) > 1}
    if not duplicates:
        print(f"扫描 {len(records)} 行标签，未发现同名分布在多个标签库的情况。无需处理。")
        return 0

    plans: list[tuple[str, Row, Row]] = []
    skipped: list[tuple[str, int, str]] = []
    for (tenant_id, name), rows in sorted(duplicates.items()):
        keeper, donor, reason = classify(rows)
        if reason is not None:
            skipped.append((name, tenant_id, reason))
            continue
        plans.append((name, keeper, donor))

    print(f"扫描标签行:            {len(records)}")
    print(f"同名跨库的标签:        {len(duplicates)}")
    print(f"  - 可合并:            {len(plans)}")
    print(f"  - 跳过(需人工):      {len(skipped)}")
    print()

    if plans:
        print("将要合并（保留 <- 合入）:")
        for name, keeper, donor in plans:
            print(f"  「{name}」 tenant={keeper.tenant_id}")
            print(f"      保留 {keeper}")
            print(f"      合入 {donor}")
            if _carries_the_data(donor):
                print(
                    f"      -> 提报者 {keeper.user_id} 改为 {donor.user_id}，"
                    f"创建时间 {keeper.create_time} 改为 {donor.create_time}，"
                    f"审核留痕 {donor.reviewer_id}/{donor.review_time}，"
                    f"迁移 {donor.link_count} 条文件关联"
                )
            else:
                print("      -> 同库重复，保留行数据不变，仅删除空壳行")
        print()

    if skipped:
        print("跳过（形态不符，需人工确认）:")
        for name, tenant_id, reason in skipped:
            print(f"  「{name}」 tenant={tenant_id}: {reason}")
        print()

    if not args.apply:
        print("Dry-run，未写库。确认无误后加 --apply 执行。")
        return 0

    if not plans:
        print("没有可自动合并的行。")
        return 0

    with bypass_tenant_filter(), get_sync_db_session() as session:
        for _name, keeper, donor in plans:
            if _carries_the_data(donor):
                session.execute(
                    MERGE_TAG_SQL,
                    {
                        "keeper_id": keeper.id,
                        "user_id": donor.user_id,
                        "create_time": donor.create_time,
                        "reviewer_id": donor.reviewer_id,
                        "review_time": donor.review_time,
                    },
                )
            # A file already linked to the keeper must not gain a second link.
            session.execute(DROP_CLASHING_LINKS_SQL, {"keeper_id": keeper.id, "donor_id": donor.id})
            session.execute(MOVE_LINKS_SQL, {"keeper_id": keeper.id, "donor_id": donor.id})
            session.execute(DELETE_TAG_SQL, {"donor_id": donor.id})
        session.commit()

    print(f"已合并 {len(plans)} 组重复标签。")
    print("提示：标签库的 tag_count 由列表接口实时统计，无需额外刷新；")
    print("      AI 打标候选词缓存 100s 内自动过期。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
