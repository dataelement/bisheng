"""PointsAwardFacade 单元测试：豁免、受益人、开关与异常吞没。"""

from types import SimpleNamespace

import pytest

from bisheng.points.domain.services.points_award_facade import (
    AnswerAdoptedEvent,
    DocumentSharedEvent,
    FavoriteChangedEvent,
    PointsAwardFacade,
    SpaceFileReadyEvent,
)
from bisheng.points.domain.services.points_ledger_service import PointsLedgerService


class FakeAwardRepository:
    """内存规则与 G3 档位进度，供 Facade 单测使用。"""

    def __init__(self, rules: dict[str, SimpleNamespace] | None = None):
        self.rules = rules or {}
        self.tier_awards: dict[int, SimpleNamespace] = {}
        self.account = SimpleNamespace(balance=0, version=0, lifetime_earned=0, lifetime_deducted=0)
        self.logs = {}
        self.today = 0

    async def get_rule(self, _tenant_id, rule_code):
        return self.rules.get(rule_code)

    async def get_favorite_tier_award(self, _tenant_id, file_id):
        return self.tier_awards.get(file_id)

    async def upsert_favorite_tier_award(self, _tenant_id, file_id, *, highest_tier, points_granted_total):
        row = self.tier_awards.get(file_id)
        if row is None:
            row = SimpleNamespace(highest_tier=highest_tier, points_granted_total=points_granted_total)
            self.tier_awards[file_id] = row
        else:
            row.highest_tier = max(row.highest_tier, highest_tier)
            row.points_granted_total = max(row.points_granted_total, points_granted_total)
        return row

    async def lock_or_create_account(self, *_):
        return self.account

    async def get_log_by_idempotency(self, _, key):
        return self.logs.get(key)

    async def sum_earn_today(self, *_):
        return self.today

    async def append_log(self, log):
        log.id = len(self.logs) + 1
        self.logs[log.idempotency_key] = log
        return log

    async def add_outbox(self, *_):
        pass


def _rule(code="G1", *, status="enabled", beneficiary="uploader", score=3, daily_cap=15, score_expr=None):
    return SimpleNamespace(
        rule_code=code,
        rule_type="earn",
        name=f"rule-{code}",
        status=status,
        beneficiary=beneficiary,
        daily_cap=daily_cap,
        score_expr=score_expr or {"mode": "fixed", "score": score},
    )


def _facade(repo, *, enabled=True, super_admins: set[int] | None = None) -> PointsAwardFacade:
    supers = super_admins or set()

    async def is_super(uid: int) -> bool:
        return uid in supers

    return PointsAwardFacade(
        repo,
        PointsLedgerService(repo),
        enabled=enabled,
        is_platform_super_admin=is_super,
    )


def _file_event(**kwargs) -> SpaceFileReadyEvent:
    base = dict(
        tenant_id=1,
        space_id=10,
        space_level="public",
        file_id=100,
        uploader_id=4,
        publisher_id=None,
        is_favorite_space=False,
        space_manager_ids=frozenset(),
    )
    base.update(kwargs)
    return SpaceFileReadyEvent(**base)


@pytest.mark.asyncio
async def test_skips_when_points_disabled():
    repo = FakeAwardRepository({"G1": _rule()})
    outcome = await _facade(repo, enabled=False).on_space_file_ready(_file_event())
    assert outcome.skipped and outcome.reason == "points_disabled"
    assert repo.account.balance == 0


@pytest.mark.asyncio
async def test_skips_personal_and_favorite_space():
    repo = FakeAwardRepository({"G1": _rule()})
    facade = _facade(repo)
    personal = await facade.on_space_file_ready(_file_event(space_level="personal"))
    favorite = await facade.on_space_file_ready(_file_event(is_favorite_space=True))
    assert personal.reason == "personal_or_unmapped_level"
    assert favorite.reason == "favorite_space"
    assert repo.account.balance == 0


@pytest.mark.asyncio
async def test_p7b_skips_when_payee_is_space_manager_not_operator():
    """管理员上传、受益人为 uploader → skip；操作人身份不参与判断。"""
    repo = FakeAwardRepository({"G1": _rule(beneficiary="uploader")})
    outcome = await _facade(repo).on_space_file_ready(
        _file_event(uploader_id=9, space_manager_ids=frozenset({9}))
    )
    assert outcome.reason == "space_manager_payee"
    assert repo.account.balance == 0


@pytest.mark.asyncio
async def test_p7b_awards_when_operator_is_manager_but_payee_is_not():
    """他人发布、受益人为 publisher（非管理员）→ 应发分。"""
    repo = FakeAwardRepository({"G1": _rule(beneficiary="publisher", score=3)})
    outcome = await _facade(repo).on_space_file_ready(
        _file_event(
            uploader_id=4,
            publisher_id=5,
            space_manager_ids=frozenset({9}),  # 管理员是别人
        )
    )
    assert not outcome.skipped
    assert repo.account.balance == 3
    assert outcome.result.applied_delta == 3


@pytest.mark.asyncio
async def test_skips_platform_super_admin_payee():
    repo = FakeAwardRepository({"G1": _rule()})
    outcome = await _facade(repo, super_admins={4}).on_space_file_ready(_file_event(uploader_id=4))
    assert outcome.reason == "super_admin"
    assert repo.account.balance == 0


@pytest.mark.asyncio
async def test_beneficiary_publisher_resolves_payee():
    repo = FakeAwardRepository({"G1": _rule(beneficiary="publisher", score=2)})
    outcome = await _facade(repo).on_space_file_ready(
        _file_event(uploader_id=4, publisher_id=8)
    )
    assert not outcome.skipped
    log = next(iter(repo.logs.values()))
    assert log.user_id == 8
    assert log.beneficiary_role == "publisher"
    assert log.delta == 2


@pytest.mark.asyncio
async def test_disabled_rule_skips_without_error():
    repo = FakeAwardRepository({"G1": _rule(status="disabled")})
    outcome = await _facade(repo).on_space_file_ready(_file_event())
    assert outcome.reason == "rule_disabled"
    assert repo.account.balance == 0


@pytest.mark.asyncio
async def test_daily_cap_skips_entire_delta():
    repo = FakeAwardRepository({"G1": _rule(score=3, daily_cap=10)})
    repo.today = 8
    outcome = await _facade(repo).on_space_file_ready(_file_event())
    assert outcome.reason == "daily_cap"
    assert outcome.result.skipped_cap
    assert repo.account.balance == 0
    assert not repo.logs


@pytest.mark.asyncio
async def test_award_uses_idempotent_key_with_file_and_space():
    repo = FakeAwardRepository({"G1": _rule(score=3)})
    facade = _facade(repo)
    first = await facade.on_space_file_ready(_file_event(file_id=11, space_id=22))
    second = await facade.on_space_file_ready(_file_event(file_id=11, space_id=22))
    assert not first.skipped and second.result.replayed
    assert repo.account.balance == 3
    assert "earn:G1:11:22" in repo.logs


@pytest.mark.asyncio
async def test_exceptions_are_swallowed():
    class BoomRepo(FakeAwardRepository):
        async def get_rule(self, *_):
            raise RuntimeError("db down")

    outcome = await _facade(BoomRepo()).on_space_file_ready(_file_event())
    assert outcome.skipped and outcome.reason == "error"


@pytest.mark.asyncio
async def test_g7_awards_sharer_and_skips_manager_payee():
    repo = FakeAwardRepository({"G7": _rule("G7", beneficiary="sharer", score=4, daily_cap=20)})
    facade = _facade(repo)
    ok = await facade.on_document_shared(
        DocumentSharedEvent(
            tenant_id=1,
            share_entry_id=77,
            uploader_id=4,
            sharer_id=5,
            related_manager_ids=frozenset({9}),
        )
    )
    assert not ok.skipped and repo.account.balance == 4
    skipped = await facade.on_document_shared(
        DocumentSharedEvent(
            tenant_id=1,
            share_entry_id=78,
            uploader_id=4,
            sharer_id=9,
            related_manager_ids=frozenset({9}),
        )
    )
    assert skipped.reason == "space_manager_payee"


@pytest.mark.asyncio
async def test_g3_tier_differential_and_lifetime_cap():
    expr = {
        "mode": "tier",
        "tiers": [
            {"threshold": 75, "score": 5},
            {"threshold": 150, "score": 10},
            {"threshold": 300, "score": 15},
        ],
        "lifetime_cap": 15,
    }
    repo = FakeAwardRepository({"G3": _rule("G3", score_expr=expr, daily_cap=None)})
    facade = _facade(repo)
    first = await facade.on_favorite_changed(
        FavoriteChangedEvent(tenant_id=1, file_id=1, uploader_id=4, unique_favoriter_count=80)
    )
    assert not first.skipped and repo.account.balance == 5
    second = await facade.on_favorite_changed(
        FavoriteChangedEvent(tenant_id=1, file_id=1, uploader_id=4, unique_favoriter_count=160)
    )
    assert not second.skipped and repo.account.balance == 10
    third = await facade.on_favorite_changed(
        FavoriteChangedEvent(tenant_id=1, file_id=1, uploader_id=4, unique_favoriter_count=400)
    )
    assert not third.skipped and repo.account.balance == 15
    # 取消收藏再达阈值：进度不回退，不再补发。
    again = await facade.on_favorite_changed(
        FavoriteChangedEvent(tenant_id=1, file_id=1, uploader_id=4, unique_favoriter_count=400)
    )
    assert again.reason == "tier_already_granted"
    assert repo.account.balance == 15


@pytest.mark.asyncio
async def test_g4_answer_adopted():
    repo = FakeAwardRepository({"G4": _rule("G4", beneficiary="answerer", score=3)})
    outcome = await _facade(repo).on_answer_adopted(
        AnswerAdoptedEvent(tenant_id=1, answer_id=55, answerer_id=6)
    )
    assert not outcome.skipped
    assert "earn:G4:55" in repo.logs
    assert repo.account.balance == 3
