"""F043: promoting a message's attachments out of the temp bucket.

Chat uploads land in the temp bucket, which wipes itself every 3 days. When the
message is actually sent we copy its attachments to the main bucket so they
live as long as the conversation. Files that are uploaded and never sent stay
in temp and expire on their own -- that is the point of promoting on send
rather than on upload.

See features/v2.6.0/043-chat-file-permanent-storage/design.md §3 decision 1.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.core.storage.chat_attachment import (
    CHAT_OBJECT_PREFIX,
    promote_chat_attachments,
    temp_object_name_from_url,
)


@pytest.fixture
def storage():
    client = MagicMock()
    client.bucket = "bisheng"
    client.tmp_bucket = "bisheng-tmp"
    client.copy_object = AsyncMock()
    with patch("bisheng.core.storage.chat_attachment.get_minio_storage", AsyncMock(return_value=client)):
        yield client


class TestPromoteChatAttachments:
    async def test_copies_temp_object_and_records_permanent_name(self, storage):
        # AC-01 — after this the file no longer depends on the temp bucket.
        files = [{"file_id": "f1", "filename": "a.png", "filepath": "/bisheng-tmp/abc.png"}]

        promoted = await promote_chat_attachments(files, user_id=7)

        storage.copy_object.assert_awaited_once()
        kwargs = storage.copy_object.await_args.kwargs
        assert kwargs["source_bucket"] == "bisheng-tmp"
        assert kwargs["source_object"] == "abc.png"
        assert kwargs["dest_object"].startswith(f"{CHAT_OBJECT_PREFIX}7/")
        assert promoted[0]["object_name"] == kwargs["dest_object"]

    async def test_already_permanent_file_is_left_alone(self, storage):
        # Task mode already uploads straight to the main bucket; it must flow
        # through the same code path without being copied a second time.
        files = [{"file_id": "f1", "filename": "a.png", "object_name": "linsight/session_files/9/f1.png"}]

        promoted = await promote_chat_attachments(files, user_id=7)

        storage.copy_object.assert_not_awaited()
        assert promoted[0]["object_name"] == "linsight/session_files/9/f1.png"

    async def test_one_failure_does_not_lose_the_other_attachments(self, storage):
        # Sending the message matters more than any single attachment.
        storage.copy_object.side_effect = [Exception("gone"), None]
        files = [
            {"file_id": "f1", "filename": "a.png", "filepath": "/bisheng-tmp/a.png"},
            {"file_id": "f2", "filename": "b.png", "filepath": "/bisheng-tmp/b.png"},
        ]

        promoted = await promote_chat_attachments(files, user_id=7)

        assert "object_name" not in promoted[0]  # stays unresolvable, flagged to the user later
        assert promoted[1]["object_name"].startswith(f"{CHAT_OBJECT_PREFIX}7/")

    async def test_extension_is_carried_over_from_the_display_name(self, storage):
        files = [{"file_id": "f1", "filename": "报告.PDF", "filepath": "/bisheng-tmp/xyz.pdf"}]

        promoted = await promote_chat_attachments(files, user_id=7)

        assert promoted[0]["object_name"].endswith(".pdf")

    async def test_no_files_is_a_no_op(self, storage):
        assert await promote_chat_attachments([], user_id=7) == []
        assert await promote_chat_attachments(None, user_id=7) == []
        storage.copy_object.assert_not_awaited()

    async def test_unreachable_storage_does_not_block_the_message(self):
        # Sending must survive a storage outage: the worst outcome allowed here
        # is an attachment that can't be viewed later, never a message the user
        # cannot send at all.
        files = [{"file_id": "f1", "filename": "a.png", "filepath": "/bisheng-tmp/a.png"}]
        with patch(
            "bisheng.core.storage.chat_attachment.get_minio_storage",
            AsyncMock(side_effect=RuntimeError("minio down")),
        ):
            assert await promote_chat_attachments(files, user_id=7) == files


class TestTempObjectNameFromUrl:
    """The link we issued at upload is what tells us the object to move."""

    def test_presigned_link_with_query_string(self):
        url = "/bisheng-tmp/abc.png?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Expires=604800"
        assert temp_object_name_from_url(url, "bisheng-tmp") == "abc.png"

    def test_link_that_still_carries_the_host(self):
        url = "http://minio:9000/bisheng-tmp/abc.png?X-Amz-Expires=1"
        assert temp_object_name_from_url(url, "bisheng-tmp") == "abc.png"

    def test_tenant_prefixed_object_keeps_its_full_key(self):
        url = "/bisheng-tmp/tenant_acme/abc.png"
        assert temp_object_name_from_url(url, "bisheng-tmp") == "tenant_acme/abc.png"

    def test_percent_encoded_name_is_decoded(self):
        url = "/bisheng-tmp/%E6%8A%A5%E5%91%8A.pdf"
        assert temp_object_name_from_url(url, "bisheng-tmp") == "报告.pdf"

    def test_link_outside_the_temp_bucket_is_not_ours_to_move(self):
        assert temp_object_name_from_url("/bisheng/knowledge/abc.png", "bisheng-tmp") is None

    def test_blank_link(self):
        assert temp_object_name_from_url("", "bisheng-tmp") is None
