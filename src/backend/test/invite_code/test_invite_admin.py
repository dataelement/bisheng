import pytest

from bisheng.api.services.invite_code.invite_code import InviteCodeService
from bisheng.common.errcode.linsight import InviteCodeBatchInvalidError, InviteCodeLimitError, InviteCodeNotFoundError
from bisheng.database.models.invite_code import InviteCode, InviteCodeDao


@pytest.mark.asyncio
async def test_create_rejects_an_empty_batch():
    with pytest.raises(InviteCodeBatchInvalidError):
        await InviteCodeService.create_batch_invite_codes(object(), "  ", 1, 10)


@pytest.mark.asyncio
async def test_update_rejects_a_limit_below_the_times_already_used(monkeypatch):
    row = InviteCode(id=1, code="ABCD", batch_id="b", batch_name="batch", limit=5, used=3, bind_user=0)

    async def _get(code_id):
        return row

    monkeypatch.setattr(InviteCodeDao, "get_invite_code", _get)
    with pytest.raises(InviteCodeLimitError):
        await InviteCodeService.update_invite_code(1, "batch", 2)


@pytest.mark.asyncio
async def test_delete_reports_a_missing_code(monkeypatch):
    async def _delete(code_id):
        return False

    monkeypatch.setattr(InviteCodeDao, "delete_invite_code", _delete)
    with pytest.raises(InviteCodeNotFoundError):
        await InviteCodeService.delete_invite_code(9)
