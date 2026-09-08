#!/usr/bin/env python3
"""根据指定的目标知识库类型下所有有效主文件，给原始上传人批量增加指定积分。

核心特性：
1. 目标库类型：支持 public/department/team/team_ks 及中文别名。
2. 主文件判定：排除目录(file_type=0)、回收站(deleted_at is not null)、分享引用(entry_type='share')及多版本文档中的历史非主版本。
3. 受让人判定：优先 original_uploader_id，为空回退 user_id。
4. 管理员默认过滤：默认自动识别并排除「系统超级管理员」(AdminRole)与「部门管理员」(DepartmentAdminGrant)，不予发分。
5. 忽略账号：匹配 user.user_name，额外支持传入自定义需忽略的账号。
6. 积分规则：突破单日 15 分 daily_cap 限制全额累加，按文件 ID 生成强幂等键防重跑。
7. 支持 --dry-run 演练预览模式。
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# 自动适配 bisheng 后端模块导入路径（兼容 bisheng/scripts 和 src/backend/scripts）
_FILE_PATH = Path(__file__).resolve()
for parent in _FILE_PATH.parents:
    if (parent / "bisheng").is_dir() and (parent / "pyproject.toml").is_file():
        if str(parent) not in sys.path:
            sys.path.insert(0, str(parent))
        break
    if (parent / "src" / "backend" / "bisheng").is_dir():
        backend_dir = parent / "src" / "backend"
        if str(backend_dir) not in sys.path:
            sys.path.insert(0, str(backend_dir))
        break

from sqlalchemy import or_
from sqlmodel import col, select

from bisheng.core.database import get_async_db_session
from bisheng.database.constants import AdminRole
from bisheng.database.models.department_admin_grant import DepartmentAdminGrant
from bisheng.knowledge.domain.models.knowledge_document import (
    KnowledgeDocument,
    KnowledgeDocumentLifecycleStatus,
)
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import (
    FileType,
    KnowledgeFile,
    KnowledgeFileEntryType,
)
from bisheng.knowledge.domain.models.knowledge_space_scope import (
    KnowledgeSpaceLevelEnum,
    KnowledgeSpaceScope,
)
from bisheng.points.domain.constants.space_level_rules import earn_rule_for_space_level
from bisheng.points.domain.repositories.points_repository import PointsRepository
from bisheng.points.domain.services.points_ledger_service import PointsLedgerService
from bisheng.user.domain.models.user import User
from bisheng.user.domain.models.user_role import UserRole

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("backfill_points")

# 中英文空间级别映射表
SPACE_LEVEL_ALIASES: dict[str, str] = {
    "public": KnowledgeSpaceLevelEnum.PUBLIC.value,
    "公共库": KnowledgeSpaceLevelEnum.PUBLIC.value,
    "公共知识库": KnowledgeSpaceLevelEnum.PUBLIC.value,
    "department": KnowledgeSpaceLevelEnum.DEPARTMENT.value,
    "部门库": KnowledgeSpaceLevelEnum.DEPARTMENT.value,
    "部门知识库": KnowledgeSpaceLevelEnum.DEPARTMENT.value,
    "team": KnowledgeSpaceLevelEnum.TEAM.value,
    "团队库": KnowledgeSpaceLevelEnum.TEAM.value,
    "team_ks": KnowledgeSpaceLevelEnum.TEAM_KS.value,
    "科室库": KnowledgeSpaceLevelEnum.TEAM_KS.value,
    "personal": KnowledgeSpaceLevelEnum.PERSONAL.value,
    "个人库": KnowledgeSpaceLevelEnum.PERSONAL.value,
}

SPACE_LEVEL_TITLES: dict[str, str] = {
    KnowledgeSpaceLevelEnum.PUBLIC.value: "公共知识库",
    KnowledgeSpaceLevelEnum.DEPARTMENT.value: "部门知识库",
    KnowledgeSpaceLevelEnum.TEAM.value: "团队知识库",
    KnowledgeSpaceLevelEnum.TEAM_KS.value: "科室知识库",
}


@dataclass
class BackfillSummary:
    """批量加分统计结果。"""

    target_level: str
    score_per_file: int
    space_ids: list[int] = field(default_factory=list)
    total_files_scanned: int = 0
    eligible_main_files: int = 0
    excluded_dirs: int = 0
    excluded_deleted: int = 0
    excluded_shares: int = 0
    excluded_history_versions: int = 0
    ignored_user_files: int = 0
    excluded_system_admin_files: int = 0
    excluded_dept_admin_files: int = 0
    excluded_custom_ignore_files: int = 0
    awarded_files: int = 0
    replayed_files: int = 0
    total_points_awarded: int = 0
    users_affected: dict[int, dict[str, Any]] = field(default_factory=dict)


def resolve_space_level(level_raw: str) -> str:
    """解析空间级别参数，支持中英文名称。"""
    cleaned = (level_raw or "").strip().lower()
    if cleaned in SPACE_LEVEL_ALIASES:
        return SPACE_LEVEL_ALIASES[cleaned]
    raw_clean = (level_raw or "").strip()
    if raw_clean in SPACE_LEVEL_ALIASES:
        return SPACE_LEVEL_ALIASES[raw_clean]
    valid_options = ", ".join(list(SPACE_LEVEL_ALIASES.keys())[:8])
    raise ValueError(f"不支持的目标库类型: '{level_raw}'. 可用选项包括: {valid_options}")


async def fetch_target_space_ids(session, tenant_id: int, space_level: str) -> list[int]:
    """查询指定级别与租户的所有知识空间 ID。"""
    stmt = select(KnowledgeSpaceScope.space_id).where(
        KnowledgeSpaceScope.tenant_id == tenant_id,
        KnowledgeSpaceScope.level == space_level,
    )
    result = await session.exec(stmt)
    return [int(sid) for sid in result.all() if sid is not None]


async def fetch_system_admin_user_ids(session) -> set[int]:
    """查询系统超级管理员 user_ids (基于 UserRole.role_id == AdminRole)。"""
    stmt = select(UserRole.user_id).where(UserRole.role_id == AdminRole)
    result = await session.exec(stmt)
    admin_ids: set[int] = set()
    for row in result.all():
        uid = row[0] if isinstance(row, (tuple, list)) else row
        if uid is not None:
            admin_ids.add(int(uid))
    return admin_ids


async def fetch_dept_admin_user_ids(session) -> set[int]:
    """查询所有部门管理员 user_ids (基于 DepartmentAdminGrant 表)。"""
    stmt = select(DepartmentAdminGrant.user_id).distinct()
    result = await session.exec(stmt)
    dept_admin_ids: set[int] = set()
    for row in result.all():
        uid = row[0] if isinstance(row, (tuple, list)) else row
        if uid is not None:
            dept_admin_ids.add(int(uid))
    return dept_admin_ids


async def fetch_custom_ignore_user_ids(
    session,
    ignore_accounts: list[str],
) -> set[int]:
    """查询自定义指定需忽略的账号 ID。"""
    cleaned_accounts = [acc.strip() for acc in ignore_accounts if acc.strip()]
    ignore_ids: set[int] = set()

    if cleaned_accounts:
        stmt = select(User.user_id).where(
            User.user_name.in_(cleaned_accounts),
            User.delete == 0,
        )
        result = await session.exec(stmt)
        for row in result.all():
            uid = row[0] if isinstance(row, (tuple, list)) else row
            if uid is not None:
                ignore_ids.add(int(uid))

    return ignore_ids


async def fetch_eligible_main_files(
    session,
    tenant_id: int,
    space_ids: list[int],
    summary: BackfillSummary,
) -> list[KnowledgeFile]:
    """精确检索并筛选符合条件的主文件。

    过滤规则：
    1. file_type == 1 (排除文件夹目录 FileType.DIR=0)
    2. deleted_at is None (排除回收站已删除文件)
    3. entry_type != 'share' (排除跨库分享引用)
    4. 若有 reference_document_id，排除非当前主版本的历史物理文件。
    """
    if not space_ids:
        return []

    # 1. 扫描属于目标库的所有未删除物理与入口文件
    stmt = select(KnowledgeFile).where(
        KnowledgeFile.tenant_id == tenant_id,
        KnowledgeFile.knowledge_id.in_(space_ids),
        col(KnowledgeFile.deleted_at).is_(None),
    )
    result = await session.exec(stmt)
    all_files: list[KnowledgeFile] = result.all()
    summary.total_files_scanned = len(all_files)

    # 收集有 reference_document_id 的文档 ID
    doc_ids = {
        int(f.reference_document_id)
        for f in all_files
        if getattr(f, "reference_document_id", None) is not None
    }

    # 查询这些文档的主版本信息及主版本指向的物理文件 ID
    primary_file_ids_by_doc: dict[int, int] = {}
    if doc_ids:
        doc_stmt = (
            select(
                KnowledgeDocument.id,
                KnowledgeDocument.primary_version_id,
                KnowledgeDocumentVersion.knowledge_file_id,
                KnowledgeDocument.lifecycle_status,
            )
            .outerjoin(
                KnowledgeDocumentVersion,
                KnowledgeDocumentVersion.id == KnowledgeDocument.primary_version_id,
            )
            .where(
                KnowledgeDocument.tenant_id == tenant_id,
                KnowledgeDocument.id.in_(list(doc_ids)),
            )
        )
        doc_res = await session.exec(doc_stmt)
        for doc_id, prim_ver_id, phys_file_id, lifecycle_status in doc_res.all():
            if lifecycle_status == KnowledgeDocumentLifecycleStatus.ACTIVE.value and phys_file_id:
                primary_file_ids_by_doc[int(doc_id)] = int(phys_file_id)

    eligible: list[KnowledgeFile] = []
    for f in all_files:
        # 排除目录
        if f.file_type != FileType.FILE.value:
            summary.excluded_dirs += 1
            continue

        # 排除 share 引用
        entry_type_str = str(getattr(f, "entry_type", "") or "").lower()
        if entry_type_str == KnowledgeFileEntryType.SHARE.value:
            summary.excluded_shares += 1
            continue

        # 检查多版本主版本一致性
        ref_doc_id = getattr(f, "reference_document_id", None)
        if ref_doc_id is not None:
            doc_id_int = int(ref_doc_id)
            if doc_id_int in primary_file_ids_by_doc:
                active_primary_file_id = primary_file_ids_by_doc[doc_id_int]
                # 排除历史非主版本物理文件
                if f.id != active_primary_file_id and entry_type_str not in (
                    KnowledgeFileEntryType.MANAGER.value,
                    KnowledgeFileEntryType.PUBLISH.value,
                ):
                    summary.excluded_history_versions += 1
                    continue

        eligible.append(f)

    summary.eligible_main_files = len(eligible)
    return eligible


async def load_user_names(session, user_ids: set[int]) -> dict[int, str]:
    """批量加载用户名映射表。"""
    if not user_ids:
        return {}
    stmt = select(User.user_id, User.user_name).where(User.user_id.in_(list(user_ids)))
    res = await session.exec(stmt)
    return {int(uid): str(uname or "") for uid, uname in res.all()}


def group_files_by_payee(
    files: list[KnowledgeFile],
    system_admin_user_ids: set[int],
    dept_admin_user_ids: set[int],
    custom_ignore_user_ids: set[int],
    summary: BackfillSummary,
) -> dict[int, list[KnowledgeFile]]:
    """按受让人分组文件，并按系统超管/部门管理员/自定义忽略名单依次过滤。

    受让人规则：优先 original_uploader_id，为空时使用 user_id。
    """
    payee_files: dict[int, list[KnowledgeFile]] = {}

    for f in files:
        # 受让人判定
        raw_original = getattr(f, "original_uploader_id", None)
        raw_uploader = getattr(f, "user_id", None)

        payee_id = int(raw_original) if raw_original else (int(raw_uploader) if raw_uploader else None)
        if payee_id is None:
            logger.warning("文件 id=%s (%s) 缺少原始上传人和上传人，跳过", f.id, f.file_name)
            continue

        # 1. 系统管理员过滤
        if payee_id in system_admin_user_ids:
            summary.excluded_system_admin_files += 1
            summary.ignored_user_files += 1
            continue

        # 2. 部门管理员过滤
        if payee_id in dept_admin_user_ids:
            summary.excluded_dept_admin_files += 1
            summary.ignored_user_files += 1
            continue

        # 3. 自定义忽略名单过滤
        if payee_id in custom_ignore_user_ids:
            summary.excluded_custom_ignore_files += 1
            summary.ignored_user_files += 1
            continue

        payee_files.setdefault(payee_id, []).append(f)

    return payee_files


async def execute_backfill(
    session,
    *,
    tenant_id: int,
    space_level: str,
    payee_files: dict[int, list[KnowledgeFile]],
    score_per_file: int,
    dry_run: bool = False,
    batch_size: int = 100,
    summary: BackfillSummary,
) -> None:
    """执行批量加分。若 dry_run=True 则仅统计。"""
    rule_code = earn_rule_for_space_level(space_level) or "G1"
    space_title = SPACE_LEVEL_TITLES.get(space_level, "知识库")
    log_title = f"{space_title}文件补发积分"

    repo = PointsRepository(session)
    ledger = PointsLedgerService(repo)

    all_user_ids = set(payee_files.keys())
    user_names = await load_user_names(session, all_user_ids)

    # 预填统计明细
    for uid, ufiles in payee_files.items():
        summary.users_affected[uid] = {
            "user_id": uid,
            "user_name": user_names.get(uid, f"User_{uid}"),
            "file_count": len(ufiles),
            "expected_points": len(ufiles) * score_per_file,
            "actual_awarded_points": 0,
            "replayed_files": 0,
        }

    if dry_run:
        logger.info("[Dry-run] 演练模式：跳过数据库写入。")
        return

    # 正式入账
    processed_count = 0
    for uid, ufiles in payee_files.items():
        user_info = summary.users_affected[uid]
        for f in ufiles:
            # 采用按文件维度唯一的幂等键
            idempotency_key = f"backfill:{space_level}:{f.id}"
            remark = f"目标库文件补偿发分 [{space_title}, file_id={f.id}]"

            result = await ledger.award(
                tenant_id=tenant_id,
                user_id=uid,
                delta=score_per_file,
                title=log_title,
                rule_code=rule_code,
                idempotency_key=idempotency_key,
                daily_cap=None,  # 显式绕过每日上限
                source="batch_backfill",
                biz_type="space_file",
                biz_id=str(f.id),
                remark=remark,
            )

            if result.replayed:
                summary.replayed_files += 1
                user_info["replayed_files"] += 1
            elif result.applied_delta > 0:
                summary.awarded_files += 1
                summary.total_points_awarded += result.applied_delta
                user_info["actual_awarded_points"] += result.applied_delta

            processed_count += 1
            if processed_count % batch_size == 0:
                await session.commit()
                logger.info("已处理 %d 个文件...", processed_count)

    await session.commit()
    logger.info("所有待加分文件已处理完毕并提交事务。")


def print_report(summary: BackfillSummary, dry_run: bool) -> None:
    """打印格式化执行结果报告。"""
    mode_str = "【演练预览 (DRY-RUN)】" if dry_run else "【正式执行 (APPLIED)】"
    print("\n" + "=" * 60)
    print(f"       目标库文件批量增加积分报告 {mode_str}")
    print("=" * 60)
    print(f"目标库类型:            {summary.target_level}")
    print(f"每个文件分值:          {summary.score_per_file} 分")
    print(f"匹配的目标库空间数:    {len(summary.space_ids)}")
    print(f"库中扫描文件总数:      {summary.total_files_scanned}")
    print(f" - 排除文件夹目录:     {summary.excluded_dirs}")
    print(f" - 排除跨库分享引用:   {summary.excluded_shares}")
    print(f" - 排除历史非主版本:   {summary.excluded_history_versions}")
    print(f"有效主文件数:          {summary.eligible_main_files}")
    print(f" - 命中忽略与过滤跳过: {summary.ignored_user_files}")
    print(f"    * 系统管理员文件:  {summary.excluded_system_admin_files}")
    print(f"    * 部门管理员文件:  {summary.excluded_dept_admin_files}")
    print(f"    * 自定义忽略文件:  {summary.excluded_custom_ignore_files}")
    print("-" * 60)
    if dry_run:
        total_pred = sum(u["expected_points"] for u in summary.users_affected.values())
        print(f"预计获得积分用户数:    {len(summary.users_affected)}")
        print(f"预计发放总积分:        {total_pred} 分")
    else:
        print(f"实际发分文件数:        {summary.awarded_files}")
        print(f"幂等跳过文件数:        {summary.replayed_files}")
        print(f"实际发放总积分:        {summary.total_points_awarded} 分")
        print(f"受影响用户总数:        {len(summary.users_affected)}")
    print("-" * 60)
    print("用户明细清单:")
    print(f"{'用户ID':<10} {'账号/用户名':<20} {'文件数':<8} {'预计分值':<10} {'实际增加':<10} {'已跳过(幂等)':<10}")
    for uid, u in sorted(summary.users_affected.items(), key=lambda x: x[1]["file_count"], reverse=True):
        print(
            f"{u['user_id']:<10} "
            f"{u['user_name']:<20} "
            f"{u['file_count']:<8} "
            f"{u['expected_points']:<10} "
            f"{u['actual_awarded_points']:<10} "
            f"{u['replayed_files']:<10}"
        )
    print("=" * 60 + "\n")


async def run(args: argparse.Namespace) -> int:
    """脚本运行入口。"""
    try:
        target_level = resolve_space_level(args.space_level)
    except ValueError as e:
        logger.error(str(e))
        return 1

    if args.score_per_file <= 0:
        logger.error("每个文件分值必须为大于 0 的正整数，当前为: %s", args.score_per_file)
        return 1

    custom_ignore_accounts = [acc.strip() for acc in (args.ignore_accounts or "").split(",") if acc.strip()]
    logger.info("开始执行目标库文件补发积分...")
    logger.info("参数配置: 目标级别=%s, 单文件积分=%d, 自定义忽略账号=%s, DryRun=%s, 租户ID=%d",
                target_level, args.score_per_file, custom_ignore_accounts, args.dry_run, args.tenant_id)

    summary = BackfillSummary(
        target_level=target_level,
        score_per_file=args.score_per_file,
    )

    async with get_async_db_session() as session:
        # 1. 查找目标库 space_ids
        space_ids = await fetch_target_space_ids(session, args.tenant_id, target_level)
        summary.space_ids = space_ids
        if not space_ids:
            logger.warning("未找到类型为 '%s' (租户ID=%d) 的知识空间，操作终止。", target_level, args.tenant_id)
            print_report(summary, args.dry_run)
            return 0

        logger.info("找到 %d 个目标知识库空间: %s", len(space_ids), space_ids[:10])

        # 2. 默认查询系统管理员与部门管理员
        system_admin_ids = await fetch_system_admin_user_ids(session)
        dept_admin_ids = await fetch_dept_admin_user_ids(session)
        logger.info("默认识别管理员: 系统超管数=%d, 部门管理员数=%d", len(system_admin_ids), len(dept_admin_ids))

        # 3. 查自定义忽略账号的 user_ids
        custom_ignore_ids = await fetch_custom_ignore_user_ids(session, custom_ignore_accounts)
        if custom_ignore_ids:
            logger.info("识别到自定义忽略账号 ID 列表: %s", list(custom_ignore_ids))

        # 4. 查有效主文件
        eligible_files = await fetch_eligible_main_files(session, args.tenant_id, space_ids, summary)
        logger.info("扫描完成: 总文件数=%d, 排除目录=%d, 排除分享=%d, 排除历史版本=%d, 有效主文件数=%d",
                    summary.total_files_scanned, summary.excluded_dirs, summary.excluded_shares,
                    summary.excluded_history_versions, summary.eligible_main_files)

        # 5. 确定受让人并按用户分组（过滤管理员及忽略账号）
        payee_files = group_files_by_payee(
            eligible_files,
            system_admin_user_ids=system_admin_ids,
            dept_admin_user_ids=dept_admin_ids,
            custom_ignore_user_ids=custom_ignore_ids,
            summary=summary,
        )
        logger.info(
            "受让人分组完成: 待发分用户数=%d (跳过超管文件=%d, 跳过部门管理员文件=%d, 跳过自定义忽略文件=%d)",
            len(payee_files),
            summary.excluded_system_admin_files,
            summary.excluded_dept_admin_files,
            summary.excluded_custom_ignore_files,
        )

        # 6. 执行发分或 dry-run
        await execute_backfill(
            session,
            tenant_id=args.tenant_id,
            space_level=target_level,
            payee_files=payee_files,
            score_per_file=args.score_per_file,
            dry_run=args.dry_run,
            batch_size=args.batch_size,
            summary=summary,
        )

    # 7. 打印输出最终报告
    print_report(summary, args.dry_run)

    # 8. 优雅释放数据库连接池
    try:
        from bisheng.core.database.manager import get_database_connection
        db_mgr = await get_database_connection()
        if hasattr(db_mgr, "async_engine") and db_mgr.async_engine:
            await db_mgr.async_engine.dispose()
    except Exception:
        pass

    return 0


def main():
    parser = argparse.ArgumentParser(
        description="根据目标类型库下所有有效主文件给原始上传人批量增加指定积分 (默认过滤系统管理员与部门管理员)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "-l",
        "--space-level",
        "--target-type",
        required=True,
        help="目标库类型 (如 public, department, team, team_ks 或中文名称: 公共知识库/部门库等)",
    )
    parser.add_argument(
        "-s",
        "--score-per-file",
        type=int,
        required=True,
        help="每个文件增加的分数 (正整数)",
    )
    parser.add_argument(
        "-i",
        "--ignore-accounts",
        default="admin",
        help="自定义忽略上传人账号，逗号分隔 (默认: admin)",
    )
    parser.add_argument(
        "--tenant-id",
        type=int,
        default=1,
        help="租户 ID",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="演练预览模式，只读统计分析，不写入任何数据库变更",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="批量记账提交大小",
    )

    args = parser.parse_args()
    exit_code = asyncio.run(run(args))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
