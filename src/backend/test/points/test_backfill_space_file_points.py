"""目标库文件原始上传人批量增加积分脚本单元测试（含管理员默认过滤）。"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

# 将 bisheng/scripts 目录加入 sys.path
_SCRIPTS_DIR = Path(__file__).resolve().parents[4] / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import backfill_space_file_points as bsp
from scripts import backfill_space_file_points as backend_bsp
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


def test_space_roles_only_exclude_files_in_managed_space():
    """同一用户在别的库是普通上传人时仍发分，按原始上传人判定角色。"""
    files = [
        KnowledgeFile(id=1, knowledge_id=1, file_name="owned", original_uploader_id=10, user_id=99),
        KnowledgeFile(id=2, knowledge_id=2, file_name="ordinary", original_uploader_id=10, user_id=99),
        KnowledgeFile(id=3, knowledge_id=1, file_name="managed", user_id=20),
        KnowledgeFile(id=4, knowledge_id=2, file_name="ordinary-admin", user_id=20),
        KnowledgeFile(id=5, knowledge_id=1, file_name="ordinary", original_uploader_id=30, user_id=10),
    ]
    summary = BackfillSummary(target_level="public", score_per_file=3)
    grouped = group_files_by_payee(
        files,
        system_admin_user_ids={99},
        space_owner_user_ids={1: {10}},
        space_admin_user_ids={1: {20}},
        custom_ignore_user_ids=set(),
        summary=summary,
    )
    assert {uid: [f.id for f in rows] for uid, rows in grouped.items()} == {10: [2], 20: [4], 30: [5]}
    assert summary.excluded_space_owner_files == 1
    assert summary.excluded_space_admin_files == 1
    assert summary.ignored_user_files == 2


@pytest.mark.asyncio
async def test_fetch_space_roles_with_real_sql():
    """真实 SQL 验证角色、成员状态、业务类型及租户边界，防止模拟结果掩盖过滤遗漏。"""
    from sqlalchemy import create_engine, text
    from sqlmodel import Session

    from bisheng.core.context.tenant import bypass_tenant_filter

    engine = create_engine("sqlite://")
    try:
        with bypass_tenant_filter(), Session(engine) as session:
            session.execute(text("CREATE TABLE knowledge (id INTEGER PRIMARY KEY, user_id INTEGER, tenant_id INTEGER)"))
            session.execute(text(
                "CREATE TABLE space_channel_member (business_id TEXT, business_type TEXT, "
                "user_id INTEGER, user_role TEXT, status TEXT)"
            ))
            session.execute(text("INSERT INTO knowledge VALUES (1, 10, 1), (2, 20, 1), (3, 30, 2)"))
            session.execute(text(
                "INSERT INTO space_channel_member VALUES "
                "('1', 'SPACE', 11, 'CREATOR', 'ACTIVE'), "
                "('1', 'SPACE', 12, 'ADMIN', 'ACTIVE'), "
                "('1', 'SPACE', 13, 'ADMIN', 'PENDING'), "
                "('1', 'SPACE', 14, 'ADMIN', 'REJECTED'), "
                "('1', 'SPACE', 15, 'MEMBER', 'ACTIVE'), "
                "('1', 'CHANNEL', 16, 'ADMIN', 'ACTIVE'), "
                "('2', 'SPACE', 22, 'ADMIN', 'ACTIVE'), "
                "('3', 'SPACE', 32, 'ADMIN', 'ACTIVE')"
            ))

            async def execute(statement):
                return session.exec(statement)

            owners, admins = await bsp.fetch_space_privileged_user_ids(
                SimpleNamespace(exec=execute), 1, [1, 2, 3]
            )
            assert owners == {1: {10, 11}, 2: {20}}
            assert admins == {1: {12}, 2: {22}}
    finally:
        engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("uploaded_at", "expected"),
    [
        (datetime(2025, 12, 31), datetime(2026, 8, 1)),
        (datetime(2026, 7, 31, 23, 59, 59), datetime(2026, 8, 1)),
        (datetime(2026, 8, 1), datetime(2026, 8, 1)),
        (datetime(2026, 8, 20, 12, 30), datetime(2026, 8, 20, 12, 30)),
        (datetime(2026, 9, 1, 1, 2, 3), datetime(2026, 9, 1, 1, 2, 3)),
        (datetime(2026, 7, 31, 17, tzinfo=timezone.utc), datetime(2026, 8, 1, 1)),
        (None, datetime(2026, 9, 15, 12)),
    ],
)
async def test_ledger_august_time_boundary(uploaded_at, expected):
    """使用真实补分账本验证流水日期及最近获分时间；数据库访问用内存对象代替。"""
    account = SimpleNamespace(balance=0, version=0, lifetime_earned=0, last_earned_at=None)
    repo = SimpleNamespace(
        get_log_by_idempotency=AsyncMock(return_value=None),
        lock_or_create_account=AsyncMock(return_value=account),
        add_outbox=AsyncMock(),
    )
    logs = []

    async def append_log(log):
        log.id = 1
        logs.append(log)
        return log

    repo.append_log = append_log
    with (
        patch.object(bsp, "PointsRepository", return_value=repo),
        patch.object(bsp, "datetime", wraps=datetime) as clock,
    ):
        clock.now.return_value = datetime(2026, 9, 15, 12, tzinfo=bsp.SHANGHAI)
        await bsp.BackfillPointsLedger(AsyncMock()).award(
            tenant_id=1, user_id=10, delta=3, title="补分", rule_code="G1",
            idempotency_key="boundary", occurred_at=uploaded_at,
        )
    assert logs[0].occurred_at == expected
    assert account.last_earned_at == expected
    assert logs[0].delta == 3


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
        space_owner_user_ids={},
        space_admin_user_ids={},
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
        space_owner_user_ids={},
        space_admin_user_ids={},
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
        space_owner_user_ids={},
        space_admin_user_ids={},
        custom_ignore_user_ids=set(),
        summary=summary,
    )

    assert super_admin_id not in result
    assert normal_user_id in result
    assert summary.excluded_system_admin_files == 1
    assert summary.ignored_user_files == 1


def test_group_files_by_payee_space_admin_filtered():
    """测试知识库管理员仅在文件所在库内被排除。"""
    summary = BackfillSummary(target_level="public", score_per_file=3)
    space_admin_id = 88
    normal_user_id = 10

    f1 = KnowledgeFile(
        id=203,
        file_name="space_admin_doc.pdf",
        file_type=FileType.FILE.value,
        knowledge_id=1,
        original_uploader_id=space_admin_id,
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
        space_owner_user_ids={},
        space_admin_user_ids={1: {space_admin_id}},
        custom_ignore_user_ids=set(),
        summary=summary,
    )

    assert space_admin_id not in result
    assert normal_user_id in result
    assert summary.excluded_space_admin_files == 1
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
        space_owner_user_ids={},
        space_admin_user_ids={},
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
@pytest.mark.parametrize("module", [bsp, backend_bsp], ids=["root-script", "backend-script"])
@pytest.mark.parametrize("dry_run", [True, False], ids=["preview", "apply"])
@pytest.mark.parametrize("existing_user", [True, False], ids=["mixed-users", "all-missing"])
async def test_backfill_skips_missing_users(module, dry_run, existing_user, capsys):
    """两份脚本都按真实用户记录过滤；失效原上传人不转发给当前上传人。"""
    from sqlalchemy import column, create_engine, table, text
    from sqlmodel import Session

    from bisheng.core.context.tenant import bypass_tenant_filter

    files = [
        KnowledgeFile(id=1, knowledge_id=1, file_name="missing-original", original_uploader_id=11534,
                      user_id=10, create_time=datetime(2026, 8, 1)),
        KnowledgeFile(id=2, knowledge_id=1, file_name="missing-uploader", user_id=4155,
                      create_time=datetime(2026, 9, 1)),
        KnowledgeFile(id=3, knowledge_id=1, file_name="existing-original", original_uploader_id=10,
                      user_id=11534, create_time=datetime(2026, 8, 1)),
        KnowledgeFile(id=4, knowledge_id=1, file_name="existing-uploader", user_id=10,
                      create_time=datetime(2026, 9, 1)),
    ]
    summary = module.BackfillSummary(target_level="department", score_per_file=2)
    grouped = module.group_files_by_payee(files, set(), {}, {}, set(), summary)
    ledger = SimpleNamespace(award=AsyncMock(return_value=SimpleNamespace(replayed=False, applied_delta=2)))
    engine = create_engine("sqlite://")
    try:
        with bypass_tenant_filter(), Session(engine) as db:
            db.execute(text("CREATE TABLE user (user_id INTEGER PRIMARY KEY, user_name TEXT)"))
            if existing_user:
                # 用户名为空不等于用户不存在，只按用户记录是否存在判断。
                db.execute(text("INSERT INTO user VALUES (10, '')"))

            async def execute(statement):
                return db.exec(statement)

            session = SimpleNamespace(exec=execute, commit=AsyncMock())
            with (
                # 全局测试配置替换了 User 模型，这里恢复真实 SQL 列以验证存在性查询。
                patch.object(module, "User", table("user", column("user_id"), column("user_name")).c),
                patch.object(module, "BackfillPointsLedger", return_value=ledger),
            ):
                await module.execute_backfill(
                    session, tenant_id=1, space_level="department", payee_files=grouped,
                    score_per_file=2, dry_run=dry_run, summary=summary,
                )
            assert set(summary.users_affected) == ({10} if existing_user else set())
            assert summary.excluded_missing_user_files == (2 if existing_user else 4)
            assert summary.ignored_user_files == summary.excluded_missing_user_files
            assert sum(u["expected_points"] for u in summary.users_affected.values()) == (4 if existing_user else 0)
            if dry_run:
                assert summary.monthly_users == ({
                    month: {10: {"user_id": 10, "user_name": "", "file_count": 1, "expected_points": 2}}
                    for month in ("2026-08", "2026-09")
                } if existing_user else {})
            calls = ledger.award.await_args_list
            assert [(c.kwargs["user_id"], c.kwargs["biz_id"]) for c in calls] == (
                [(10, "3"), (10, "4")] if existing_user and not dry_run else []
            )
            assert summary.total_points_awarded == (4 if existing_user and not dry_run else 0)
            if dry_run or not existing_user:
                session.commit.assert_not_awaited()
            module.print_report(summary, dry_run=dry_run)
            report = capsys.readouterr().out
            assert "不存在用户文件:" in report
            assert "User_11534" not in report and "User_4155" not in report
    finally:
        engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("empty", [False, True])
async def test_dry_run_groups_users_by_accounting_month(empty, capsys):
    """按记账年月分组，跨月用户分别统计，总人数去重，且预览不写账。"""
    files = {
        10: [
            SimpleNamespace(create_time=datetime(2027, 8, 2)),
            SimpleNamespace(create_time=datetime(2026, 7, 1)),
            SimpleNamespace(create_time=datetime(2026, 8, 20)),
            SimpleNamespace(create_time=datetime(2026, 8, 31, 17, tzinfo=timezone.utc)),
        ],
        20: [SimpleNamespace(create_time=None)],
    }
    summary = BackfillSummary(target_level="public", score_per_file=2)
    session = AsyncMock()
    with (
        patch.object(bsp, "load_user_names", AsyncMock(return_value={10: "张三", 20: "李四"})),
        patch.object(bsp, "BackfillPointsLedger") as ledger,
        patch.object(bsp, "datetime", wraps=datetime) as clock,
    ):
        clock.now.return_value = datetime(2026, 9, 15, tzinfo=bsp.SHANGHAI)
        await execute_backfill(
            session, tenant_id=1, space_level="public", payee_files={} if empty else files,
            score_per_file=2, dry_run=True, summary=summary,
        )
        bsp.print_report(summary, dry_run=True)
    output = capsys.readouterr().out
    ledger.return_value.award.assert_not_called()
    session.commit.assert_not_called()
    session.add.assert_not_called()
    session.flush.assert_not_called()
    if empty:
        assert summary.monthly_users == {}
        assert "无待发分文件" in output
        return
    assert {
        month: {uid: (user["file_count"], user["expected_points"]) for uid, user in users.items()}
        for month, users in summary.monthly_users.items()
    } == {"2026-08": {10: (2, 4)}, "2026-09": {10: (1, 2), 20: (1, 2)}, "2027-08": {10: (1, 2)}}
    assert len(summary.users_affected) == 2
    assert sum(u["expected_points"] for u in summary.users_affected.values()) == 10
    assert output.index("月份: 2026-08") < output.index("月份: 2026-09") < output.index("月份: 2027-08")
    assert "月份: 2026-07" not in output
    assert output.count("张三") == 3
    assert output.count("李四") == 1
    assert "2026-08\n待发分文件数: 2 | 预计获得积分用户数: 1 | 预计发放总积分: 4 分" in output


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
                last_earned_at=datetime(2026, 8, 15),
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

        # 1. 旧上传时间归到八月一日，不回退已有的最近获分时间
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
        # 最近获分时间不回退
        assert fake_repo.account.last_earned_at == datetime(2026, 8, 15)
        assert fake_repo.logs["k1"].occurred_at == datetime(2026, 8, 1)

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

        # 3. 八月之后的上传时间原样保留，并推进最近获分时间
        new_time = datetime(2026, 9, 1, 9, 0, 0)
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
        # 推进到九月
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
