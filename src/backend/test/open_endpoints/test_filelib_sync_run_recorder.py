import pytest

from bisheng.open_endpoints.domain.services.filelib_sync_run_recorder import (
    FILELIB_FILE_SYNC_JOB_CODE,
    SYNC_RECORD_ERROR_LIMIT_BYTES,
    is_error_message_truncated,
    job_code_to_interface_label,
    prepare_sync_error_message,
    record_sync_run_finished,
    utc_now_naive,
)


def test_prepare_sync_error_message_keeps_short_text():
    text = "parse failed: short reason"
    stored, truncated = prepare_sync_error_message(text)
    assert stored == text
    assert truncated is False
    assert is_error_message_truncated(stored) is False


def test_prepare_sync_error_message_truncates_over_limit():
    raw = "x" * (SYNC_RECORD_ERROR_LIMIT_BYTES + 1)
    stored, truncated = prepare_sync_error_message(raw)
    assert truncated is True
    assert stored is not None
    assert len(stored.encode("utf-8")) <= SYNC_RECORD_ERROR_LIMIT_BYTES
    assert is_error_message_truncated(stored) is True


def test_prepare_sync_error_message_redacts_developer_token_header():
    raw = "upstream rejected x-developer-token: bst_super_secret_value please retry"
    stored, truncated = prepare_sync_error_message(raw)
    assert truncated is False
    assert stored is not None
    assert "bst_super_secret_value" not in stored
    assert "[REDACTED]" in stored


def test_job_code_to_interface_label_distinguishes_sync_kinds():
    assert "file/sync" in job_code_to_interface_label(FILELIB_FILE_SYNC_JOB_CODE)
    assert "汽车板" in job_code_to_interface_label("automotive_sheet_intro")
    assert job_code_to_interface_label(FILELIB_FILE_SYNC_JOB_CODE) != job_code_to_interface_label(
        "automotive_sheet_intro"
    )


@pytest.mark.asyncio
async def test_record_sync_run_finished_swallows_repository_errors(monkeypatch):
    class _BoomSession:
        async def __aenter__(self):
            raise RuntimeError("db down")

        async def __aexit__(self, *_args):
            return False

    monkeypatch.setattr(
        "bisheng.open_endpoints.domain.services.filelib_sync_run_recorder.get_async_db_session",
        lambda: _BoomSession(),
    )
    await record_sync_run_finished(
        tenant_id=1,
        developer_token_id=9,
        job_code=FILELIB_FILE_SYNC_JOB_CODE,
        trigger_type="api",
        status="failed",
        start_time=utc_now_naive(),
        error_message="ignored because write fails",
    )
