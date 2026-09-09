"""目标库文件原始上传人批量增加积分脚本单元测试（含管理员默认过滤）。"""

from __future__ import annotations

import sys
from pathlib import Path

# 将 bisheng/scripts 目录加入 sys.path
_SCRIPTS_DIR = Path(__file__).resolve().parents[4] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import backfill_space_file_points as bsp
from backfill_space_file_points import (
    BackfillSummary,
    execute_backfill,
    group_files_by_payee,
    resolve_space_level,
)
from bisheng.knowledge.domain.models.knowledge_file import (
    FileType,
    KnowledgeFile,
    KnowledgeFileEntryType,
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
    result = group_files_by_payee(
        [f1],
        system_admin_user_ids=set(),
        dept_admin_user_ids=set(),
        custom_ignore_user_ids=set(),
        summary=summary,
    )
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
    result = group_files_by_payee(
        [f2],
        system_admin_user_ids=set(),
        dept_admin_user_ids=set(),
        custom_ignore_user_ids=set(),
        summary=summary,
    )
    assert 20 in result
    assert result[20][0].id == 102


def test_group_files_by_payee_system_admin_filtered():
    """测试系统超级管理员默认过滤：命中系统超管的用户文件被跳过。"""
    summary = BackfillSummary(target_level="public", score_per_file=3)
    super_admin_id = 99
    normal_user_id = 10

    f1 = KnowledgeFile(
        id=201,
        file_name="super_doc.pdf",
        file_type=FileType.FILE.value,
        knowledge_id=1,
        original_uploader_id=super_admin_id,
        user_id=normal_user_id,
    )
    f2 = KnowledgeFile(
        id=202,
        file_name="normal_doc.pdf",
        file_type=FileType.FILE.value,
        knowledge_id=1,
        original_uploader_id=normal_user_id,
        user_id=normal_user_id,
    )

    result = group_files_by_payee(
        [f1, f2],
        system_admin_user_ids={super_admin_id},
        dept_admin_user_ids=set(),
        custom_ignore_user_ids=set(),
        summary=summary,
    )

    assert super_admin_id not in result
    assert normal_user_id in result
    assert summary.excluded_system_admin_files == 1
    assert summary.ignored_user_files == 1


def test_group_files_by_payee_dept_admin_filtered():
    """测试部门管理员默认过滤：命中部门管理员的用户文件被跳过。"""
    summary = BackfillSummary(target_level="public", score_per_file=3)
    dept_admin_id = 88
    normal_user_id = 10

    f1 = KnowledgeFile(
        id=203,
        file_name="dept_admin_doc.pdf",
        file_type=FileType.FILE.value,
        knowledge_id=1,
        original_uploader_id=dept_admin_id,
        user_id=normal_user_id,
    )
    f2 = KnowledgeFile(
        id=204,
        file_name="normal_doc.pdf",
        file_type=FileType.FILE.value,
        knowledge_id=1,
        original_uploader_id=normal_user_id,
        user_id=normal_user_id,
    )

    result = group_files_by_payee(
        [f1, f2],
        system_admin_user_ids=set(),
        dept_admin_user_ids={dept_admin_id},
        custom_ignore_user_ids=set(),
        summary=summary,
    )

    assert dept_admin_id not in result
    assert normal_user_id in result
    assert summary.excluded_dept_admin_files == 1
    assert summary.ignored_user_files == 1


def test_group_files_by_payee_custom_ignore_accounts():
    """测试自定义忽略账号过滤：受让人在自定义 ignore 列表中则跳过。"""
    summary = BackfillSummary(target_level="public", score_per_file=3)
    custom_ignore_id = 77
    normal_id = 10

    f1 = KnowledgeFile(
        id=205,
        file_name="custom_ignored.pdf",
        file_type=FileType.FILE.value,
        knowledge_id=1,
        original_uploader_id=custom_ignore_id,
        user_id=normal_id,
    )

    result = group_files_by_payee(
        [f1],
        system_admin_user_ids=set(),
        dept_admin_user_ids=set(),
        custom_ignore_user_ids={custom_ignore_id},
        summary=summary,
    )

    assert custom_ignore_id not in result
    assert summary.excluded_custom_ignore_files == 1
    assert summary.ignored_user_files == 1


@pytest.mark.asyncio
async def test_execute_backfill_accumulation_and_idempotency():
    """测试积分全额累加（如 10 个文件 +30 分，突破 15 分上限）与强幂等性。"""
    summary = BackfillSummary(target_level="public", score_per_file=3)
    from datetime import datetime, timedelta
    uid = 100
    upload_base_time = datetime(2026, 5, 1, 10, 0, 0)
    files = [
        KnowledgeFile(
            id=300 + i,
            file_name=f"file_{i}.pdf",
            file_type=FileType.FILE.value,
            knowledge_id=1,
            user_id=uid,
            create_time=upload_base_time + timedelta(days=i),
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
            self.awarded_occurred_ats = []

        async def award(self, *, tenant_id, user_id, delta, title, rule_code, idempotency_key, **kwargs):
            # 验证业务发生时间精确继承文件上传时间
            occurred_at = kwargs.get("occurred_at")
            assert occurred_at is not None
            self.awarded_occurred_ats.append(occurred_at)

            if idempotency_key in self.logs:
                return SimpleNamespace(replayed=True, applied_delta=0)
            self.balance += delta
            self.lifetime_earned += delta
            self.logs[idempotency_key] = delta
            return SimpleNamespace(replayed=False, applied_delta=delta)

    fake_ledger = FakePointsLedger()
    mock_session = AsyncMock()

    with patch.object(bsp, "load_user_names", AsyncMock(return_value={uid: "test_user"})), \
         patch.object(bsp, "BackfillPointsLedger", return_value=fake_ledger):

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
        assert len(fake_ledger.awarded_occurred_ats) == 10
        for idx, ot in enumerate(fake_ledger.awarded_occurred_ats):
            assert ot == upload_base_time + timedelta(days=idx)

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
    with patch.object(bsp, "load_user_names", AsyncMock(return_value={uid: "dry_user"})), \
         patch.object(bsp, "BackfillPointsLedger") as mock_ledger_cls:

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
async def test_backfill_points_ledger_custom_occurred_at_and_last_earned_at():
    """测试 BackfillPointsLedger 自身：业务发生时间继承、幂等性与 last_earned_at 保护。"""
    from datetime import datetime
    class FakeRepo:
        def __init__(self):
            self.account = SimpleNamespace(
                balance=10,
                version=1,
                lifetime_earned=10,
                lifetime_deducted=0,
                last_earned_at=datetime(2026, 4, 1),
            )
            self.logs = {}
            self.outboxes = []

        async def get_log_by_idempotency(self, tenant_id, key):
            return self.logs.get(key)

        async def lock_or_create_account(self, tenant_id, user_id):
            return self.account

        async def append_log(self, log):
            log.id = 1001
            self.logs[log.idempotency_key] = log
            return log

        async def add_outbox(self, tenant_id, log_id, payload):
            self.outboxes.append((tenant_id, log_id, payload))

    mock_session = AsyncMock()
    fake_repo = FakeRepo()
    with patch.object(bsp, "PointsRepository", return_value=fake_repo):
        ledger = bsp.BackfillPointsLedger(mock_session)

        # 1. 历史更早时间补发（2026-03-01 < 2026-04-01）
        hist_time = datetime(2026, 3, 1, 9, 0, 0)
        res1 = await ledger.award(
            tenant_id=1,
            user_id=1,
            delta=3,
            title="测试补发",
            rule_code="G1",
            idempotency_key="k1",
            occurred_at=hist_time,
        )
        assert not res1.replayed
        assert fake_repo.account.balance == 13
        assert fake_repo.account.lifetime_earned == 13
        # 因为 3月 早于 4月，last_earned_at 应受保护不回退
        assert fake_repo.account.last_earned_at == datetime(2026, 4, 1)
        assert fake_repo.logs["k1"].occurred_at == hist_time

        # 2. 幂等性测试
        res_replay = await ledger.award(
            tenant_id=1,
            user_id=1,
            delta=3,
            title="测试补发",
            rule_code="G1",
            idempotency_key="k1",
            occurred_at=hist_time,
        )
        assert res_replay.replayed
        assert fake_repo.account.balance == 13

        # 3. 更新时间补发（2026-05-01 > 2026-04-01）
        new_time = datetime(2026, 5, 1, 9, 0, 0)
        res2 = await ledger.award(
            tenant_id=1,
            user_id=1,
            delta=3,
            title="测试补发2",
            rule_code="G1",
            idempotency_key="k2",
            occurred_at=new_time,
        )
        assert not res2.replayed
        assert fake_repo.account.balance == 16
        # 推进到 5月
        assert fake_repo.account.last_earned_at == new_time
        assert fake_repo.logs["k2"].occurred_at == new_time
        assert len(fake_repo.outboxes) == 2


@pytest.mark.asyncio
async def test_fetch_eligible_main_files_filters():
    """测试主文件过滤：排除目录、回收站、share 引用和历史非主版本。"""
    summary = BackfillSummary(target_level="public", score_per_file=3)
    space_ids = [1]

    f_valid = KnowledgeFile(
        id=501,
        file_name="valid.pdf",
        file_type=FileType.FILE.value,
        knowledge_id=1,
        user_id=10,
        entry_type=KnowledgeFileEntryType.MANAGER.value,
    )
    f_dir = KnowledgeFile(
        id=502,
        file_name="my_folder",
        file_type=FileType.DIR.value,
        knowledge_id=1,
        user_id=10,
    )
    f_share = KnowledgeFile(
        id=503,
        file_name="shared.pdf",
        file_type=FileType.FILE.value,
        knowledge_id=1,
        user_id=10,
        entry_type=KnowledgeFileEntryType.SHARE.value,
    )
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
    mock_session = AsyncMock()

    class MockExecResult:
        def __init__(self, data):
            self._data = data
        def all(self):
            return self._data

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
