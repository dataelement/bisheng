# ruff: noqa: RUF002, RUF003
"""目标库文件原始上传人批量增加积分脚本单元测试。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from bisheng.knowledge.domain.models.knowledge_file import (
    FileType,
    KnowledgeFile,
    KnowledgeFileEntryType,
)
from scripts import backfill_space_file_points as bsp
from scripts.backfill_space_file_points import (
    BackfillSummary,
    execute_backfill,
    group_files_by_payee,
    resolve_space_level,
)


def test_resolve_space_level():
    """测试中英文目标库类型解析。"""
    assert resolve_space_level("public") == "public"
    assert resolve_space_level("PUBLIC") == "public"
    assert resolve_space_level("公共知识库") == "public"
    assert resolve_space_level("公共库") == "public"
    assert resolve_space_level("department") == "department"
    assert resolve_space_level("部门库") == "department"
    assert resolve_space_level("team") == "team"
    assert resolve_space_level("团队库") == "team"
    assert resolve_space_level("team_ks") == "team_ks"
    assert resolve_space_level("科室库") == "team_ks"

    with pytest.raises(ValueError, match="不支持的目标库类型"):
        resolve_space_level("unknown_type_xxx")


def test_group_files_by_payee_original_uploader_priority():
    """测试受让人判定：original_uploader_id 优先。"""
    summary = BackfillSummary(target_level="public", score_per_file=3)
    f1 = KnowledgeFile(
        id=101,
        file_name="doc1.pdf",
        file_type=FileType.FILE.value,
        knowledge_id=1,
        original_uploader_id=10,
        user_id=20,
    )
    result = group_files_by_payee([f1], ignore_user_ids=set(), summary=summary)
    assert 10 in result
    assert result[10][0].id == 101


def test_group_files_by_payee_fallback_to_uploader():
    """测试受让人判定：original_uploader_id 为空时回退到 user_id。"""
    summary = BackfillSummary(target_level="public", score_per_file=3)
    f2 = KnowledgeFile(
        id=102,
        file_name="doc2.pdf",
        file_type=FileType.FILE.value,
        knowledge_id=1,
        original_uploader_id=None,
        user_id=20,
    )
    result = group_files_by_payee([f2], ignore_user_ids=set(), summary=summary)
    assert 20 in result
    assert result[20][0].id == 102


def test_group_files_by_payee_ignore_accounts():
    """测试忽略账号过滤：受让人在 ignore 列表中则跳过。"""
    summary = BackfillSummary(target_level="public", score_per_file=3)
    admin_id = 1
    normal_id = 2

    # 文件 1 原始上传人是 admin -> 忽略
    f1 = KnowledgeFile(
        id=201,
        file_name="admin_doc.pdf",
        file_type=FileType.FILE.value,
        knowledge_id=1,
        original_uploader_id=admin_id,
        user_id=normal_id,
    )
    # 文件 2 原始上传人为空，上传人是 admin -> 忽略
    f2 = KnowledgeFile(
        id=202,
        file_name="admin_fallback.pdf",
        file_type=FileType.FILE.value,
        knowledge_id=1,
        original_uploader_id=None,
        user_id=admin_id,
    )
    # 文件 3 正常用户文件 -> 纳入
    f3 = KnowledgeFile(
        id=203,
        file_name="user_doc.pdf",
        file_type=FileType.FILE.value,
        knowledge_id=1,
        original_uploader_id=normal_id,
        user_id=admin_id,
    )

    result = group_files_by_payee(
        [f1, f2, f3],
        ignore_user_ids={admin_id},
        summary=summary,
    )

    assert admin_id not in result
    assert normal_id in result
    assert len(result[normal_id]) == 1
    assert result[normal_id][0].id == 203
    assert summary.ignored_user_files == 2


@pytest.mark.asyncio
async def test_execute_backfill_accumulation_and_idempotency():
    """测试积分全额累加（如 10 个文件 +30 分，突破 15 分上限）与强幂等性。"""
    summary = BackfillSummary(target_level="public", score_per_file=3)
    uid = 100
    files = [
        KnowledgeFile(
            id=300 + i,
            file_name=f"file_{i}.pdf",
            file_type=FileType.FILE.value,
            knowledge_id=1,
            user_id=uid,
        )
        for i in range(10)
    ]
    payee_files = {uid: files}

    # 模拟内存账本
    class FakePointsLedger:
        def __init__(self):
            self.balance = 0
            self.lifetime_earned = 0
            self.logs = {}

        async def award(self, *, tenant_id, user_id, delta, title, rule_code, idempotency_key, daily_cap, **kwargs):
            # 验证显式传了 daily_cap=None 以跳过上限截断
            assert daily_cap is None
            if idempotency_key in self.logs:
                return SimpleNamespace(replayed=True, applied_delta=0)
            self.balance += delta
            self.lifetime_earned += delta
            self.logs[idempotency_key] = delta
            return SimpleNamespace(replayed=False, applied_delta=delta)

    fake_ledger = FakePointsLedger()
    mock_session = AsyncMock()

    with (
        patch.object(bsp, "load_user_names", AsyncMock(return_value={uid: "test_user"})),
        patch.object(bsp, "PointsLedgerService", return_value=fake_ledger),
        patch.object(bsp, "PointsRepository"),
    ):
        # 第一次执行：应全额发放 10 * 3 = 30 分
        await execute_backfill(
            mock_session,
            tenant_id=1,
            space_level="public",
            payee_files=payee_files,
            score_per_file=3,
            dry_run=False,
            summary=summary,
        )

        assert summary.awarded_files == 10
        assert summary.total_points_awarded == 30
        assert summary.replayed_files == 0
        assert fake_ledger.balance == 30
        assert fake_ledger.lifetime_earned == 30

        # 第二次重复执行：幂等性保障，不增加积分
        summary_replay = BackfillSummary(target_level="public", score_per_file=3)
        await execute_backfill(
            mock_session,
            tenant_id=1,
            space_level="public",
            payee_files=payee_files,
            score_per_file=3,
            dry_run=False,
            summary=summary_replay,
        )

        assert summary_replay.awarded_files == 0
        assert summary_replay.replayed_files == 10
        assert summary_replay.total_points_awarded == 0
        # 余额仍为 30，无二次累加
        assert fake_ledger.balance == 30


@pytest.mark.asyncio
async def test_execute_backfill_dry_run():
    """测试 Dry-run 演练模式不调用数据库写操作。"""
    summary = BackfillSummary(target_level="public", score_per_file=3)
    uid = 200
    files = [
        KnowledgeFile(id=401, file_name="dry_file.pdf", file_type=FileType.FILE.value, knowledge_id=1, user_id=uid)
    ]
    payee_files = {uid: files}

    mock_session = AsyncMock()
    with (
        patch.object(bsp, "load_user_names", AsyncMock(return_value={uid: "dry_user"})),
        patch.object(bsp, "PointsLedgerService") as mock_ledger_cls,
    ):
        await execute_backfill(
            mock_session,
            tenant_id=1,
            space_level="public",
            payee_files=payee_files,
            score_per_file=3,
            dry_run=True,
            summary=summary,
        )

        # dry_run 模式下不调用 ledger.award，不 commit
        mock_ledger_cls.return_value.award.assert_not_called()
        mock_session.commit.assert_not_called()
        assert summary.users_affected[uid]["expected_points"] == 3
        assert summary.users_affected[uid]["actual_awarded_points"] == 0


@pytest.mark.asyncio
async def test_fetch_eligible_main_files_filters():
    """测试主文件过滤：排除目录、回收站、share 引用和历史非主版本。"""
    summary = BackfillSummary(target_level="public", score_per_file=3)
    space_ids = [1]

    # 1. 正常主文件
    f_valid = KnowledgeFile(
        id=501,
        file_name="valid.pdf",
        file_type=FileType.FILE.value,
        knowledge_id=1,
        user_id=10,
        entry_type=KnowledgeFileEntryType.MANAGER.value,
    )
    # 2. 文件夹目录 -> 排除
    f_dir = KnowledgeFile(
        id=502,
        file_name="my_folder",
        file_type=FileType.DIR.value,
        knowledge_id=1,
        user_id=10,
    )
    # 3. 跨库分享引用 -> 排除
    f_share = KnowledgeFile(
        id=503,
        file_name="shared.pdf",
        file_type=FileType.FILE.value,
        knowledge_id=1,
        user_id=10,
        entry_type=KnowledgeFileEntryType.SHARE.value,
    )
    # 4. 多版本中的历史非主版本 -> 排除
    f_history = KnowledgeFile(
        id=504,
        file_name="old_v1.pdf",
        file_type=FileType.FILE.value,
        knowledge_id=1,
        user_id=10,
        reference_document_id=999,
        entry_type=None,
    )

    all_mock_files = [f_valid, f_dir, f_share, f_history]

    # 模拟 session.exec 查询
    mock_session = AsyncMock()

    class MockExecResult:
        def __init__(self, data):
            self._data = data

        def all(self):
            return self._data

    # 第一次查询全量文件返回 all_mock_files
    # 第二次查询文档主版本，doc_id=999 的主物理文件 ID 为 505（非 504）
    doc_row = (999, 10, 505, "active")

    mock_session.exec.side_effect = [
        MockExecResult(all_mock_files),
        MockExecResult([doc_row]),
    ]

    eligible = await bsp.fetch_eligible_main_files(mock_session, tenant_id=1, space_ids=space_ids, summary=summary)

    assert len(eligible) == 1
    assert eligible[0].id == 501
    assert summary.excluded_dirs == 1
    assert summary.excluded_shares == 1
    assert summary.excluded_history_versions == 1
    assert summary.eligible_main_files == 1
